from dataclasses import replace
from threading import Event

import pytest

from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.bootstrap.stock_weekly_history import capture_weekly_history
from orchestrator.defs.run_contracts.stock_weekly import WeeklyBudget

from .stock_weekly_capture_test_support import (
    FakePsqlExporter,
    bind_plan_evidence,
    prod_frame,
    prod_plan,
)


def test_cancel_resume_without_refetch_and_monotonic_progress(tmp_path):
    plan = bind_plan_evidence(
        prod_plan(("000001.SZ", "000005.SZ"), budget=WeeklyBudget(prod_code_batch=1)),
        tmp_path,
    )
    event = Event()
    observed = []

    def observe(payload):
        observed.append(payload.copy())
        if payload["completed_units"] == 1:
            event.set()

    resource = FakePsqlExporter(prod_frame("000001.SZ"))
    with pytest.raises(WeeklyCaptureError, match="canceled"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_exporter=resource,
            cancel=event.is_set,
            progress=observe,
        )
    assert resource.calls == 1
    assert [p["completed_units"] for p in observed] == sorted(
        p["completed_units"] for p in observed
    )
    resumed = FakePsqlExporter(prod_frame())
    result = capture_weekly_history(plan, capture_root=tmp_path, prod_exporter=resumed)
    assert (
        result["completed_units"] == 2
        and result["source_rows"] == 2
        and result["formal_writes"] == 0
    )
    assert resumed.calls == 1
    repeated = FakePsqlExporter()
    assert (
        capture_weekly_history(plan, capture_root=tmp_path, prod_exporter=repeated)
        == result
    )
    assert repeated.calls == 0


def test_plan_mutation_under_same_hash_rejected(tmp_path):
    plan = bind_plan_evidence(prod_plan(), tmp_path)
    capture_weekly_history(
        plan, capture_root=tmp_path, prod_exporter=FakePsqlExporter()
    )
    changed = replace(plan, budget=replace(plan.budget, fetch_batch_rows=1))
    with pytest.raises(WeeklyCaptureError, match="plan_changed"):
        capture_weekly_history(
            changed, capture_root=tmp_path, prod_exporter=FakePsqlExporter()
        )


def test_incomplete_source_never_marked_complete(tmp_path):
    plan = bind_plan_evidence(prod_plan(), tmp_path)
    with pytest.raises(WeeklyCaptureError, match="source_count_changed"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_exporter=FakePsqlExporter(control_count=2),
        )
    assert not list(tmp_path.rglob("receipt.json"))
    assert list(tmp_path.rglob("transport.csv"))


def test_external_evidence_tamper_stops_before_source_call(tmp_path):
    plan = bind_plan_evidence(prod_plan(), tmp_path)
    resource = FakePsqlExporter()
    (tmp_path / "inventory.csv").write_text("tampered")
    with pytest.raises(WeeklyCaptureError, match="source_evidence_hash_mismatch"):
        capture_weekly_history(plan, capture_root=tmp_path, prod_exporter=resource)
    assert resource.calls == 0


def test_actual_process_exit_releases_lock_and_committed_unit_resumes(tmp_path):
    import multiprocessing

    from .stock_weekly_capture_test_support import capture_then_exit

    process = multiprocessing.get_context("spawn").Process(
        target=capture_then_exit, args=(str(tmp_path),)
    )
    process.start()
    process.join(timeout=10)
    try:
        assert process.exitcode == 17
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        process.close()
    plan = bind_plan_evidence(
        prod_plan(("000001.SZ", "000005.SZ"), budget=WeeklyBudget(prod_code_batch=1)),
        tmp_path,
    )
    remaining = FakePsqlExporter()
    result = capture_weekly_history(
        plan, capture_root=tmp_path, prod_exporter=remaining
    )
    assert result["completed_units"] == 2 and remaining.calls == 1


def test_csv_artifact_tamper_blocks_resume_without_network(tmp_path):
    plan = bind_plan_evidence(prod_plan(), tmp_path)
    capture_weekly_history(
        plan, capture_root=tmp_path, prod_exporter=FakePsqlExporter()
    )
    next(tmp_path.rglob("transport.csv")).write_text("tampered")
    exporter = FakePsqlExporter()
    with pytest.raises(WeeklyCaptureError, match="capture_hash_mismatch"):
        capture_weekly_history(plan, capture_root=tmp_path, prod_exporter=exporter)
    assert exporter.calls == 0


def test_csv_preserves_null_decimal_and_anomalous_source_date(tmp_path):
    import json
    from decimal import Decimal

    from orchestrator.defs.duckdb_connection import (
        DuckDBConnectionSettings,
        connect_configured_duckdb,
    )

    plan = bind_plan_evidence(prod_plan(), tmp_path)
    frame = prod_frame(trade_date="20200227")
    frame.loc[0, "open"] = "123456789.12340000"
    frame.loc[0, "end_date"] = None
    capture_weekly_history(
        plan, capture_root=tmp_path, prod_exporter=FakePsqlExporter(frame)
    )
    chunk = next(tmp_path.rglob("chunk-*.parquet"))
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=tmp_path / "query_spill")
    ) as con:
        assert con.execute(
            "SELECT open,close,trade_date,end_date FROM read_parquet(?,hive_partitioning=false)",
            [str(chunk)],
        ).fetchone() == (Decimal("123456789.1234"), None, "20200227", None)
    receipt = json.loads(next(tmp_path.rglob("receipt.json")).read_text())
    assert receipt["source_rows"] == 1


def test_csv_excess_precision_rejected_without_receipt(tmp_path):
    plan = bind_plan_evidence(prod_plan(), tmp_path)
    frame = prod_frame()
    frame.loc[0, "open"] = "1.12345"
    with pytest.raises(WeeklyCaptureError, match="decimal_precision_loss"):
        capture_weekly_history(
            plan, capture_root=tmp_path, prod_exporter=FakePsqlExporter(frame)
        )
    assert not list(tmp_path.rglob("receipt.json"))
