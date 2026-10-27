"""D4 request capacity and FIFO waiting, confined to one asyncio event loop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import anyio

from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationDeadlineError, CapacityBusyError,
    WaitExpiredError,
)
from src.foundation.technical_indicators.execution_control import ExecutionControl


@dataclass(slots=True, eq=False)
class AdmissionLease:
    lease_id: int
    control: ExecutionControl
    released: bool = False


@dataclass(slots=True, eq=False)
class _Waiter:
    future: asyncio.Future[AdmissionLease]
    control: ExecutionControl
    wait_until: float
    assigned_lease: AdmissionLease | None = None
    handed_over: bool = False


class AdmissionController:
    """No connection or worker exists here; release never suspends."""

    def __init__(self, config: KernelConfig):
        self.config = config
        self._loop = asyncio.get_running_loop()
        self.closing = False
        self.active_leases: dict[int, AdmissionLease] = {}
        self.waiters: list[_Waiter] = []
        self.idle_event = anyio.Event()
        self.idle_event.set()

    def _assert_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("Admission must use the event loop that created it")

    def _grant(self, control: ExecutionControl) -> AdmissionLease:
        identity = id(control)
        if identity in self.active_leases:
            raise RuntimeError("The same request already holds a calculation slot")
        if not self.active_leases:
            self.idle_event = anyio.Event()
        lease = AdmissionLease(identity, control)
        self.active_leases[identity] = lease
        return lease

    @staticmethod
    def _raise_expired(waiter: _Waiter) -> None:
        waiter.control.check_active()
        if waiter.control.clock() >= waiter.control.work_until:
            raise CalculationDeadlineError("The request working deadline was reached while waiting")
        raise WaitExpiredError("The calculation slot waiting deadline was reached")

    async def acquire(self, control: ExecutionControl) -> AdmissionLease:
        self._assert_loop()
        if self.closing:
            error = CapacityBusyError("Technical indicator runtime is closing")
            error.reason = "closing"
            raise error
        control.check_active()
        if not self.waiters and len(self.active_leases) < self.config.max_concurrent_requests:
            return self._grant(control)
        if len(self.waiters) >= self.config.max_waiting_requests:
            raise CapacityBusyError("Technical indicator waiting capacity is full")

        waiter = _Waiter(
            self._loop.create_future(), control,
            min(control.clock() + self.config.max_wait_ms / 1000, control.work_until),
        )
        self.waiters.append(waiter)
        try:
            remaining = waiter.wait_until - control.clock()
            if remaining <= 0:
                self._raise_expired(waiter)
            # Shield only the Future from cancellation: acquire itself remains
            # cancellable and owns any assigned-but-not-handed-over lease.
            with anyio.CancelScope(deadline=anyio.current_time() + remaining) as scope:
                lease = await asyncio.shield(waiter.future)
            if scope.cancel_called:
                self._raise_expired(waiter)
            control.check_active()
            waiter.handed_over = True
            return lease
        except BaseException:
            if waiter in self.waiters:
                self.waiters.remove(waiter)
            if waiter.assigned_lease is not None and not waiter.handed_over:
                self.release(waiter.assigned_lease)
            raise
        finally:
            if not waiter.future.done():
                waiter.future.cancel()
            elif not waiter.future.cancelled():
                # A simultaneous cancellation can win after shutdown/expiry
                # completed the Future. Consume its diagnostic exception even
                # when this acquire exits with the caller's cancellation.
                waiter.future.exception()

    def release(self, lease: AdmissionLease) -> None:
        self._assert_loop()
        if (not isinstance(lease, AdmissionLease) or lease.released
                or self.active_leases.get(lease.lease_id) is not lease):
            raise RuntimeError("The calculation slot is unknown, foreign or already released")
        del self.active_leases[lease.lease_id]
        lease.released = True
        if not self.closing:
            while self.waiters and len(self.active_leases) < self.config.max_concurrent_requests:
                waiter = self.waiters.pop(0)
                if waiter.future.done():
                    continue
                try:
                    waiter.control.check_active()
                    if waiter.control.clock() >= waiter.wait_until:
                        self._raise_expired(waiter)
                except (CalculationCancelledError, CalculationDeadlineError, WaitExpiredError) as error:
                    waiter.future.set_exception(error)
                    continue
                waiter.assigned_lease = self._grant(waiter.control)
                waiter.future.set_result(waiter.assigned_lease)
        if not self.active_leases:
            self.idle_event.set()

    async def shutdown(self) -> None:
        self._assert_loop()
        with anyio.CancelScope(shield=True):
            self.closing = True
            idle_event = self.idle_event
            pending, self.waiters = self.waiters, []
            for waiter in pending:
                waiter.control.request_stop("cancel")
                if not waiter.future.done():
                    waiter.future.set_exception(CalculationCancelledError("Runtime closed while waiting"))
            for lease in tuple(self.active_leases.values()):
                lease.control.request_stop("cancel")
            await idle_event.wait()
