import multiprocessing
import os
import signal
import traceback
from dataclasses import replace
from threading import Event, Timer
from time import monotonic

import duckdb
import pytest
from dagster._core.errors import DagsterExecutionInterruptedError
from dagster._utils.interrupts import raise_interrupts_as

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    WeeklyCaptureStore,
)
from orchestrator.defs.stock_weekly_source import (
    _source_exception_category,
    _weekly_worker_entry,
    capture_weekly_source_unit,
    copy_source_diagnostic,
    fetch_weekly_request_supervised,
    fetch_weekly_supervised,
    weekly_source_params,
)

from .stock_weekly_capture_test_support import (
    SourceFailureWorker,
    StaticWorker,
    weekly_plan,
)


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
    with pytest.raises(WeeklyCaptureError, match="source_timeout") as error:
        fetch_weekly_supervised(
            StaticWorker("blocked"),
            plan.units[0],
            replace(plan.budget, call_timeout_seconds=1),
            lambda: False,
        )
    assert error.value.__notes__ == ["source_diagnostic=supervisor_timeout"]
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


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, DagsterExecutionInterruptedError])
def test_execution_interrupt_reaps_source_worker(error_type):
    """A real SIGINT unwinds the shared supervisor and leaves no SDK child."""
    plan = weekly_plan()
    before = {child.pid for child in multiprocessing.active_children()}
    interrupted_pids = set()
    original_handler = signal.getsignal(signal.SIGINT)
    original_term_handler = signal.getsignal(signal.SIGTERM)

    def interrupt_after_spawn():
        interrupted_pids.update(
            child.pid for child in multiprocessing.active_children() if child.pid not in before
        )
        assert interrupted_pids
        os.kill(os.getpid(), signal.SIGINT)

    try:
        with pytest.raises(error_type), raise_interrupts_as(error_type):
            fetch_weekly_supervised(
                StaticWorker("blocked"),
                plan.units[0],
                plan.budget,
                lambda: False,
                interrupt_after_spawn,
            )
    finally:
        # Dagster also maps SIGTERM to SIGINT; keep this test's handlers isolated.
        signal.signal(signal.SIGTERM, original_term_handler)

    assert signal.getsignal(signal.SIGINT) == original_handler
    assert {child.pid for child in multiprocessing.active_children()} == before


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
    with store.locked(), duckdb.connect() as connection:
        with pytest.raises(WeeklyCaptureError, match="source_failed") as error:
            capture_weekly_source_unit(
                connection,
                plan.units[0],
                worker=SourceFailureWorker("proxy"),
                store=store,
                cancel=lambda: False,
            )
        assert str(error.value) == "source_failed"
        assert error.value.__notes__ == ["source_diagnostic=network_proxy"]
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


class RecordingSender:
    def __init__(self):
        self.messages = []
        self.closed = False

    def send(self, payload):
        self.messages.append(payload)

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "mode,category",
    [
        ("proxy", "network_proxy"),
        ("tls", "network_tls"),
        ("connect_timeout", "network_timeout"),
        ("read_timeout", "network_timeout"),
        ("connection", "network_connection"),
        ("request", "network_request"),
        ("decode", "response_decode"),
        ("requests_decode", "response_decode"),
        ("schema", "response_schema"),
        ("dependency", "worker_dependency"),
        ("type", "worker_type"),
        ("value", "worker_value"),
        ("unknown", "unknown"),
        ("capture_unknown", "unknown"),
        ("arbitrary_type", "unknown"),
        ("business", "unknown"),
    ],
)
def test_ipc_has_only_fixed_classification(mode, category):
    sender = RecordingSender()
    _weekly_worker_entry(sender, SourceFailureWorker(mode), {}, ("ts_code",), 1)
    assert sender.closed
    assert sender.messages == [("source_failed", None, category)]
    assert "synthetic-secret-token" not in repr(sender.messages)
    assert "password" not in repr(sender.messages)
    assert "https://" not in repr(sender.messages)


@pytest.mark.parametrize(
    "mode,category", [("proxy", "network_proxy"), ("unknown", "unknown")]
)
def test_actual_spawn_preserves_safe_note_and_serialized_failure(mode, category):
    import sys

    from dagster._utils.error import serializable_error_info_from_exc_info

    plan = weekly_plan()
    try:
        fetch_weekly_request_supervised(
            SourceFailureWorker(mode), {}, ("ts_code",), 1, plan.budget, lambda: False
        )
    except WeeklyCaptureError as error:
        assert str(error) == "source_failed"
        assert error.__notes__ == ["source_diagnostic=" + category]
        rendered = "".join(traceback.format_exception(error))
        serialized = serializable_error_info_from_exc_info(sys.exc_info())
        assert "source_diagnostic=" + category in serialized.message
        assert "synthetic-secret-token" not in rendered + repr(serialized)
        assert "password" not in rendered + repr(serialized)
    else:
        pytest.fail("source failure became successful empty response")
    assert not multiprocessing.active_children()


def test_actual_spawn_eof_is_distinct_from_worker_exception():
    plan = weekly_plan()
    with pytest.raises(WeeklyCaptureError) as error:
        fetch_weekly_request_supervised(
            SourceFailureWorker("exit"), {}, ("ts_code",), 1, plan.budget, lambda: False
        )
    assert str(error.value) == "source_failed"
    assert error.value.__notes__[0] in {
        "source_diagnostic=worker_eof",
        "source_diagnostic=worker_exit",
    }
    assert not multiprocessing.active_children()


def test_copy_diagnostic_rejects_untrusted_notes():
    source = RuntimeError("synthetic-secret-token")
    source.add_note("password=https://example.invalid/")
    source.add_note("source_diagnostic=synthetic-secret-token")
    source.add_note("source_diagnostic=network_proxy")
    target = copy_source_diagnostic(
        source, ValueError("monthly_request_budget_exhausted")
    )
    assert str(target) == "monthly_request_budget_exhausted"
    assert target.__notes__ == ["source_diagnostic=network_proxy"]
    clean = copy_source_diagnostic(None, ValueError("budget"))
    assert not hasattr(clean, "__notes__")


def test_ipc_success_and_contract_failures_keep_existing_reasons():
    for worker, reason, category in (
        (StaticWorker("empty"), "ok", None),
        (StaticWorker("zero_columns"), "source_schema_mismatch", "response_schema"),
        (
            SourceFailureWorker("row_budget"),
            "unit_row_budget_exceeded",
            "unit_row_budget",
        ),
    ):
        sender = RecordingSender()
        _weekly_worker_entry(sender, worker, {}, ("ts_code",), 1)
        observed_reason, frame, observed_category = sender.messages[0]
        assert (observed_reason, observed_category) == (reason, category)
        assert frame.empty if reason == "ok" else frame is None


def test_classification_does_not_retry_a_failed_resource_import(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "orchestrator.defs.resources", None)
    assert (
        _source_exception_category(ImportError("synthetic-secret-token"))
        == "worker_dependency"
    )
    assert (
        _source_exception_category(RuntimeError("synthetic-secret-token")) == "unknown"
    )
