import multiprocessing
from dataclasses import replace
from threading import Event, Timer
from time import monotonic

import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    WeeklyCaptureStore,
)
from orchestrator.defs.stock_weekly_source import (
    capture_weekly_source_unit,
    fetch_weekly_supervised,
    weekly_source_params,
)

from .stock_weekly_capture_test_support import StaticWorker, weekly_plan


def test_explicit_object_range_fields():
    plan = weekly_plan()
    assert weekly_source_params(plan.units[0]) == {
        "ts_code": "000005.SZ",
        "start_date": "20200224",
        "end_date": "20200301",
    }
    assert (
        len(
            fetch_weekly_supervised(
                StaticWorker(), plan.units[0], plan.budget, lambda: False
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "mode,reason",
    [("failed", "source_failed"), ("zero_columns", "source_schema_mismatch")],
)
def test_failures_are_not_empty(mode, reason):
    plan = weekly_plan()
    with pytest.raises(WeeklyCaptureError, match=reason) as error:
        fetch_weekly_supervised(
            StaticWorker(mode), plan.units[0], plan.budget, lambda: False
        )
    assert "secret-token" not in str(error.value)


def test_timeout_kills_worker_and_precall_cancel():
    plan = weekly_plan()
    before = {child.pid for child in multiprocessing.active_children()}
    started = monotonic()
    with pytest.raises(WeeklyCaptureError, match="source_timeout"):
        fetch_weekly_supervised(
            StaticWorker("blocked"),
            plan.units[0],
            replace(plan.budget, call_timeout_seconds=1),
            lambda: False,
        )
    assert monotonic() - started < 4
    assert {child.pid for child in multiprocessing.active_children()} == before
    with pytest.raises(WeeklyCaptureError, match="canceled"):
        fetch_weekly_supervised(
            StaticWorker(), plan.units[0], plan.budget, lambda: True
        )


def test_cancel_running_worker_kills_process():
    plan = weekly_plan()
    event = Event()
    timer = Timer(0.4, event.set)
    timer.start()
    try:
        with pytest.raises(WeeklyCaptureError, match="canceled"):
            fetch_weekly_supervised(
                StaticWorker("blocked"), plan.units[0], plan.budget, event.is_set
            )
    finally:
        timer.join()
    assert not multiprocessing.active_children()


def test_success_empty_has_schema_and_receipt(tmp_path):
    plan = weekly_plan()
    store = WeeklyCaptureStore(tmp_path, plan)
    with store.locked(), duckdb.connect() as connection:
        receipt = capture_weekly_source_unit(
            connection,
            plan.units[0],
            worker=StaticWorker("empty"),
            store=store,
            cancel=lambda: False,
        )
        assert receipt["status"] == "success_empty" and receipt["source_rows"] == 0
        assert store.resume(connection, plan.units[0]) == receipt


def test_retry_cap_survives_restart_without_secret_leak(tmp_path):
    plan = weekly_plan()
    store = WeeklyCaptureStore(tmp_path, plan)
    with store.locked(), duckdb.connect() as connection:  # noqa: SIM117 -- Keep source-failure scope explicit.
        with pytest.raises(WeeklyCaptureError, match="source_failed"):
            capture_weekly_source_unit(
                connection,
                plan.units[0],
                worker=StaticWorker("failed"),
                store=store,
                cancel=lambda: False,
            )
    with (
        WeeklyCaptureStore(tmp_path, plan).locked() as reopened,
        duckdb.connect() as connection,
        pytest.raises(WeeklyCaptureError, match="unit_attempt_budget"),
    ):
        capture_weekly_source_unit(
            connection,
            plan.units[0],
            worker=StaticWorker(),
            store=reopened,
            cancel=lambda: False,
        )
    assert all(
        "secret-token" not in path.read_text() for path in tmp_path.rglob("*.json")
    )


def test_retries_use_shared_persisted_cap(tmp_path):
    import json

    from orchestrator.defs.run_contracts.stock_weekly import WeeklyBudget

    plan = weekly_plan(WeeklyBudget(max_retries=1))
    store = WeeklyCaptureStore(tmp_path, plan)
    with (
        store.locked(),
        duckdb.connect() as connection,
        pytest.raises(WeeklyCaptureError, match="source_failed"),
    ):
        capture_weekly_source_unit(
            connection,
            plan.units[0],
            worker=StaticWorker("failed"),
            store=store,
            cancel=lambda: False,
        )
    requests = json.loads((store.root / "requests.json").read_text())
    assert requests["attempts"] == 2 and requests["ended_at"] is not None
