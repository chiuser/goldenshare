"""LLD §04.2/11/12/13: real in-memory SQL plus bounded error substitutes.

No network, server, lake data, installation or durable database is used.
The only longer SQL is one 10-million-row aggregate interrupted once; all
other SQL is a few literal rows. Arrow is the approved project dependency.
"""

from contextlib import contextmanager
from dataclasses import replace
import threading
from time import monotonic

import duckdb
import pyarrow as pa
import pytest

from src.foundation.technical_indicators.calculation.calculation import SqlStep
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationExecutionError, ResourceLimitError,
)
from src.foundation.technical_indicators.execution_control import ExecutionControl
from src.foundation.technical_indicators.executor import DuckDBExecutor
from src.foundation.technical_indicators.service import TechnicalIndicatorService


def config(**changes):
    return replace(KernelConfig(
        "/not-accessed/data_lake", 2, 2, 2000, 1, 8192, 134217728,
        268435456, 1073741824, 8000, 2000, 10000, 1500000, 5000,
        10000, 5000000, 16, 33554432, 20, 200,
    ), **changes)


@contextmanager
def opened(**changes):
    settings = config(**changes)
    service = TechnicalIndicatorService(source=None, registry=None, config=settings)
    control = ExecutionControl(arrived_at=monotonic(), config=settings)
    connection, executor = service._open_execution(control)
    try:
        yield connection, executor, control
    finally:
        errors = service._close_execution(control, connection)
        assert not errors, errors


def test_private_connection_uses_all_confirmed_settings():
    with opened() as (_, executor, _):
        assert executor.scalar("SELECT current_setting('threads')") == 1
        assert executor.scalar("SELECT current_setting('temp_directory')") == ""
        assert executor.scalar("SELECT current_setting('max_temp_directory_size')") == "0 bytes"
        assert executor.scalar("SELECT current_setting('autoinstall_known_extensions')") is False
        assert executor.scalar("SELECT current_setting('autoload_known_extensions')") is False
        # DuckDB displays the byte limit rounded in human-readable units.
        assert executor.scalar("SELECT current_setting('memory_limit')") == "128.0 MiB"


def test_execute_uses_returned_count_and_bindings_without_an_extra_scan():
    with opened() as (_, executor, _):
        stats = executor.execute(SqlStep(
            "literal prices", "CREATE TABLE ti_prices AS SELECT * FROM (VALUES (?),(?)) b(close)",
            (5, 6), (), ("ti_prices",), 2,
        ))
        assert (stats.logical_input_rows, stats.output_rows, stats.failed) == (2, 2, False)
        assert executor.scalar("SELECT max(close) FROM ti_prices") == 6
        assert executor.sql_processed_rows == 2
        executor.drop_table("ti_prices")
        assert len(executor.statistics) == 1


def test_scalar_supports_one_struct_metadata_value_and_no_lazy_cursor():
    with opened() as (_, executor, _):
        value = executor.scalar("SELECT struct_pack(basis_date := DATE '2026-10-23', basis_value := 2.0::DOUBLE)")
        assert value["basis_date"].isoformat() == "2026-10-23"
        assert value["basis_value"] == 2.0
        assert executor.scalar("SELECT 1 WHERE false") is None
        with pytest.raises(CalculationExecutionError):
            executor.scalar("SELECT 1, 2")
    assert value["basis_value"] == 2.0


def test_arrow_is_materialized_once_and_registration_can_be_reused_after_release():
    with opened() as (_, executor, _):
        batch = pa.record_batch([pa.array([5.0, 6.0])], names=["close"])
        executor.register_arrow("ti_source_batch", batch)
        with pytest.raises(ValueError):
            executor.register_arrow("ti_source_batch", batch)
        executor.execute(SqlStep(
            "materialize", "CREATE TABLE ti_prices AS SELECT * FROM ti_source_batch",
            (), ("ti_source_batch",), ("ti_prices",), 2,
        ))
        executor.unregister_arrow("ti_source_batch")
        del batch
        assert executor.scalar("SELECT sum(close) FROM ti_prices") == 11.0
        executor.register_arrow("ti_source_batch", pa.record_batch([pa.array([7.0])], names=["close"]))
        executor.unregister_arrow("ti_source_batch")
        executor.drop_table("ti_prices")


def test_stopped_cleanup_only_accepts_owned_resources_and_is_idempotent():
    with opened() as (_, executor, control):
        executor.execute(SqlStep("literal", "CREATE TABLE ti_prices AS SELECT 1 AS close", (), (), ("ti_prices",), 1))
        with pytest.raises(RuntimeError):
            executor.cleanup_drop("ti_prices")
        with pytest.raises(ValueError):
            executor.drop_table("ti_never_registered")
        with pytest.raises(ValueError):
            executor.execute(SqlStep("bad name", "SELECT 1", (), (), ('ti_bad";SELECT 1',), 0))
        control.request_stop("cancel")
        with pytest.raises(CalculationCancelledError):
            executor.scalar("SELECT 1")
        assert control.stop_monitor() == ()
        executor.cleanup_drop("ti_prices")
        executor.cleanup_drop("ti_prices")
        with pytest.raises(ValueError):
            executor.cleanup_drop("ti_never_registered")
        with pytest.raises(ValueError):
            executor.cleanup_unregister("ti_never_registered")


def test_failed_creation_retains_cleanup_eligibility_and_original_database_cause():
    with opened() as (_, executor, control):
        with pytest.raises(CalculationExecutionError) as raised:
            executor.execute(SqlStep("broken", "CREATE TABLE ti_failed AS SELECT missing_name", (), (), ("ti_failed",), 0))
        assert isinstance(raised.value.__cause__, duckdb.BinderException)
        assert executor.statistics[-1].failed
        assert control.stop_monitor() == ()
        executor.cleanup_drop("ti_failed")


def test_cancel_after_successful_drop_does_not_create_a_false_cleanup_error():
    with opened() as (connection, executor, control):
        executor.execute(SqlStep("literal", "CREATE TABLE ti_prices AS SELECT 1", (), (), ("ti_prices",), 1))

        class StopAfterDrop:
            def execute(self, sql, *args):
                value = connection.execute(sql, *args)
                control.request_stop("cancel")
                return value

        executor.connection = StopAfterDrop()
        with pytest.raises(CalculationCancelledError):
            executor.drop_table("ti_prices")
        assert control.stop_monitor() == ()
        executor.cleanup_drop("ti_prices")


def test_executor_rejects_operations_in_a_different_working_thread():
    with opened() as (_, executor, _):
        errors = []

        def wrong_thread():
            try:
                executor.scalar("SELECT 1")
            except RuntimeError as exc:
                errors.append(exc)

        caller = threading.Thread(target=wrong_thread)
        caller.start()
        caller.join(timeout=1)
        assert not caller.is_alive() and len(errors) == 1
        assert executor.scalar("SELECT 2") == 2


def test_actual_duckdb_sql_is_interrupted_then_an_independent_request_succeeds():
    entered = threading.Event()
    stop_requested = threading.Event()
    observed = {}
    with opened(control_poll_ms=1) as (connection, executor, control):
        class MarkSqlEntry:
            def execute(self, sql, *args):
                entered.set()
                return connection.execute(sql, *args)

        executor.connection = MarkSqlEntry()

        def cancel():
            if entered.wait(1):
                observed["stop"] = monotonic()
                control.request_stop("cancel")
                stop_requested.set()

        caller = threading.Thread(target=cancel)
        caller.start()
        try:
            with pytest.raises(CalculationCancelledError) as raised:
                executor.execute(SqlStep("bounded interruption", "SELECT sum(sin(i)) FROM range(10000000) b(i)", (), (), (), 10000000))
            observed["returned"] = monotonic()
            assert isinstance(raised.value.__context__, duckdb.InterruptException)
            assert stop_requested.is_set()
            assert (observed["returned"] - observed["stop"]) * 1000 <= 1500
        finally:
            caller.join(timeout=1)
            assert not caller.is_alive()
    assert (monotonic() - observed["stop"]) * 1000 <= 2000
    with opened() as (_, executor, _):
        assert executor.scalar("SELECT 7") == 7


def test_database_memory_error_maps_to_resource_limit_without_a_fallback():
    # This substitutes the driver error only; low-memory real sorting is §17 acceptance.
    control = ExecutionControl(arrived_at=monotonic(), config=config())

    class OutOfMemory:
        def execute(self, *args):
            raise duckdb.OutOfMemoryException("synthetic allocation failure")

    executor = DuckDBExecutor(OutOfMemory(), control)
    with pytest.raises(ResourceLimitError) as raised:
        executor.execute(SqlStep("memory failure", "SELECT 1", (), (), (), 1))
    assert isinstance(raised.value.__cause__, duckdb.OutOfMemoryException)
    assert len(executor.statistics) == 1 and executor.statistics[0].failed
    assert control.stop_monitor() == ()


def test_cancel_one_active_request_does_not_stop_another_private_connection():
    with opened() as (_, first, first_control), opened() as (_, second, second_control):
        first_control.request_stop("cancel")
        with pytest.raises(CalculationCancelledError):
            first.scalar("SELECT 1")
        assert second.scalar("SELECT 9") == 9
        assert second_control.stop_reason is None
