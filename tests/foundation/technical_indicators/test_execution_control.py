"""LLD §13/18: bounded ordering tests, no services, source reads or installs.

Event-controlled callbacks substitute only the database interrupt operation;
the actual DuckDB interrupt check is in test_executor.py. All helper threads
are joined in finally; configuration is a literal copy of confirmed §16 values.
"""

from dataclasses import replace
import threading
from time import monotonic

import pytest

from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationDeadlineError, ResourceCleanupError,
)
from src.foundation.technical_indicators.execution_control import ExecutionControl


def config(**changes):
    original = KernelConfig(
        goldenshare_lake_root="/not-accessed/data_lake",
        max_concurrent_requests=2, max_waiting_requests=2, max_wait_ms=2000,
        sql_threads=1, batch_rows=8192, query_memory_bytes=134217728,
        request_memory_bytes=268435456, deployment_reserve_bytes=1073741824,
        total_target_ms=8000, cleanup_reserve_ms=2000, frontend_expire_ms=10000,
        max_input_rows=1500000, max_source_files=5000, max_output_rows=10000,
        max_output_bytes=5000000, max_indicator_instances=16,
        max_projected_row_group_bytes=33554432, control_poll_ms=20,
        monitor_join_target_ms=200,
    )
    return replace(original, **changes)


def test_absolute_deadline_is_not_reset_and_has_no_thread_before_execution():
    now = [10.0]
    control = ExecutionControl(arrived_at=10.0, config=config(), clock=lambda: now[0])
    assert control.work_until == 16.0
    assert control.target_finish == 18.0
    assert control.monitor is None
    now[0] = 15.9
    control.check_active()
    now[0] = 16.0
    with pytest.raises(CalculationDeadlineError):
        control.check_active()
    now[0] = 17.0
    control.request_stop("cancel")
    assert control.stop_reason == "deadline"
    assert control.stop_requested_at == 16.0
    assert control.stop_monitor() == ()


def test_first_cancel_is_preserved_and_unstarted_cleanup_is_idempotent():
    control = ExecutionControl(arrived_at=monotonic(), config=config())
    with pytest.raises(ValueError):
        control.request_stop("not-a-reason")
    control.request_stop("cancel")
    first = control.stop_requested_at
    control.request_stop("deadline")
    with pytest.raises(CalculationCancelledError):
        control.check_active()
    assert control.stop_reason == "cancel"
    assert control.stop_requested_at == first
    assert control.stop_monitor() == control.stop_monitor() == ()
    assert control.cleanup_ready


def test_normal_end_joins_and_later_stop_cannot_call_an_old_connection():
    called = threading.Event()
    control = ExecutionControl(arrived_at=monotonic(), config=config())
    control.start_monitor(called.set)
    monitor = control.monitor
    assert control.stop_monitor() == ()
    assert monitor is not None and not monitor.is_alive()
    assert control.monitor_exited and control.cleanup_ready
    assert control.interrupt_callback is None and control.monitor is None
    assert control.stop_monitor_elapsed_ms >= control.monitor_join_elapsed_ms >= 0
    control.request_stop("cancel")
    assert not called.is_set()
    with pytest.raises(RuntimeError):
        control.start_monitor(called.set)


def test_deadline_wakes_the_single_monitor_without_a_timer_per_operation():
    now = [0.0]
    called = threading.Event()
    control = ExecutionControl(arrived_at=0.0, config=config(), clock=lambda: now[0])
    control.start_monitor(called.set)
    try:
        with control.condition:
            now[0] = 6.0
            control.condition.notify_all()
        assert called.wait(1)
        assert control.stop_reason == "deadline"
    finally:
        assert control.stop_monitor() == ()


def test_early_interrupt_is_retried_to_cover_a_later_sql_start():
    second_call = threading.Event()
    calls = []

    def interrupt():
        calls.append(1)
        if len(calls) == 2:
            second_call.set()

    control = ExecutionControl(arrived_at=monotonic(), config=config(control_poll_ms=1))
    control.start_monitor(interrupt)
    try:
        control.request_stop("cancel")
        assert second_call.wait(1)
    finally:
        assert control.stop_monitor() == ()
    assert control.interrupt_count >= 2


def test_interrupt_error_is_remembered_but_does_not_end_the_retry_loop():
    second_call = threading.Event()
    calls = []

    def interrupt():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("synthetic interrupt failure")
        second_call.set()

    control = ExecutionControl(arrived_at=monotonic(), config=config(control_poll_ms=1))
    control.start_monitor(interrupt)
    try:
        control.request_stop("cancel")
        assert second_call.wait(1)
    finally:
        errors = control.stop_monitor()
    assert control.interrupt_error == ("OSError", "synthetic interrupt failure")
    assert len(errors) == 1 and isinstance(errors[0], ResourceCleanupError)
    assert control.cleanup_ready and control.interrupt_callback is None


def test_start_failure_unbinds_and_does_not_join_an_unstarted_thread(monkeypatch):
    def fail_start(self):
        raise RuntimeError("synthetic thread start failure")

    def forbidden_join(self, *args, **kwargs):
        raise AssertionError("Unstarted thread must not be joined")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    monkeypatch.setattr(threading.Thread, "join", forbidden_join)
    control = ExecutionControl(arrived_at=monotonic(), config=config())
    with pytest.raises(RuntimeError, match="synthetic"):
        control.start_monitor(lambda: None)
    assert control.interrupt_callback is None and not control.monitor_started
    assert control.stop_monitor() == ()


def test_join_target_failure_waits_for_real_exit_and_records_total_elapsed():
    # This substitutes join scheduling only, not the actual-SQL cancellation test.
    now = [0.0]
    control = ExecutionControl(arrived_at=0.0, config=config(), clock=lambda: now[0])

    class DelayedJoin:
        alive = True
        calls = []

        def join(self, timeout=None):
            self.calls.append(timeout)
            if timeout is not None:
                now[0] += 0.25
            else:
                now[0] += 0.1
                self.alive = False
                control.monitor_exited = True

        def is_alive(self):
            return self.alive

    monitor = DelayedJoin()
    control.monitor = monitor
    control.monitor_started = True
    errors = control.stop_monitor()
    assert monitor.calls == [0.2, None]
    assert not monitor.alive and control.cleanup_ready
    assert len(errors) == 1 and isinstance(errors[0], ResourceCleanupError)
    assert control.monitor_join_elapsed_ms == pytest.approx(350)
    assert control.stop_monitor_elapsed_ms == pytest.approx(350)


def test_monitor_cannot_be_joined_or_cleaned_by_another_working_thread():
    control = ExecutionControl(arrived_at=monotonic(), config=config())
    errors = []
    control.start_monitor(lambda: None)

    def wrong_owner():
        try:
            control.stop_monitor()
        except RuntimeError as error:
            errors.append(error)

    caller = threading.Thread(target=wrong_owner)
    caller.start()
    try:
        caller.join(timeout=1)
        assert not caller.is_alive() and len(errors) == 1
        assert not control.monitor_stop
    finally:
        assert control.stop_monitor() == ()


def test_stop_monitor_total_includes_waiting_for_the_interrupt_lock():
    # A virtual clock supplies a precise expectation, not a real latency claim.
    now = [0.0]
    locked = threading.Event()
    entered_stop = threading.Event()
    owner = threading.get_ident()

    def clock():
        value = now[0]
        if threading.get_ident() == owner:
            entered_stop.set()
        return value

    control = ExecutionControl(arrived_at=0.0, config=config(), clock=clock)

    def hold_lock():
        with control.condition:
            locked.set()
            assert entered_stop.wait(1)
            now[0] = 0.5

    holder = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert locked.wait(1)
        assert control.stop_monitor() == ()
    finally:
        holder.join(timeout=1)
        assert not holder.is_alive()
    assert control.monitor_lock_wait_ms == 500
    assert control.monitor_join_elapsed_ms == 0
    assert control.stop_monitor_elapsed_ms == 500
