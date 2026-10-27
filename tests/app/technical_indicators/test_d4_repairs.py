"""Only the three bounded D4 repair cases from the approved LLD.

Expectations come from LLD12.4 and d4-three-repairs-20261027. These tests
use actual Admission, App tasks and worker handoff; calculate and Control
are controlled, so no source, SQL or real interrupt monitor is created.
Only pytest's JUnit properties report costs; historical reports are untouched.
"""

import importlib
import json
from pathlib import Path
import threading
from time import monotonic

import anyio
import pytest

from test_admission import (
    FakeControl, light_case,
    test_normal_grant_and_prewait_validation as _normal_grant_case,
)
from test_execution_cancellation import (
    inspect_release_locals, install_control, request, runtime,
)
from src.app.runtime.technical_indicators import execution
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, SourceReadError,
)


@pytest.fixture
def fake_control_calls(monkeypatch, record_property):
    """Measure only this test; the runner owns the new repair ledger."""
    metrics = dict(fake_controls=0, real_controls=0, input_rows=0, sql_logical_rows=0)
    original = FakeControl.__init__

    def create(control, *args, **kwargs):
        metrics["fake_controls"] += 1
        original(control, *args, **kwargs)

    monkeypatch.setattr(FakeControl, "__init__", create)
    try:
        yield metrics
    finally:
        record_property("d4_repair_metrics", json.dumps(metrics, sort_keys=True))


def test_repeatable_regression_ignores_acceptance_history(monkeypatch, fake_control_calls):
    root = Path(__file__).resolve().parents[3]
    history = root / "reports/technical_indicator_kernel_d4_20261027"
    previous = tuple(FakeControl.instances)
    original_read, original_write = Path.read_text, Path.write_text

    def read(path, *args, **kwargs):
        assert not path.absolute().is_relative_to(history), "Regression read acceptance history"
        return original_read(path, *args, **kwargs)

    def write(path, *args, **kwargs):
        assert not path.absolute().is_relative_to(history), "Regression wrote acceptance history"
        return original_write(path, *args, **kwargs)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "read_text", read)
        guarded.setattr(Path, "write_text", write)
        guarded.syspath_prepend(str(root / "tests/architecture"))
        architecture = importlib.import_module("test_technical_indicator_dependencies")
        for _ in range(2):
            with guarded.context() as independent:
                _normal_grant_case(independent)
            architecture.test_indicator_dependency_boundaries()
            assert tuple(FakeControl.instances) == previous
    assert fake_control_calls["fake_controls"] == 8


class _CompletionBoundary:
    """Hold only this request's done wait, without changing worker execution."""

    def __init__(self, event):
        self.finished = event()
        self.hold_main = event()
        self.cancel_error = None

    def set(self):
        self.finished.set()

    async def wait(self):
        try:
            await self.finished.wait()
            await self.hold_main.wait()
        except anyio.get_cancelled_exc_class() as error:
            self.cancel_error = error
            # The original cancellation is delivered only after the worker's
            # error has been published and run_worker has really finished.
            with anyio.CancelScope(shield=True):
                await self.finished.wait()
            raise


def _exercise_cancel_order(monkeypatch, *, feedback, original_failure=None):
    async def scenario():
        rt = runtime()
        native_event = anyio.Event
        started, stopped, completed, never = (native_event() for _ in range(4))
        boundary = _CompletionBoundary(native_event)
        release_worker = threading.Event()
        outcomes, scopes, order, messages, releases = {}, {}, [], [], []
        cancelled_type = anyio.get_cancelled_exc_class()

        def created(control):
            def done_event():
                # This callback runs inside _execute's Control construction;
                # the next public Event is this request's done, not Admission.
                monkeypatch.setattr(execution.anyio, "Event", native_event)
                return boundary

            monkeypatch.setattr(execution.anyio, "Event", done_event)

        controls = install_control(
            monkeypatch, on_create=created, on_stop=lambda control: stopped.set(),
        )

        def calculate(service, normalized):
            anyio.from_thread.run_sync(started.set)
            try:
                assert release_worker.wait(1), "The controlled worker was not released"
                if original_failure is not None:
                    raise original_failure
                assert service.control.stop_reason == "cancel"
                if feedback == "framework_cancel":
                    raise cancelled_type("Controlled worker cancellation feedback")
                service.control.check_active()
                raise AssertionError("The stopped worker unexpectedly continued")
            except BaseException as error:
                outcomes["worker_error"] = error
                raise
            finally:
                order.append("worker_exit")

        monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate", calculate)
        original_release = rt.admission.release

        def release(lease):
            assert boundary.finished.is_set() and "worker_exit" in order
            inspect_release_locals(failure=True)
            releases.append(lease)
            order.append("release")
            original_release(lease)

        monkeypatch.setattr(rt.admission, "release", release)

        async def receive():
            await never.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        async def invoke():
            try:
                with anyio.CancelScope() as scope:
                    scopes["request"] = scope
                    try:
                        await execution.execute_http(
                            rt, request(), arrived_at=monotonic(), receive=receive, send=send,
                        )
                    except BaseException as error:
                        outcomes["main_error"] = error
                        if isinstance(error, cancelled_type):
                            raise
            finally:
                completed.set()

        try:
            with anyio.fail_after(2):
                async with anyio.create_task_group() as group:
                    group.start_soon(invoke)
                    await started.wait()
                    if original_failure is not None:
                        release_worker.set()
                        await boundary.finished.wait()
                    scopes["request"].cancel()
                    await stopped.wait()
                    if original_failure is None:
                        assert rt.admission.active_leases
                    release_worker.set()
                    await completed.wait()
            assert len(controls) == len(releases) == 1
            assert boundary.cancel_error is not None and boundary.finished.is_set()
            assert order.index("worker_exit") < order.index("release")
            assert not messages and not rt.admission.active_leases
            if original_failure is not None:
                assert outcomes["worker_error"] is original_failure
                assert outcomes["main_error"] is original_failure
            else:
                expected = cancelled_type if feedback == "framework_cancel" else CalculationCancelledError
                assert isinstance(outcomes["worker_error"], expected)
                assert outcomes["main_error"] is boundary.cancel_error
                assert outcomes["main_error"] is not outcomes["worker_error"]
        finally:
            release_worker.set()
            boundary.hold_main.set()
            if "request" in scopes:
                scopes["request"].cancel()
            await rt.aclose()

    anyio.run(scenario)


def test_external_cancel_preserves_main_error_after_worker_feedback(monkeypatch, fake_control_calls):
    with light_case("test_external_cancel_preserves_main_error_after_worker_feedback"):
        for feedback in ("control_cancel", "framework_cancel"):
            with monkeypatch.context() as independent:
                _exercise_cancel_order(independent, feedback=feedback)
    assert fake_control_calls["fake_controls"] == 2


def test_original_worker_failure_precedes_later_cancel(monkeypatch, fake_control_calls):
    failure = SourceReadError("Independent original source failure")
    with light_case("test_original_worker_failure_precedes_later_cancel"):
        with monkeypatch.context() as independent:
            _exercise_cancel_order(independent, feedback="real_failure", original_failure=failure)
    assert fake_control_calls["fake_controls"] == 1
