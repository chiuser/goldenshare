"""D4's seven admission classes; no source reads, SQL or real Control.

The independent expected ordering comes from LLD12.2/12.4/12.4a. These
helpers are also used by the two lifecycle modules; each scope releases its
FakeControl references without reading or writing acceptance history.
"""

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from time import monotonic

import anyio
import pytest

from src.app.runtime.technical_indicators.admission import AdmissionController
from src.app.runtime.technical_indicators.composition import TechnicalIndicatorRuntime
from src.foundation.config.settings import Settings
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.indicators import create_builtin_registry
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationDeadlineError, CapacityBusyError,
    RequestInvalidError, WaitExpiredError,
)


def make_config(**overrides):
    base = KernelConfig.from_settings(Settings(
        _env_file=None, GOLDENSHARE_LAKE_ROOT="/private/tmp/d4-no-source-access",
        TECHNICAL_INDICATOR_MAX_CONCURRENT_REQUESTS=2,
        TECHNICAL_INDICATOR_MAX_WAITING_REQUESTS=2,
        TECHNICAL_INDICATOR_MAX_WAIT_MS=2000,
        TECHNICAL_INDICATOR_TOTAL_TARGET_MS=8000,
        TECHNICAL_INDICATOR_CLEANUP_RESERVE_MS=2000,
    ))
    return replace(base, **overrides)


class FakeControl:
    """Only the stop/clock boundary; never starts a monitor or connection."""

    instances = []

    def __init__(self, *, config, arrived_at=None, clock=monotonic):
        self.config, self.clock = config, clock
        self.arrived_at = self.clock() if arrived_at is None else arrived_at
        self.work_until = self.arrived_at + (config.total_target_ms-config.cleanup_reserve_ms)/1000
        self.target_finish = self.arrived_at + config.total_target_ms/1000
        self.stop_reason = self.stop_requested_at = self.resources_released_at = None
        self.cleanup_ready = False
        self.monitor = None
        self.interrupt_count = 0
        type(self).instances.append(self)

    def request_stop(self, reason):
        assert reason in ("cancel", "deadline")
        if self.stop_reason is None:
            self.stop_reason, self.stop_requested_at = reason, self.clock()

    def check_active(self):
        if self.stop_reason is None and self.clock() >= self.work_until:
            self.request_stop("deadline")
        if self.stop_reason == "cancel":
            raise CalculationCancelledError("Controlled D4 cancellation")
        if self.stop_reason == "deadline":
            raise CalculationDeadlineError("Controlled D4 working deadline")

    def start_monitor(self, callback):
        pass

    def stop_monitor(self):
        self.cleanup_ready = True
        return ()

    def _assert_working_thread(self):
        pass

    def _note_sql_returned(self):
        pass


@contextmanager
def light_case(name):
    """Keep each ordinary regression independent of acceptance history."""
    first = len(FakeControl.instances)
    try:
        yield
    finally:
        del FakeControl.instances[first:]


def test_normal_grant_and_prewait_validation(monkeypatch):
    with light_case("test_normal_grant_and_prewait_validation"):
        from src.app.runtime.technical_indicators import execution

        async def scenario():
            config = make_config()
            admission = AdmissionController(config)
            first = await admission.acquire(FakeControl(config=config))
            second = await admission.acquire(FakeControl(config=config))
            runtime = TechnicalIndicatorRuntime(config, create_builtin_registry(), object(), admission)
            monkeypatch.setattr(execution, "ExecutionControl", FakeControl)
            bad = CalculationRequest("stock", "600000.SH", "day", (
                CalculationInstance("ma", "ma", {"period":0}),
            ))
            with pytest.raises(RequestInvalidError):
                await execution.execute_library(runtime, bad, arrived_at=monotonic())
            assert not admission.waiters and len(admission.active_leases) == 2
            good = replace(bad, calculations=(CalculationInstance("ma", "ma", {"period":20}),))
            assert execution._validate_request_before_wait(runtime, good) == good
            queued = asyncio.create_task(admission.acquire(FakeControl(config=config)))
            await asyncio.sleep(0)
            assert len(admission.waiters) == 1
            admission.release(first)
            third = await queued
            admission.release(second)
            admission.release(third)
            with pytest.raises(RuntimeError):
                admission.release(third)
            foreign = AdmissionController(config)
            with pytest.raises(RuntimeError):
                foreign.release(third)
            assert not admission.active_leases and admission.idle_event.is_set()
            await runtime.aclose()

        anyio.run(scenario)


def test_fifo_waiting():
    with light_case("test_fifo_waiting"):
        async def scenario():
            config = make_config()
            admission = AdmissionController(config)
            first = await admission.acquire(FakeControl(config=config))
            second = await admission.acquire(FakeControl(config=config))
            third = asyncio.create_task(admission.acquire(FakeControl(config=config)))
            await asyncio.sleep(0)
            fourth = asyncio.create_task(admission.acquire(FakeControl(config=config)))
            await asyncio.sleep(0)
            assert len(admission.waiters) == 2
            admission.release(first)
            third_lease = await third
            assert not fourth.done()
            admission.release(second)
            fourth_lease = await fourth
            assert third_lease.control is FakeControl.instances[-2]
            assert fourth_lease.control is FakeControl.instances[-1]
            admission.release(third_lease)
            admission.release(fourth_lease)
            await admission.shutdown()

        anyio.run(scenario)


def test_waiting_full():
    with light_case("test_waiting_full"):
        async def scenario():
            config = make_config()
            admission = AdmissionController(config)
            first = await admission.acquire(FakeControl(config=config))
            second = await admission.acquire(FakeControl(config=config))
            third = asyncio.create_task(admission.acquire(FakeControl(config=config)))
            await asyncio.sleep(0)
            fourth = asyncio.create_task(admission.acquire(FakeControl(config=config)))
            await asyncio.sleep(0)
            with pytest.raises(CapacityBusyError):
                await admission.acquire(FakeControl(config=config))
            assert len(admission.waiters) == 2 and len(admission.active_leases) == 2
            admission.release(first)
            admission.release(second)
            admission.release(await third)
            admission.release(await fourth)
            await admission.shutdown()

        anyio.run(scenario)


def test_waiting_expired():
    with light_case("test_waiting_expired"):
        async def scenario():
            config = make_config(max_concurrent_requests=1, max_wait_ms=1)
            admission = AdmissionController(config)
            lease = await admission.acquire(FakeControl(config=config))
            with pytest.raises(WaitExpiredError):
                await admission.acquire(FakeControl(config=config))
            assert not admission.waiters and len(admission.active_leases) == 1
            admission.release(lease)
            normal = await admission.acquire(FakeControl(config=config))
            admission.release(normal)
            await admission.shutdown()

        anyio.run(scenario)


def test_waiting_cancelled():
    with light_case("test_waiting_cancelled"):
        async def scenario():
            config = make_config(max_concurrent_requests=1)
            admission = AdmissionController(config)
            lease = await admission.acquire(FakeControl(config=config))
            cancelled = asyncio.create_task(admission.acquire(FakeControl(config=config)))
            await asyncio.sleep(0)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            assert not admission.waiters
            normal = asyncio.create_task(admission.acquire(FakeControl(config=config)))
            await asyncio.sleep(0)
            admission.release(lease)
            admission.release(await normal)
            await admission.shutdown()

        anyio.run(scenario)


def test_cancel_after_grant_before_handoff():
    with light_case("test_cancel_after_grant_before_handoff"):
        async def scenario():
            config = make_config(max_concurrent_requests=1)
            admission = AdmissionController(config)
            first = await admission.acquire(FakeControl(config=config))
            queued = asyncio.create_task(admission.acquire(FakeControl(config=config)))
            await asyncio.sleep(0)
            waiter = admission.waiters[0]
            admission.release(first)
            assert waiter.assigned_lease is not None and not waiter.handed_over
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
            assert waiter.assigned_lease.released and not admission.active_leases
            normal = await admission.acquire(FakeControl(config=config))
            admission.release(normal)
            await admission.shutdown()

        anyio.run(scenario)


def test_grant_after_work_deadline():
    with light_case("test_grant_after_work_deadline"):
        async def scenario():
            config = make_config(max_concurrent_requests=1)
            admission = AdmissionController(config)
            first = await admission.acquire(FakeControl(config=config))
            now = [monotonic()]
            control = FakeControl(config=config, clock=lambda:now[0])
            waiting = asyncio.create_task(admission.acquire(control))
            await asyncio.sleep(0)
            now[0] = control.work_until
            admission.release(first)
            with pytest.raises(CalculationDeadlineError):
                await waiting
            assert not admission.active_leases and not admission.waiters
            normal = await admission.acquire(FakeControl(config=config))
            admission.release(normal)
            await admission.shutdown()

        anyio.run(scenario)
