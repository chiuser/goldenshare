from dataclasses import replace
from threading import Event

import pytest

from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.bootstrap.stock_weekly_history import capture_weekly_history
from orchestrator.defs.run_contracts.stock_weekly import WeeklyBudget

from .stock_weekly_capture_test_support import (
    FakeConnection,
    FakeResource,
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

    resource = FakeResource(FakeConnection(prod_frame("000001.SZ")))
    with pytest.raises(WeeklyCaptureError, match="canceled"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_resource=resource,
            cancel=event.is_set,
            progress=observe,
        )
    assert resource.connection_count == 1
    assert [p["completed_units"] for p in observed] == sorted(
        p["completed_units"] for p in observed
    )
    resumed = FakeResource(FakeConnection(prod_frame()))
    result = capture_weekly_history(plan, capture_root=tmp_path, prod_resource=resumed)
    assert (
        result["completed_units"] == 2
        and result["source_rows"] == 2
        and result["formal_writes"] == 0
    )
    assert resumed.connection_count == 1
    repeated = FakeResource()
    assert (
        capture_weekly_history(plan, capture_root=tmp_path, prod_resource=repeated)
        == result
    )
    assert repeated.connection_count == 0


def test_plan_mutation_under_same_hash_rejected(tmp_path):
    plan = bind_plan_evidence(prod_plan(), tmp_path)
    capture_weekly_history(plan, capture_root=tmp_path, prod_resource=FakeResource())
    changed = replace(plan, budget=replace(plan.budget, fetch_batch_rows=1))
    with pytest.raises(WeeklyCaptureError, match="plan_changed"):
        capture_weekly_history(
            changed, capture_root=tmp_path, prod_resource=FakeResource()
        )


def test_incomplete_source_never_marked_complete(tmp_path):
    plan = bind_plan_evidence(prod_plan(), tmp_path)
    with pytest.raises(WeeklyCaptureError, match="source_count_changed"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_resource=FakeResource(FakeConnection(control_count=2)),
        )
    assert not list(tmp_path.rglob("receipt.json"))
    assert list(tmp_path.rglob("chunk-*.parquet"))


def test_external_evidence_tamper_stops_before_source_call(tmp_path):
    plan = bind_plan_evidence(prod_plan(), tmp_path)
    resource = FakeResource()
    (tmp_path / "inventory.csv").write_text("tampered")
    with pytest.raises(WeeklyCaptureError, match="source_evidence_hash_mismatch"):
        capture_weekly_history(plan, capture_root=tmp_path, prod_resource=resource)
    assert resource.connection_count == 0


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
    remaining = FakeResource()
    result = capture_weekly_history(
        plan, capture_root=tmp_path, prod_resource=remaining
    )
    assert result["completed_units"] == 2 and remaining.connection_count == 1
