"""Independent values and documented SQL branches for the THS Silver writer."""

import hashlib
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from time import perf_counter

import pytest

import orchestrator.defs.assets.moneyflow_ths as assets
import orchestrator.defs.checks.moneyflow_ths as checks
import orchestrator.defs.io.moneyflow_ths_silver_update as update
import orchestrator.defs.io.moneyflow_update_publication as publication
from orchestrator.defs.io.moneyflow_candidates import (
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
)
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_THS_SCHEMA,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

from . import test_moneyflow_ths_definitions as support

env = support.env
pytestmark = pytest.mark.usefixtures("isolated_moneyflow_transport")


@pytest.mark.parametrize("branch,expected_sql", [
    ("new", 31), ("changed", 35), ("reuse", 32),
    ("candidate_new", 39), ("candidate_changed", 43), ("candidate_reuse", 40),
    ("intent", 18), ("published", 15), ("complete", 15),
])
def test_actual_file_values_and_documented_sql_branches(env, monkeypatch, record_property, branch, expected_sql):
    assert support.run(env, "raw_tushare_moneyflow_ths_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_ths", support.DAY)
    target = silver_moneyflow_path(env.lake, "moneyflow_ths", support.DAY)
    kwargs = {"lake_root": env.lake, "staging_root": env.staging, "operation_id": "measured", "trade_date": support.DAY}
    previous = None
    if branch in {"changed", "reuse", "candidate_changed", "candidate_reuse"}:
        update.update_moneyflow_ths_silver(**{**kwargs, "operation_id": "previous"})
        previous = (target.stat().st_ino, target.read_bytes())
    if branch in {"changed", "candidate_changed"}:
        support._change_file(env, raw, "* REPLACE(99::DECIMAL(24,4) AS net_amount)")
    if branch.startswith("candidate_"):
        directory = moneyflow_candidate_directory(env.staging, "measured", support.DAY, dataset="moneyflow_ths")
        directory.mkdir(parents=True, exist_ok=True)
        # Literal DATE fixture, independent from the producer's strptime formula.
        with moneyflow_candidate_connection(env.staging) as connection:
            connection.execute(
                "COPY (SELECT * REPLACE(DATE '2026-10-08' AS trade_date) FROM read_parquet($raw,hive_partitioning=false) ORDER BY trade_date,ts_code) TO $out (FORMAT PARQUET)",
                {"raw": str(raw), "out": str(directory / "silver.parquet")},
            )
    if branch in {"intent", "published"}:
        original_checkpoint = publication._checkpoint

        def paused(path, state):
            if state["stage"] == ("intent" if branch == "intent" else "complete"):
                if branch == "intent":
                    original_checkpoint(path, state)
                raise RuntimeError("pause at existing publication boundary")
            original_checkpoint(path, state)

        monkeypatch.setattr(publication, "_checkpoint", paused)
        with pytest.raises(RuntimeError, match="pause at existing"):
            update.update_moneyflow_ths_silver(**kwargs)
        monkeypatch.setattr(publication, "_checkpoint", original_checkpoint)
    elif branch == "complete":
        update.update_moneyflow_ths_silver(**kwargs)
    sql = []
    original_connect = update.moneyflow_candidate_connection

    @contextmanager
    def measured(directory):
        with original_connect(directory) as connection:
            class Connection:
                def execute(self, statement, *args, **kwargs):
                    sql.append(statement)
                    return connection.execute(statement, *args, **kwargs)
            yield Connection()

    monkeypatch.setattr(update, "moneyflow_candidate_connection", measured)
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    started = perf_counter()
    result = update.update_moneyflow_ths_silver(**kwargs)
    elapsed = perf_counter() - started
    assert len(sql) == expected_sql
    assert result["raw_sha256"] == digest and result["row_count"] == 3
    with original_connect(env.staging) as connection:
        values = connection.execute(
            "SELECT trade_date,ts_code,name,net_amount,buy_md_amount FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(target)],
        ).fetchall()
    amount = Decimal("99.0000") if branch in {"changed", "candidate_changed"} else Decimal("-5.1234")
    assert values == [
        (date(2026, 10, 8), "000001.SZ", None, amount, None),
        (date(2026, 10, 8), "000002.SZ", "同名股票", amount, None),
        (date(2026, 10, 8), "600000.SH", "同名股票", amount, None),
    ]
    if branch in {"reuse", "candidate_reuse"}:
        assert result["promotion_mode"] == "reuse"
        assert (target.stat().st_ino, target.read_bytes()) == previous
    assert len(env.source.calls) == 2
    record_property("ths_stage4_silver", {"branch": branch, "sql": len(sql), "seconds": elapsed, "raw_bytes": raw.stat().st_size, "silver_bytes": target.stat().st_size})


@pytest.mark.parametrize("stage", ["entry", "intent"])
def test_cancel_preserves_old_silver_then_original_checkpoint_resumes(env, monkeypatch, stage):
    assert support.run(env, "raw_tushare_moneyflow_ths_update_job").success
    kwargs = {"lake_root": env.lake, "staging_root": env.staging, "operation_id": "old", "trade_date": support.DAY}
    update.update_moneyflow_ths_silver(**kwargs)
    target = silver_moneyflow_path(env.lake, "moneyflow_ths", support.DAY)
    previous = target.read_bytes()
    support._change_file(env, raw_moneyflow_path(env.lake, "moneyflow_ths", support.DAY), "* REPLACE(0::DECIMAL(24,4) AS net_amount)")
    kwargs["operation_id"] = "cancelled"
    cancelled = {"value": stage == "entry"}
    original_checkpoint = publication._checkpoint

    def checkpoint(path, state):
        original_checkpoint(path, state)
        if state["stage"] == "intent":
            cancelled["value"] = True

    def check_cancel():
        if cancelled["value"]:
            raise MoneyflowContractError("user_cancel")

    monkeypatch.setattr(publication, "_checkpoint", checkpoint)
    with pytest.raises(MoneyflowContractError, match="user_cancel"):
        update.update_moneyflow_ths_silver(**kwargs, check_cancel=check_cancel)
    assert target.read_bytes() == previous
    monkeypatch.setattr(publication, "_checkpoint", original_checkpoint)
    result = update.update_moneyflow_ths_silver(**kwargs)
    assert result["row_count"] == 3 and len(env.source.calls) == 2


@pytest.mark.parametrize("failure", ["metadata", "formal_check"])
def test_published_silver_survives_failure_and_manual_same_day_job_recovers(env, monkeypatch, failure):
    assert support.run(env, "raw_tushare_moneyflow_ths_update_job").success
    original = assets._result if failure == "metadata" else checks.audit_standardization

    def rejected(*args, **kwargs):
        if failure == "metadata":
            raise RuntimeError("test_metadata_failure")
        raise MoneyflowContractError("test_standardization_check_failure")

    module, name = (assets, "_result") if failure == "metadata" else (checks, "audit_standardization")
    monkeypatch.setattr(module, name, rejected)
    result = support.run(env, "silver_moneyflow_ths_update_job", raise_on_error=False)
    target = silver_moneyflow_path(env.lake, "moneyflow_ths", support.DAY)
    assert not result.success and target.is_file()
    saved = target.read_bytes()
    monkeypatch.setattr(module, name, original)
    assert support.run(env, "silver_moneyflow_ths_update_job").success
    assert target.read_bytes() == saved and len(env.source.calls) == 2


def test_silver_capacity_preserves_twenty_thousand_rows_and_nulls(env, record_property):
    # Input types follow the verified source contract, independently of the
    # candidate builder. No source calls or event history are needed.
    raw = raw_moneyflow_path(env.lake, "moneyflow_ths", support.DAY)
    raw.parent.mkdir(parents=True, exist_ok=True)
    fields = ["'20261008'::VARCHAR AS trade_date", "lpad(CAST(i AS VARCHAR),6,'0') || '.SZ' AS ts_code"]
    fields += [f'NULL::{column.type} AS "{column.name}"' for column in RAW_TUSHARE_MONEYFLOW_THS_SCHEMA[2:]]
    with moneyflow_candidate_connection(env.staging) as connection:
        connection.execute(f"COPY (SELECT {','.join(fields)} FROM range(20000) t(i)) TO $out (FORMAT PARQUET)", {"out": str(raw)})
    started = perf_counter()
    result = update.update_moneyflow_ths_silver(
        lake_root=env.lake, staging_root=env.staging, operation_id="capacity", trade_date=support.DAY,
    )
    elapsed = perf_counter() - started
    target = silver_moneyflow_path(env.lake, "moneyflow_ths", support.DAY)
    with moneyflow_candidate_connection(env.staging) as connection:
        fact = connection.execute(
            "SELECT count(*),count(DISTINCT ts_code),min(ts_code),max(ts_code),min(trade_date),max(trade_date),count(name),count(net_amount),typeof(min(trade_date)) FROM read_parquet(?,hive_partitioning=false)",
            [str(target)],
        ).fetchone()
    assert fact == (20000, 20000, "000000.SZ", "019999.SZ", date(2026, 10, 8), date(2026, 10, 8), 0, 0, "DATE")
    assert result["row_count"] == 20000 and env.source.calls == []
    record_property("ths_stage4_silver_capacity", {"seconds": elapsed, "rows": 20000, "raw_bytes": raw.stat().st_size, "silver_bytes": target.stat().st_size})
