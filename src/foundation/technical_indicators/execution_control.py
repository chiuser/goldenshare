"""One request's deadline and interrupt monitor (LLD §13).

Only the monitor calls interrupt. SQL, file operations and resource cleanup
remain in the calling working thread; an elapsed target never abandons them.
"""

from __future__ import annotations

from collections.abc import Callable
import threading
from time import monotonic

from .configuration.settings import KernelConfig
from .errors import (
    CalculationCancelledError,
    CalculationDeadlineError,
    ResourceCleanupError,
)


class ExecutionControl:
    def __init__(self, *, arrived_at: float, config: KernelConfig, clock=monotonic):
        self.config = config
        self.clock = clock
        self.arrived_at = arrived_at
        self.work_until = arrived_at + (config.total_target_ms - config.cleanup_reserve_ms) / 1000
        self.target_finish = arrived_at + config.total_target_ms / 1000
        self.condition = threading.Condition(threading.Lock())
        self.stop_reason: str | None = None
        self.stop_requested_at: float | None = None
        self.interrupt_callback: Callable[[], None] | None = None
        self.monitor: threading.Thread | None = None
        self.monitor_started = False
        self.monitor_stop = False
        self.monitor_exited = False
        self.interrupt_count = 0
        self.interrupt_error: tuple[str, str] | None = None
        self.sql_returned_at: float | None = None
        self.resources_released_at: float | None = None
        self.stop_monitor_elapsed_ms: float | None = None
        self.monitor_lock_wait_ms: float | None = None
        self.monitor_join_elapsed_ms: float | None = None
        self._start_attempted = False
        self._owner_thread: int | None = None

    def _assert_working_thread(self) -> None:
        if self._owner_thread is not None and self._owner_thread != threading.get_ident():
            raise RuntimeError("Execution cleanup must remain in its working thread")

    def _stop_locked(self, reason: str, now: float) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
            self.stop_requested_at = now
            self.condition.notify_all()

    def _set_deadline_if_due_locked(self) -> None:
        now = self.clock()
        if now >= self.work_until:
            self._stop_locked("deadline", now)

    def request_stop(self, reason: str) -> None:
        if reason not in ("cancel", "deadline"):
            raise ValueError("Stop reason must be cancel or deadline")
        with self.condition:
            self._stop_locked(reason, self.clock())

    def check_active(self) -> None:
        with self.condition:
            self._set_deadline_if_due_locked()
            reason = self.stop_reason
        if reason == "cancel":
            raise CalculationCancelledError("Technical indicator calculation was cancelled")
        if reason == "deadline":
            raise CalculationDeadlineError("Technical indicator working deadline was reached")

    def start_monitor(self, callback: Callable[[], None]) -> None:
        if not callable(callback):
            raise TypeError("Interrupt callback must be callable")
        with self.condition:
            if self._start_attempted or self.monitor_stop:
                raise RuntimeError("The request interrupt monitor can only start once")
            self._start_attempted = True
            self._owner_thread = threading.get_ident()
            self.interrupt_callback = callback
            try:
                self.monitor = threading.Thread(
                    target=self._monitor_loop,
                    name="technical-indicator-interrupt",
                    daemon=False,
                )
                self.monitor.start()
            except BaseException:
                self.interrupt_callback = None
                self.monitor = None
                raise
            self.monitor_started = True

    def _monitor_loop(self) -> None:
        try:
            with self.condition:
                while not self.monitor_stop:
                    self._set_deadline_if_due_locked()
                    if self.stop_reason is None:
                        self.condition.wait(timeout=max(0.0, self.work_until - self.clock()))
                        continue
                    if self.interrupt_callback is not None:
                        self.interrupt_count += 1
                        try:
                            self.interrupt_callback()
                        except Exception as exc:
                            if self.interrupt_error is None:
                                # Do not retain a traceback or a copy of the bound connection.
                                self.interrupt_error = (type(exc).__name__, str(exc))
                    self.condition.wait(timeout=self.config.control_poll_ms / 1000)
        finally:
            with self.condition:
                self.monitor_exited = True
                self.condition.notify_all()

    def _note_sql_returned(self) -> None:
        returned_at = self.clock()
        with self.condition:
            self.sql_returned_at = returned_at

    @property
    def cleanup_ready(self) -> bool:
        with self.condition:
            return self.monitor_stop and (not self.monitor_started or self.monitor_exited)

    def stop_monitor(self) -> tuple[BaseException, ...]:
        """Detach and really join; timing targets do not permit an early return."""
        self._assert_working_thread()
        started_at = self.clock()
        errors: list[BaseException] = []
        with self.condition:
            locked_at = self.clock()
            self.interrupt_callback = None
            self.monitor_stop = True
            self.condition.notify_all()
            monitor = self.monitor if self.monitor_started else None
        self.monitor_lock_wait_ms = (locked_at - started_at) * 1000
        joined_at = self.clock()
        if monitor is not None:
            try:
                monitor.join(timeout=self.config.monitor_join_target_ms / 1000)
            except BaseException as exc:
                errors.append(exc)
            if monitor.is_alive() or (self.clock() - joined_at) * 1000 > self.config.monitor_join_target_ms:
                errors.append(ResourceCleanupError("Interrupt monitor exceeded its join target"))
                # Even a signal interrupting join cannot make closing a live callback safe.
                remembered_join_error = bool(errors)
                while monitor.is_alive():
                    try:
                        monitor.join()
                    except BaseException as exc:
                        if not remembered_join_error:
                            errors.append(exc)
                            remembered_join_error = True
        finished_at = self.clock()
        self.monitor_join_elapsed_ms = (finished_at - joined_at) * 1000
        self.stop_monitor_elapsed_ms = (finished_at - started_at) * 1000
        with self.condition:
            if self.interrupt_error is not None:
                kind, message = self.interrupt_error
                errors.append(ResourceCleanupError(f"Interrupt callback failed: {kind}: {message}"))
            self.monitor = None
        return tuple(errors)
