"""Four original D4 lifecycle classes, with controlled work and no data I/O.

LLD12.4/12.4b/13 define the independent expectations. Admission and the
App entry points are real; only ExecutionControl and calculate are replaced.
No connection, SQL, source fixture or real interrupt monitor is created here.
"""

import asyncio
from datetime import date
import inspect
import threading
from time import monotonic

import anyio
import pytest

from test_admission import FakeControl, light_case, make_config
from src.app.runtime.technical_indicators import execution
from src.app.runtime.technical_indicators.admission import AdmissionController
from src.app.runtime.technical_indicators.composition import TechnicalIndicatorRuntime
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.indicators import create_builtin_registry
from src.foundation.technical_indicators.contracts import (
    CalculationResult, CalculationStatistics, CalculationValues, OutputRange,
    PriceAdjustmentResult, RequestedRange, SeriesDescription, SourceResult,
)
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationDeadlineError, CapacityBusyError,
    ResourceCleanupError,
)


def request():
    return CalculationRequest("stock", "600000.SH", "day", (
        CalculationInstance("ma", "ma", {"period": 20}),
    ))


def literal_result():
    """A result contract literal, not a calculated price or expected algorithm."""
    day = date(2026, 1, 2)
    return CalculationResult(
        "2.0.0", SeriesDescription("stock", "600000.SH", "day", "qfq", "Asia/Shanghai",
                                  "CNY", "share", "CNY"),
        RequestedRange(None, None, None, 1000),
        SourceResult("controlled-lifecycle", "1", "qfq", None, day, day, None),
        PriceAdjustmentResult(None, None, None, None, False, "1"),
        (day,), None,
        (CalculationValues("ma", "ma", "1.0.0", (("period", 20),), (("value", (None,)),)),),
        OutputRange(day, day, 1), CalculationStatistics(0, 0, 0, 0, 0, 0, 0.0), "",
    )


def runtime():
    config = make_config()
    return TechnicalIndicatorRuntime(config, create_builtin_registry(), object(), AdmissionController(config))


def install_control(monkeypatch, *, on_stop=None, on_create=None):
    created = []
    loop = asyncio.get_running_loop()

    def factory(*, arrived_at, config):
        control = FakeControl(arrived_at=arrived_at, config=config)
        original = control.request_stop

        def stop(reason):
            original(reason)
            if on_stop is not None:
                loop.call_soon_threadsafe(on_stop, control)

        control.request_stop = stop
        if on_create is not None:
            on_create(control)
        created.append(control)
        return control

    monkeypatch.setattr(execution, "ExecutionControl", factory)
    return created


def inspect_release_locals(*, failure):
    """Inspect only the owning entry's explicit, documented result variables."""
    frame = inspect.currentframe()
    owner = None
    try:
        while frame is not None:
            if frame.f_code.co_name == "_execute" and frame.f_code.co_filename == execution.__file__:
                owner = frame
                break
            frame = frame.f_back
        assert owner is not None
        values = owner.f_locals
        assert values["result"] is None and values["body"] is None
        assert values["handoff"] == {"result": None, "body": None, "error": None}
        if failure:
            assert values["return_result"] is None
    finally:
        # The observer must not become another reference to the entry's frame.
        owner = frame = None


def assert_ended_frames_empty(error, *names):
    seen, pending, found = set(), [error], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        pending.extend(item for item in (current.__cause__, current.__context__) if item is not None)
        trace = current.__traceback__
        while trace is not None:
            if trace.tb_frame.f_code.co_name in names:
                assert trace.tb_frame.f_locals == {}
                found.add(trace.tb_frame.f_code.co_name)
            trace = trace.tb_next
    assert found == set(names)


def test_execution_cancelled(monkeypatch):
    with light_case("test_execution_cancelled"):
        async def scenario():
            rt = runtime()
            started_a, started_b, stopped_a = anyio.Event(), anyio.Event(), anyio.Event()
            done_a, done_b = anyio.Event(), anyio.Event()
            release_a, release_b = threading.Event(), threading.Event()
            controls, outcomes, scopes, order = [], {}, {}, []

            def on_stop(control):
                if controls and control is controls[0]:
                    order.append("stop_a")
                    stopped_a.set()

            created = install_control(monkeypatch, on_stop=on_stop)

            def controlled_calculate(service, normalized):
                is_a = not controls
                controls.append(service.control)
                anyio.from_thread.run_sync((started_a if is_a else started_b).set)
                try:
                    assert (release_a if is_a else release_b).wait(1), "Test did not release its controlled worker"
                    service.control.check_active()
                    return literal_result()
                finally:
                    order.append("worker_a_exit" if is_a else "worker_b_exit")

            monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate", controlled_calculate)
            original_release = rt.admission.release

            def release(lease):
                inspect_release_locals(failure=lease.control is controls[0])
                order.append("release_a" if lease.control is controls[0] else "release_b")
                original_release(lease)

            monkeypatch.setattr(rt.admission, "release", release)

            async def call(label, done):
                with anyio.CancelScope() as scope:
                    scopes[label] = scope
                    try:
                        outcomes[label] = await execution.execute_library(rt, request(), arrived_at=monotonic())
                    except BaseException as error:
                        outcomes[label] = error
                        raise
                    finally:
                        done.set()

            try:
                with anyio.fail_after(2):
                    async with anyio.create_task_group() as group:
                        group.start_soon(call, "a", done_a)
                        await started_a.wait()
                        group.start_soon(call, "b", done_b)
                        await started_b.wait()
                        scopes["a"].cancel()
                        await stopped_a.wait()
                        assert len(rt.admission.active_leases) == 2
                        assert controls[1].stop_reason is None
                        release_a.set()
                        await done_a.wait()
                        assert len(rt.admission.active_leases) == 1
                        assert controls[1].stop_reason is None
                        release_b.set()
                        await done_b.wait()
                assert isinstance(outcomes["a"], anyio.get_cancelled_exc_class())
                assert outcomes["b"] == literal_result()
                assert created == controls and controls[1].stop_reason is None
                assert order.index("stop_a") < order.index("worker_a_exit") < order.index("release_a")
                assert not rt.admission.active_leases
            finally:
                release_a.set()
                release_b.set()
                await rt.aclose()

        anyio.run(scenario)


def test_execution_deadline(monkeypatch):
    with light_case("test_execution_deadline"):
        async def scenario():
            rt = runtime()
            started, stopped, finished = anyio.Event(), anyio.Event(), anyio.Event()
            release_worker = threading.Event()
            calls, outcome = [], {}

            def on_create(control):
                if not calls:
                    control.work_until = monotonic() + 0.2

            created = install_control(monkeypatch, on_create=on_create,
                                      on_stop=lambda control: stopped.set())

            def controlled_calculate(service, normalized):
                calls.append(service.control)
                if len(calls) == 1:
                    anyio.from_thread.run_sync(started.set)
                    assert release_worker.wait(1), "Test did not release the controlled deadline worker"
                    service.control.check_active()
                return literal_result()

            monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate", controlled_calculate)

            async def call():
                try:
                    await execution.execute_library(rt, request(), arrived_at=monotonic())
                except BaseException as error:
                    outcome["error"] = error
                finally:
                    finished.set()

            try:
                with anyio.fail_after(2):
                    async with anyio.create_task_group() as group:
                        group.start_soon(call)
                        await started.wait()
                        await stopped.wait()
                        assert created[0].stop_reason == "deadline"
                        assert len(rt.admission.active_leases) == 1 and not finished.is_set()
                        release_worker.set()
                        await finished.wait()
                assert isinstance(outcome["error"], CalculationDeadlineError)
                assert not rt.admission.active_leases
                assert await execution.execute_library(rt, request(), arrived_at=monotonic()) == literal_result()
                assert calls == created and created[0].stop_reason == "deadline"
                assert created[1].stop_reason is None and not rt.admission.active_leases
            finally:
                release_worker.set()
                await rt.aclose()

        anyio.run(scenario)


def test_cleanup_failure(monkeypatch):
    with light_case("test_cleanup_failure"):
        async def scenario():
            install_control(monkeypatch)
            for mode in ("calculation_cleanup", "release_only", "primary_and_release"):
                rt = runtime()
                primary = ResourceCleanupError("Deliberate controlled calculation cleanup failure")
                cause = OSError("Deliberate controlled resource close failure")
                release_error = RuntimeError("Deliberate controlled admission release failure")
                releases = []

                def failing_calculate(service, normalized):
                    result = literal_result()
                    if mode != "release_only":
                        try:
                            raise cause
                        except OSError:
                            raise primary from cause
                    return result

                monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate", failing_calculate)
                original_release = rt.admission.release

                def release(lease):
                    releases.append(lease)
                    inspect_release_locals(failure=mode != "release_only")
                    if mode != "release_only":
                        assert_ended_frames_empty(primary, "failing_calculate")
                    original_release(lease)
                    if mode != "calculation_cleanup":
                        raise release_error

                monkeypatch.setattr(rt.admission, "release", release)
                expected = release_error if mode == "release_only" else primary
                try:
                    returned = None
                    with pytest.raises(type(expected)) as caught:
                        returned = await execution.execute_library(rt, request(), arrived_at=monotonic())
                    assert returned is None and caught.value is expected
                    assert len(releases) == 1 and not rt.admission.active_leases
                    if expected is primary:
                        assert caught.value.__cause__ is cause
                        assert_ended_frames_empty(caught.value, "failing_calculate")
                    if mode == "primary_and_release":
                        assert any("Admission release" in note and str(release_error) in note
                                   for note in caught.value.__notes__)
                    # The entry was still running while release failed; its own
                    # explicit failure result references must also be cleared.
                    trace = caught.value.__traceback__
                    while trace is not None:
                        if trace.tb_frame.f_code.co_name == "_execute":
                            assert trace.tb_frame.f_locals["return_result"] is None
                            assert trace.tb_frame.f_locals["result"] is None
                            assert trace.tb_frame.f_locals["body"] is None
                        trace = trace.tb_next
                finally:
                    await rt.aclose()

        anyio.run(scenario)


def test_shutdown(monkeypatch):
    with light_case("test_shutdown"):
        async def scenario():
            rt = runtime()
            started, stopped, finished, closed = (anyio.Event() for _ in range(4))
            release_worker = threading.Event()
            outcomes, calls = {}, []
            created = install_control(monkeypatch, on_stop=lambda control: stopped.set())

            def controlled_calculate(service, normalized):
                calls.append(service.control)
                if len(calls) == 1:
                    anyio.from_thread.run_sync(started.set)
                    assert release_worker.wait(1), "Test did not release the controlled shutdown worker"
                    service.control.check_active()
                return literal_result()

            monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate", controlled_calculate)

            async def active_call():
                try:
                    await execution.execute_library(rt, request(), arrived_at=monotonic())
                except BaseException as error:
                    outcomes["active"] = error
                finally:
                    finished.set()

            async def close_runtime():
                await rt.aclose()
                closed.set()

            second = waiter = None
            try:
                with anyio.fail_after(2):
                    async with anyio.create_task_group() as group:
                        group.start_soon(active_call)
                        await started.wait()
                        second_control = FakeControl(config=rt.config)
                        second = await rt.admission.acquire(second_control)
                        waiter_control = FakeControl(config=rt.config)
                        waiter = asyncio.create_task(rt.admission.acquire(waiter_control))
                        await anyio.lowlevel.checkpoint()
                        assert len(rt.admission.waiters) == 1
                        group.start_soon(close_runtime)
                        await stopped.wait()
                        assert rt.admission.closing and not closed.is_set()
                        assert len(rt.admission.active_leases) == 2
                        with pytest.raises(CalculationCancelledError):
                            await waiter
                        assert waiter_control.stop_reason == second_control.stop_reason == "cancel"
                        with pytest.raises(CapacityBusyError) as caught:
                            await execution.execute_library(rt, request(), arrived_at=monotonic())
                        assert caught.value.reason == "closing" and len(calls) == 1
                        rt.admission.release(second)
                        second = None
                        release_worker.set()
                        await finished.wait()
                        await closed.wait()
                assert isinstance(outcomes["active"], CalculationCancelledError)
                assert not rt.admission.active_leases and not rt.admission.waiters
                assert rt.admission.idle_event.is_set()
                await rt.aclose()
                normal = runtime()
                try:
                    assert await execution.execute_library(normal, request(), arrived_at=monotonic()) == literal_result()
                    assert created[-1].stop_reason is None
                finally:
                    await normal.aclose()
            finally:
                release_worker.set()
                if waiter is not None and not waiter.done():
                    waiter.cancel()
                if second is not None and not second.released:
                    rt.admission.release(second)
                await rt.aclose()

        anyio.run(scenario)
