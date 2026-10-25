"""LLD §04.2/11/13: connection ownership and partial initialization failures.

The original driver/resource substitutes verify call order and error precedence;
test_executor.py covers the actual in-memory DuckDB boundary.  The separately
selected D2 pending-batch cancellation test uses the real source with shared
temporary producer-contract files, one real control and the real private
in-memory DuckDB connection.  No database process, network, formal-Lake source,
installation or running-SQL interruption claim is involved in that new test.
"""

from time import monotonic

import pytest

from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import CalculationCancelledError, ResourceCleanupError
from src.foundation.technical_indicators.execution_control import ExecutionControl
from src.foundation.technical_indicators import service as implementation

from test_source_contracts import (
    batch_assembly_files, AssemblyReadTrace, assembly_metrics, assembly_source, assembly_config,
    track_assembly_reader, track_compact_copies,
)


def config():
    return KernelConfig(
        "/not-accessed/data_lake", 2, 2, 2000, 1, 8192, 134217728,
        268435456, 1073741824, 8000, 2000, 10000, 1500000, 5000,
        10000, 5000000, 16, 33554432, 20, 200,
    )


class Connection:
    """Driver substitute: no database, and fail loudly on post-close interrupts."""
    def __init__(self, events, *, fail_close=False):
        self.events = events
        self.closed = False
        self.fail_close = fail_close

    def interrupt(self):
        assert not self.closed
        self.events.append("interrupt")

    def close(self):
        assert not self.closed
        self.events.append("connection.close")
        self.closed = True
        if self.fail_close:
            raise OSError("synthetic close failure")


def prepared(monkeypatch, *, fail_close=False):
    events = []
    connection = Connection(events, fail_close=fail_close)

    def connect(settings):
        events.append("connect")
        return connection

    monkeypatch.setattr(implementation, "connect_private_memory_instance", connect)
    settings = config()
    service = implementation.TechnicalIndicatorService(source=None, registry=None, config=settings)
    control = ExecutionControl(arrived_at=monotonic(), config=settings)
    return service, control, connection, events


def test_cancel_before_open_does_not_create_any_connection(monkeypatch):
    service, control, connection, events = prepared(monkeypatch)
    control.request_stop("cancel")
    with pytest.raises(CalculationCancelledError):
        service._open_execution(control)
    assert events == [] and not connection.closed and control.cleanup_ready


def test_connection_creation_failure_is_not_retried_with_default_settings(monkeypatch):
    calls = []

    def fail(settings):
        calls.append(settings)
        raise OSError("synthetic connection failure")

    monkeypatch.setattr(implementation, "connect_private_memory_instance", fail)
    settings = config()
    service = implementation.TechnicalIndicatorService(source=None, registry=None, config=settings)
    control = ExecutionControl(arrived_at=monotonic(), config=settings)
    with pytest.raises(OSError, match="synthetic connection"):
        service._open_execution(control)
    assert calls == [settings] and control.cleanup_ready


def test_monitor_start_failure_still_closes_the_connection_in_the_same_service(monkeypatch):
    service, control, connection, events = prepared(monkeypatch)

    def fail(callback):
        raise RuntimeError("synthetic monitor failure")

    monkeypatch.setattr(control, "start_monitor", fail)
    with pytest.raises(RuntimeError, match="synthetic monitor"):
        service._open_execution(control)
    assert events == ["connect", "connection.close"] and connection.closed


def test_executor_initialization_failure_closes_the_partially_opened_connection(monkeypatch):
    service, control, connection, events = prepared(monkeypatch)

    def fail(*args):
        raise RuntimeError("synthetic executor failure")

    monkeypatch.setattr(implementation, "DuckDBExecutor", fail)
    with pytest.raises(RuntimeError, match="synthetic executor"):
        service._open_execution(control)
    assert events == ["connect", "connection.close"] and connection.closed


def test_cleanup_detaches_monitor_before_owned_resources_and_closes_last(monkeypatch):
    service, control, connection, events = prepared(monkeypatch)
    service._open_execution(control)

    class Resource:
        def __init__(self, name):
            self.name = name

        def close(self):
            assert control.cleanup_ready and control.interrupt_callback is None
            events.append(self.name)

        discard = close

    errors = service._close_execution(
        control, connection, engine=Resource("engine"), inputs=Resource("inputs"), output=Resource("output"),
    )
    assert not errors
    assert events == ["connect", "engine", "inputs", "output", "connection.close"]
    assert control.resources_released_at is not None
    control.request_stop("cancel")  # A late stop cannot target the closed connection.


def test_cleanup_error_does_not_skip_other_resources_or_override_the_original_error(monkeypatch):
    service, control, connection, events = prepared(monkeypatch)
    service._open_execution(control)

    class FailingResource:
        def close(self):
            events.append("engine")
            raise OSError("synthetic engine cleanup")

    class RemainingResource:
        def close(self):
            events.append("inputs")

        def discard(self):
            events.append("output")

    errors = service._close_execution(
        control, connection, engine=FailingResource(), inputs=RemainingResource(), output=RemainingResource(),
    )
    assert events == ["connect", "engine", "inputs", "output", "connection.close"]
    assert len(errors) == 1 and connection.closed
    assert control.resources_released_at is None
    primary = ArithmeticError("original calculation failure")
    with pytest.raises(ArithmeticError) as raised:
        implementation.raise_primary_or_cleanup_error_if_any(primary, errors)
    assert raised.value is primary and "synthetic engine cleanup" in raised.value.__notes__[0]
    with pytest.raises(ResourceCleanupError):
        implementation.raise_primary_or_cleanup_error_if_any(None, errors)


def test_close_failure_is_returned_not_reported_as_success(monkeypatch):
    service, control, connection, events = prepared(monkeypatch, fail_close=True)
    service._open_execution(control)
    errors = service._close_execution(control, connection)
    assert len(errors) == 1 and isinstance(errors[0], OSError)
    assert events == ["connect", "connection.close"] and control.resources_released_at is None


def test_cleanup_target_is_measured_from_first_stop_not_restarted_at_close(monkeypatch):
    service, _, connection, events = prepared(monkeypatch)
    now = [0.0]
    control = ExecutionControl(arrived_at=0.0, config=config(), clock=lambda: now[0])
    service._open_execution(control)
    control.request_stop("cancel")
    now[0] = 2.1
    errors = service._close_execution(control, connection)
    assert len(errors) == 1 and isinstance(errors[0], ResourceCleanupError)
    assert connection.closed and events[-1] == "connection.close"
    assert control.resources_released_at == 2.1


def test_pending_batch_cancel_releases_stream(batch_assembly_files, monkeypatch, record_property):
    """The one real-control pending-cancellation request in LLD 18.1.

    Exactly the first 10000 target rows are physically read.  The final one-row
    file must remain unopened; delivered source positions are 1..8192 and the
    compact remainder is 1808 rows until cancellation.
    """
    started, trace = monotonic(), AssemblyReadTrace()
    cfg = assembly_config(batch_assembly_files)
    control = ExecutionControl(arrived_at=monotonic(), config=cfg)
    cfg, request, requirement, context, _, source, description, _ = assembly_source(
        batch_assembly_files,control=control,open_stream=False)
    service = implementation.TechnicalIndicatorService(source=source,registry=None,config=cfg)
    connection = stream = None
    delivered, cleanup = [], ()
    try:
        connection, executor = service._open_execution(control)
        stream = source.open(executor,description,requirement,read_context=context)
        track_assembly_reader(stream,trace,monkeypatch)
        track_compact_copies(trace,monkeypatch)
        batch = stream.next_batch(8192)
        assert batch.selected_rows==8192
        assert (batch.source_first_position,batch.source_last_position)==(1,8192)
        delivered.append(batch.selected_rows)
        trace.observe_owned(stream)
        pending = stream._pending_batch
        assert pending is not None and pending.num_rows==1808
        assert context.source_rows==trace.actual_read_rows==10000
        assert trace.reader_opens==[str(path) for path in batch_assembly_files.minute_paths[:3]]
        stream.release_current_batch()
        assert stream._pending_batch is pending
        del batch,pending
        control.request_stop("cancel")
        with pytest.raises(CalculationCancelledError):stream.next_batch(8192)
        assert trace.actual_read_rows==10000 and stream._delivered==8192
        assert stream._current_batch is stream._pending_batch is None
        assert stream._failed
    finally:
        cleanup=service._close_execution(control,connection,inputs=stream)
        assembly_metrics(record_property,"pending_cancel",trace,context,started,
            real_controls=1,delivered=delivered,cleanup=[str(item) for item in cleanup],
            expected={"actual_input":10000,"sizes":[8192],"pending_before_stop":1808,
                      "error":"CalculationCancelledError"},
            stop_requested_at=control.stop_requested_at,resources_released_at=control.resources_released_at,
            monitor_join_elapsed_ms=control.monitor_join_elapsed_ms,
            stop_to_cleanup_ms=None if control.stop_requested_at is None or control.resources_released_at is None
              else (control.resources_released_at-control.stop_requested_at)*1000)
        assert not cleanup
        assert stream is None or (stream._closed and stream._reader is None)
        assert control.interrupt_callback is None
        assert control.monitor is None or not control.monitor.is_alive()
        assert all(reader.closed for reader in trace.readers)
