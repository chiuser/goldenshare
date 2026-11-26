"""Isolated PostgreSQL acceptance for the nine-bar index volume repair."""

from datetime import datetime
from pathlib import Path
from runpy import run_path
from time import perf_counter

from alembic.migration import MigrationContext
from alembic.operations import Operations
import duckdb
import pytest
from sqlalchemy import event, insert, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from src.foundation.ingestion.index_minute_volume_repair import PILOT, freeze_volume_repair
from src.foundation.ingestion.source_client import DatasetSourceClient
from src.foundation.models.raw.raw_index_mins import RawIndexMins
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.worker import OperationsWorker
from src.ops.runtime.worker_lane import WorkerLane
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
from src.ops.services.task_run_service import TaskRunCommandService
from src.scripts.index_minute_volume_repair import enqueue_volume_repair
from tests.wealth_watchlist_postgres_support import PG_BIN, isolated_postgres


pytestmark = pytest.mark.skipif(
    not (PG_BIN / "initdb").is_file(), reason="requires an existing PostgreSQL test binary"
)


# 2026-11-24 DG Raw mirror, 000001.SH, 30min. All nine times and
# volumes were matched against Prod in the stage 2 readiness audit.
PILOT_BARS = (
    ("09:30", 3567.8406, 3567.8406, 3567.8406, 3567.8406, 7725349.0, 12728771688.5, 3567.8406),
    ("10:00", 3568.2476, 3585.2227, 3558.7341, 3574.3083, 164682975.0, 277033100392.0, 3575.2197),
    ("10:30", 3573.7024, 3574.5808, 3561.4004, 3563.7773, 62484293.0, 101924161040.0, 3566.523),
    ("11:00", 3563.512, 3570.06, 3560.7598, 3561.332, 41365177.0, 63449243576.1, 3565.9185),
    ("11:30", 3561.0278, 3561.0278, 3547.3691, 3555.4915, 39295999.0, 56998502987.5, 3554.1262),
    ("13:30", 3554.8386, 3561.083, 3549.308, 3553.6116, 39897952.0, 61664359121.6, 3555.0083),
    ("14:00", 3553.7703, 3559.6504, 3549.3052, 3549.34, 32801311.0, 49060686839.1, 3554.911),
    ("14:30", 3549.1382, 3552.8306, 3539.007, 3548.4082, 47814920.0, 66642094426.1, 3544.9382),
    ("15:00", 3547.057, 3550.5234, 3541.3499, 3548.3694, 57458320.0, 82360090238.0, 3545.8445),
)


def _seed(engine):
    code, freq, day = PILOT
    bars = [
        dict(ts_code=code, freq=freq, trade_time=datetime.fromisoformat(f"{day}T{stamp}"),
             open=op, high=high, low=low, close=close, vol=vol, amount=amount, exchange="XSHG", vwap=vwap)
        for stamp, op, high, low, close, vol, amount, vwap in PILOT_BARS
    ]
    with engine.begin() as connection:
        migration = Path(__file__).resolve().parents[1] / "alembic/versions/20260506_000098_add_index_mins_dataset.py"
        with Operations.context(MigrationContext.configure(connection)):
            run_path(migration)["upgrade"]()
        connection.exec_driver_sql("CREATE SCHEMA ops")
        for model in (TaskRun, TaskRunNode, TaskRunIssue):
            model.__table__.create(connection)
        connection.execute(insert(RawIndexMins), [
            *bars, {**bars[-1], "ts_code": "399001.SZ", "exchange": "XSHE", "vol": 120_000_000.0},
        ])
    return bars


def _make_preview(path, bars):
    with duckdb.connect() as connection:
        connection.execute("""
            CREATE TABLE preview(ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
                                 trade_date DATE, old_vol DOUBLE, target_vol DOUBLE)
        """)
        connection.executemany(
            "INSERT INTO preview VALUES (?, ?, ?, ?, ?, ?)",
            [(r["ts_code"], r["freq"], r["trade_time"], PILOT[2], r["vol"], r["vol"] * 100) for r in bars],
        )
        connection.execute("COPY preview TO ? (FORMAT PARQUET)", [str(path)])


def _assert_readback(session, bars):
    table = RawIndexMins.__table__
    rows = session.execute(select(table).where(table.c.ts_code == PILOT[0]).order_by(table.c.trade_time)).mappings()
    assert [dict(row) for row in rows] == [{**row, "vol": row["vol"] * 100} for row in bars]
    assert session.scalar(select(table.c.vol).where(table.c.ts_code == "399001.SZ")) == 120_000_000
    assert session.execute(text("""
        SELECT count(*), sum(vol), sum(amount) FROM core_serving.index_minute_bar
        WHERE ts_code = '000001.SH' AND freq = '30min'
          AND trade_time >= '2026-11-24' AND trade_time < '2026-11-25'
    """)).one() == (9, 49_352_629_600, pytest.approx(771_861_010_308.9, abs=0.01))


def _run(session, *, manifest, digest):
    task = enqueue_volume_repair(session, manifest=manifest, sha256=digest)
    return OperationsWorker(lane=WorkerLane.INDEX_MINS).run_task_run(session, task.id)


def test_frozen_pilot_through_index_worker(tmp_path, monkeypatch):
    def unexpected_fetch(*args, **kwargs):
        pytest.fail("Frozen manifest execution must not fetch from Tushare")

    monkeypatch.setattr(DatasetSourceClient, "fetch", unexpected_fetch)
    cluster = tmp_path / "pg"
    cluster.mkdir()
    with isolated_postgres(cluster) as engine:
        bars = _seed(engine)
        preview = tmp_path / "preview.parquet"
        manifest = tmp_path / "frozen.jsonl"
        _make_preview(preview, bars)
        session_factory = sessionmaker(engine)
        digest = freeze_volume_repair(session_factory, preview=preview, target=manifest, scope="pilot")
        assert sum(row["vol"] for row in bars) == 493_526_296

        locked_selects = []
        updates = []
        locked_at = {}

        def trace_sql(connection, _cursor, statement, params, _context, _many):
            if statement.startswith("SELECT") and "raw_tushare.index_mins" in statement and "FOR UPDATE" in statement:
                locked_selects.append((statement, params))
                locked_at[connection] = perf_counter()
            if statement.startswith("UPDATE raw_tushare.index_mins"):
                updates.append(statement)

        def trace_commit(connection):
            if connection in locked_at:
                print(f"locking query returned to commit start: {(perf_counter() - locked_at.pop(connection)) * 1000:.1f} ms")

        event.listen(engine, "after_cursor_execute", trace_sql)
        event.listen(engine, "commit", trace_commit)

        with session_factory() as session:
            started = perf_counter()
            run = _run(session, manifest=manifest, digest=digest)
            print(f"pilot worker enqueue + run + finalize: {(perf_counter() - started) * 1000:.1f} ms")
            assert (run.status, run.unit_done, run.rows_fetched, run.rows_saved) == ("success", 1, 9, 9)
            assert session.get(TaskRunNode, run.current_node_id).status == "success"
            _assert_readback(session, bars)

        # A fresh worker and session replay the same frozen file.
        with session_factory() as session:
            run = _run(session, manifest=manifest, digest=digest)
            assert (run.status, run.unit_done, run.rows_fetched, run.rows_saved) == ("success", 1, 9, 0)
            _assert_readback(session, bars)

        assert len(locked_selects) == 2
        assert len(updates) == 1 and " SET vol=" in updates[0]
        statement, params = locked_selects[0]
        with engine.connect() as connection:
            plan = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, params
            ).scalar_one()[0]["Plan"]
            assert plan["Actual Rows"] == 9

            def nodes(item):
                yield item["Node Type"]
                for child in item.get("Plans", ()):
                    yield from nodes(child)

            print(f"locking query plan: {' / '.join(nodes(plan))}, {plan['Actual Rows']} returned rows")

        manifest.write_bytes(manifest.read_bytes() + b"\n")
        with session_factory() as session, pytest.raises(ValueError, match="SHA-256"):
            enqueue_volume_repair(session, manifest=manifest, sha256=digest)


def test_pilot_conflict_observation_failure_and_cancel(tmp_path, monkeypatch):
    cluster = tmp_path / "pg"
    cluster.mkdir()
    with isolated_postgres(cluster) as engine:
        bars = _seed(engine)
        preview = tmp_path / "preview.parquet"
        manifest = tmp_path / "frozen.jsonl"
        _make_preview(preview, bars)
        session_factory = sessionmaker(engine)
        digest = freeze_volume_repair(session_factory, preview=preview, target=manifest, scope="pilot")
        table = RawIndexMins.__table__
        target = table.c.ts_code == PILOT[0]
        first = table.c.trade_time == bars[0]["trade_time"]
        with engine.begin() as connection:
            connection.execute(update(table).where(target, first).values(amount=1.0))
        with session_factory() as session:
            run = _run(session, manifest=manifest, digest=digest)
            assert (run.status, run.unit_done, run.rows_saved) == ("failed", 0, 0)
            assert session.get(TaskRunNode, run.current_node_id).status == "failed"
            assert session.scalars(select(table.c.vol).where(target).order_by(table.c.trade_time)).all() == [
                row["vol"] for row in bars
            ]

        with engine.begin() as connection:
            connection.execute(update(table).where(target, first).values(amount=bars[0]["amount"]))

        def fail_observation(*args):
            raise SQLAlchemyError("test progress transaction failure")

        monkeypatch.setattr(TaskRunIngestionContext, "_update_current_running_node", fail_observation)
        update_progress = TaskRunIngestionContext.update_progress

        def cancel_after_commit(self, **kwargs):
            update_progress(self, **kwargs)
            if kwargs["unit_done"] == 1:
                with session_factory() as separate:
                    TaskRunCommandService().request_cancel(
                        separate, task_run_id=kwargs["run_id"], requested_by_user_id=1,
                    )

        monkeypatch.setattr(TaskRunIngestionContext, "update_progress", cancel_after_commit)

        with session_factory() as session:
            run = _run(session, manifest=manifest, digest=digest)
            assert (run.status, run.unit_done, run.rows_saved) == ("canceled", 1, 9)
            assert session.get(TaskRunNode, run.current_node_id).status == "canceled"
            _assert_readback(session, bars)

        monkeypatch.setattr(TaskRunIngestionContext, "update_progress", update_progress)
        with session_factory() as session:
            retry = TaskRunCommandService().retry_task_run(session, task_run_id=run.id, requested_by_user_id=1)
            result = OperationsWorker(lane=WorkerLane.INDEX_MINS).run_task_run(session, retry.id)
            assert (result.status, result.unit_done, result.rows_saved) == ("success", 1, 0)
            _assert_readback(session, bars)
