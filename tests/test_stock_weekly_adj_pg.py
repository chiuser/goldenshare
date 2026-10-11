"""Real PG checks in a newly created test database; never a formal database."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from src.foundation.datasets.stock_weekly_adj_contracts import WeeklyAdjContractError
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.stock_weekly_adj_execution import (
    bounded_unit_transaction,
    publisher_lock,
)
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.task_run_dispatcher import TaskRunDispatchOutcome
from src.ops.runtime.worker import OperationsWorker
from test_stock_weekly_adj_p2 import (
    CODE,
    OLD,
    WEEK,
    NOW,
    Calendar,
    Daily,
    Factor,
    Raw,
    Serving,
    Delivery,
    fake_pages,
    planned,
    requested,
    row,
    seed_frontier,
    seed_weekly_data,
)


def migrate(engine, revision):
    path = next(Path("alembic/versions").glob(f"{revision}_*.py"))
    spec = importlib.util.spec_from_file_location("weekly_pg_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with context.begin_transaction(), Operations.context(context):
            module.upgrade()


@pytest.fixture
def pg():
    value = os.getenv("ANNS_P1_TEST_DATABASE_URL")
    if not value:
        pytest.skip("task-owned isolated PostgreSQL required")
    url = make_url(value)
    assert url.drivername == "postgresql+psycopg"
    assert str(url.query.get("host", "")).startswith("/private/tmp/anns-p1-pg-socket-")
    assert url.host is None and url.password is None and url.database == "postgres"
    base = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "weekly_p2_" + uuid4().hex[:12]
    with base.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url.set(database=name))
    with engine.begin() as connection:
        for schema in ("core", "core_serving", "raw_tushare", "ops"):
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Table only: migration 186 must perform the actual concurrent index build.
        connection.execute(CreateTable(Raw.__table__))
        for model in (Calendar, Daily, Factor, Serving, TaskRun, TaskRunNode):
            model.__table__.create(connection)
    migrate(engine, "20261010_000185")
    migrate(engine, "20261010_000186")
    seed_weekly_data(engine)
    yield engine
    engine.dispose()
    base.dispose()
    # Keep test databases for readback. The caller stops its own temporary cluster.


def run(pg, definition, request, units, pages, **callbacks):
    with Session(pg) as session:
        executor = IngestionExecutor(session)
        executor.source_client.iter_weekly_adj_pages = pages
        return executor.run(
            request=request, definition=definition, units=units, **callbacks
        )


def batch_rows(unit):
    return (
        [row(WEEK, close="20", qfq="20")]
        if unit.trade_date
        else [row(), row(WEEK, close="20", qfq="20")]
    )


def test_pg_migrations_index_and_append_only_guard(pg):
    migrate(pg, "20261010_000186")  # Exact valid index is safely reusable.
    with pg.connect() as connection:
        index = connection.execute(
            text("""SELECT indisvalid, indisready, indislive,
            pg_get_indexdef(indexrelid) AS definition FROM pg_index
            WHERE indexrelid='raw_tushare.idx_raw_stk_period_bar_adj_week_date_code'::regclass""")
        ).one()
        assert index.indisvalid and index.indisready and index.indislive
        assert (
            "(trade_date, ts_code) WHERE ((freq)::text = 'week'::text)"
            in index.definition
        )
    seed_frontier(pg)
    with Session(pg) as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                text("UPDATE core.stock_weekly_adj_delivery SET outcome=outcome")
            )
        session.rollback()
        assert session.scalar(select(Delivery.revision)) is not None


def test_pg_publisher_lock_competes_and_releases(pg):
    definition, _, _ = planned(pg)
    policy = definition.planning.weekly_adj_policy
    with publisher_lock(pg, policy):
        with pytest.raises(WeeklyAdjContractError) as caught:
            with publisher_lock(pg, policy):
                pytest.fail("second publisher acquired a held lock")
        assert caught.value.code == "weekly_adj.writer_busy"
    with publisher_lock(pg, policy):
        pass


def test_pg_cancel_after_commit_resume_and_observer_failure(pg):
    seed_frontier(pg)
    definition, request, units = planned(
        pg, requested(mode="point", trigger="schedule", code=None)
    )
    request = replace(request, run_id=1)
    calls, stopped = [], [False]

    def pages(unit):
        calls.append(unit.unit_id)
        return batch_rows(unit)

    def progress(snapshot, message):
        if snapshot.unit_done == 1:
            stopped[0] = True

    with pytest.raises(IngestionCanceledError):
        run(
            pg,
            definition,
            request,
            units,
            fake_pages(pages),
            cancel_checker=lambda _: stopped[0],
            progress_reporter=progress,
        )
    with Session(pg) as session:
        assert (
            len(
                session.scalars(
                    select(Delivery).where(Delivery.record_kind == "unit")
                ).all()
            )
            == 1
        )
        assert (
            session.scalar(
                select(Delivery).where(Delivery.record_kind == "batch_closed")
            )
            is None
        )
        assert session.get(Raw, (CODE, WEEK, "week")).close_qfq == 20
    definition, restored, remaining = planned(pg, request)

    def broken_observer(*args):
        raise RuntimeError("injected independent observer failure")

    result = run(
        pg,
        definition,
        restored,
        remaining,
        fake_pages(pages),
        progress_reporter=broken_observer,
    )
    assert result.unit_done == 2 and result.rows_written == 3
    assert calls == [unit.unit_id for unit in units]
    replay = run(
        pg,
        definition,
        restored,
        remaining,
        fake_pages(lambda _: pytest.fail("replay must not download committed units")),
    )
    assert replay.unit_done == 2 and replay.rows_written == 3


def test_pg_abrupt_process_exit_releases_lock_and_resumes(pg):
    seed_frontier(pg)
    script = """
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_stock_weekly_adj_p2 import planned, requested, row, WEEK, fake_pages
from src.foundation.ingestion.executor import IngestionExecutor
engine=create_engine(os.environ['WEEKLY_P2_CHILD_DATABASE_URL'])
definition, request, units=planned(engine, requested(mode='point', trigger='schedule', code=None))
def progress(snapshot, message):
    if snapshot.unit_done == 1: os._exit(23)
with Session(engine) as session:
    executor=IngestionExecutor(session)
    executor.source_client.iter_weekly_adj_pages=fake_pages(lambda unit: [row(WEEK,close='20',qfq='20')])
    executor.run(request=request, definition=definition, units=units, progress_reporter=progress)
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(Path("tests").resolve()) + os.pathsep + str(Path.cwd()),
        "WEEKLY_P2_CHILD_DATABASE_URL": pg.url.render_as_string(hide_password=False),
    }
    child = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, timeout=30
    )
    assert child.returncode == 23, child.stderr.decode()[-2000:]
    definition, request, units = planned(
        pg, requested(mode="point", trigger="schedule", code=None)
    )
    calls = []

    def rows(unit):
        calls.append(unit.unit_id)
        return batch_rows(unit)

    result = run(pg, definition, request, units, fake_pages(rows))
    assert result.unit_done == 2 and calls == [units[1].unit_id]


def test_pg_raw_and_serving_rollback_together_on_publisher_failure(pg, monkeypatch):
    definition, request, units = planned(pg)

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO core_serving.stk_period_bar_adj"):
            raise RuntimeError("injected serving write failure")

    event.listen(pg, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="serving write failure"):
            run(pg, definition, request, units, fake_pages(lambda _: [row()]))
    finally:
        event.remove(pg, "before_cursor_execute", fail)
    with Session(pg) as session:
        assert session.get(Raw, (CODE, OLD, "week")).close_qfq == 10
        assert session.get(Serving, (CODE, OLD, "week")).close_qfq == 10
        assert (
            session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
            is None
        )


def test_pg_sql_and_row_lock_timeouts_are_local_and_rollback(pg):
    definition, _, _ = planned(pg)
    policy = replace(
        definition.planning.weekly_adj_policy, db_statement_timeout_seconds=1
    )
    started = time.monotonic()
    with pytest.raises(DBAPIError, match="statement timeout"):
        with Session(pg) as session:
            with bounded_unit_transaction(session, policy, lambda: None):
                session.add(Raw(**row(WEEK, close="20", qfq="20")))
                session.flush()
                session.execute(text("SELECT pg_sleep(3)"))
    assert time.monotonic() - started < 3
    with pg.connect() as held:
        held.execute(
            text(
                "SELECT ts_code FROM raw_tushare.stk_period_bar_adj WHERE freq='week' FOR UPDATE"
            )
        )
        lock_policy = replace(
            policy, db_statement_timeout_seconds=4, lock_timeout_seconds=1
        )
        with pytest.raises(DBAPIError, match="lock timeout"):
            with Session(pg) as session:
                with bounded_unit_transaction(session, lock_policy, lambda: None):
                    session.execute(
                        text(
                            "UPDATE raw_tushare.stk_period_bar_adj SET close_qfq=close_qfq WHERE freq='week'"
                        )
                    )
    with Session(pg) as session:
        assert session.get(Raw, (CODE, WEEK, "week")) is None
        assert session.scalar(text("SHOW statement_timeout")) == "0"
        assert session.scalar(text("SHOW lock_timeout")) == "0"


@pytest.mark.parametrize("status", ["failed", "canceled", "success"])
def test_pg_weekly_finalizer_keeps_business_progress_and_node_terminal(pg, status):
    with Session(pg) as session:
        run_record = TaskRun(
            task_type="dataset_action",
            resource_key="stk_period_bar_adj_week",
            action="maintain",
            title="weekly PG acceptance",
            trigger_source="manual",
            status="running",
            requested_at=NOW,
            rows_saved=500,
            rows_fetched=2000,
            request_payload_json={
                "execution_context": {"contract_kind": "stock_weekly_adj/v1"}
            },
            ingestion_diagnostics_json={
                "runtime": {"weekly_adj": {"stage": "单元已提交"}}
            },
        )
        session.add(run_record)
        session.flush()
        node = TaskRunNode(
            task_run_id=run_record.id,
            node_key="weekly",
            node_type="action",
            title="weekly",
            sequence_no=1,
            status="running",
        )
        session.add(node)
        session.flush()
        run_record.current_node_id = node.id
        session.commit()
        result = OperationsWorker()._finalize_task_run(
            session,
            run_record.id,
            TaskRunDispatchOutcome(status=status, rows_saved=700, rows_fetched=2000),
        )
        session.refresh(node)
        assert result.status == node.status == status
        assert (
            result.rows_saved
            == node.rows_saved
            == (700 if status == "success" else 500)
        )
        assert result.ingestion_diagnostics_json == node.ingestion_diagnostics_json


@pytest.mark.parametrize(
    "resource,context",
    [
        ("stk_period_bar_adj_month", {"contract_kind": "stock_weekly_adj/v1"}),
        ("stk_period_bar_adj_week", {"contract_kind": "other"}),
        ("stk_period_bar_adj_week", None),
    ],
)
def test_pg_finalizer_does_not_apply_weekly_policy_to_other_contracts(
    pg, resource, context
):
    with Session(pg) as session:
        record = TaskRun(
            task_type="dataset_action",
            resource_key=resource,
            action="maintain",
            title="non-weekly finalizer guard",
            trigger_source="manual",
            status="running",
            requested_at=NOW,
            rows_saved=500,
            request_payload_json={"execution_context": context},
            ingestion_diagnostics_json={"runtime": {"other": {"stage": "running"}}},
        )
        session.add(record)
        session.commit()
        result = OperationsWorker()._finalize_task_run(
            session, record.id, TaskRunDispatchOutcome(status="failed", rows_saved=3)
        )
        assert result.rows_saved == 3
        assert result.ingestion_diagnostics_json == {}


def test_pg_bootstrap_preserves_unverified_source_with_nullable_audit_basis(pg):
    from test_stock_weekly_adj_basis import RETIRED, BASIS, retired_row, seed_retired
    from test_stock_weekly_adj_p1_contracts import weekly_definition
    from src.foundation.ingestion.stock_weekly_adj_planning import (
        resolve_weekly_adj_units,
    )

    seed_retired(pg, basis_factor=False)
    definition = weekly_definition()
    with Session(pg) as session:
        request, units = resolve_weekly_adj_units(
            session,
            requested(code=None, end=OLD),
            definition,
            now=datetime(2026, 6, 6, tzinfo=timezone.utc),
        )
    assert request.execution_context["business_plan"]["metadata"]["bootstrap"] is True
    result = run(
        pg,
        definition,
        request,
        units,
        fake_pages(lambda _: [row(qfq="10", basis=BASIS), retired_row()]),
    )
    assert result.rows_written == 2
    with Session(pg) as session:
        raw = session.get(Raw, (RETIRED, OLD, "week"))
        assert raw.end_date == BASIS and raw.close_qfq == Decimal(".35")
        record = session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
        assert record.basis_date is None
        assert record.reason_summary["basis_audit"]["checked"] == 0
        assert record.reason_summary["basis_audit"]["unverified_codes"] == 2


def test_pg_delivery_checks_payload_in_jsonb_and_preserves_json_isolation(pg):
    from copy import deepcopy
    import re
    from src.foundation.dao.stock_weekly_adj_delivery_dao import (
        StockWeeklyAdjDeliveryDAO,
    )
    from src.foundation.datasets.stock_weekly_adj_contracts import (
        WeeklyAdjExecutionPolicy,
        digest,
    )
    from test_stock_weekly_adj_p1_contracts import record

    values = record(uuid4())
    statements = []

    def track(conn, cursor, statement, parameters, context, executemany):
        if "FROM core.stock_weekly_adj_delivery" in statement:
            statements.append(statement)

    event.listen(pg, "before_cursor_execute", track)
    try:
        with Session(pg) as session:
            dao = StockWeeklyAdjDeliveryDAO(session)
            receipt = dao.append(values, WeeklyAdjExecutionPolicy())
            revision = receipt.revision
            session.commit()
            assert not re.search(
                r"\.payload(?:\s|,)", statements[0].partition("\nFROM")[0]
            )
            assert ".payload = " in statements[0]
            receipt.payload["rows"][0]["close_qfq"] = "999.0000"
            assert values["payload"]["rows"][0]["close_qfq"] == "1.2500"
            session.expire_all()
            assert (
                session.get(Delivery, revision).payload["rows"][0]["close_qfq"]
                == "1.2500"
            )
            changed = deepcopy(values)
            changed["payload"]["rows"][0]["close_qfq"] = "2.2500"
            changed["payload_digest"] = digest(changed["payload"])
            with pytest.raises(WeeklyAdjContractError, match="不同交付值"):
                dao.append(changed, WeeklyAdjExecutionPolicy())
            session.rollback()
            changed = deepcopy(values)
            changed["rows_preserved"] = 1
            with pytest.raises(WeeklyAdjContractError, match="不同交付值"):
                dao.append(changed, WeeklyAdjExecutionPolicy())
            session.rollback()
    finally:
        event.remove(pg, "before_cursor_execute", track)


@pytest.mark.parametrize("problem", ["fail", "cancel"])
def test_pg_later_write_block_rolls_back_prior_blocks(pg, monkeypatch, problem):
    from src.foundation.ingestion.writer import DatasetWriter
    from test_stock_weekly_adj_memory import large_rows, point_plan

    definition, request, units = point_plan(pg)
    source = large_rows()
    original = DatasetWriter._write_raw_and_core
    state = {"calls": 0, "cancel": False}

    def write(**kwargs):
        state["calls"] += 1
        if problem == "fail" and state["calls"] == 2:
            raise RuntimeError("later write failed")
        result = original(**kwargs)
        if state["calls"] == 2:
            state["cancel"] = True
        return result

    monkeypatch.setattr(DatasetWriter, "_write_raw_and_core", staticmethod(write))
    expected = RuntimeError if problem == "fail" else IngestionCanceledError
    with pytest.raises(expected):
        run(
            pg,
            definition,
            request,
            units,
            fake_pages(lambda _: source),
            cancel_checker=lambda _: state["cancel"],
        )
    with Session(pg) as session:
        assert session.get(Raw, (CODE, OLD, "week")).close_qfq == Decimal("10")
        assert session.get(Serving, (CODE, OLD, "week")).close_qfq == Decimal("10")
        assert session.get(Raw, (source[1]["ts_code"], OLD, "week")) is None
        assert (
            session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
            is None
        )
