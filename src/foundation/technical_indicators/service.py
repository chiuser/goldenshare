"""D2 request resource ownership; the complete calculate entry belongs to D3."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .configuration.settings import KernelConfig
from .errors import ResourceCleanupError
from .execution_control import ExecutionControl
from .executor import DuckDBExecutor

if TYPE_CHECKING:
    from .calculation.registry import CalculationRegistry
    from .sources.contracts import PriceSource


def connect_private_memory_instance(config: KernelConfig):
    """Create exactly this request's configured instance; never use defaults on error."""
    import duckdb

    return duckdb.connect(database=":memory:", config={
        "threads": str(config.sql_threads),
        "memory_limit": f"{config.query_memory_bytes}B",
        "temp_directory": "",
        "max_temp_directory_size": "0B",
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
    })


def raise_primary_or_cleanup_error_if_any(
    primary_error: BaseException | None, cleanup_errors: tuple[BaseException, ...],
) -> None:
    if primary_error is not None:
        for error in cleanup_errors:
            primary_error.add_note(f"Resource cleanup: {type(error).__name__}: {error}")
        raise primary_error
    if cleanup_errors:
        error = ResourceCleanupError("Technical indicator resource cleanup failed")
        for item in cleanup_errors:
            error.add_note(f"{type(item).__name__}: {item}")
        raise error from cleanup_errors[0]


class TechnicalIndicatorService:
    def __init__(
        self, *, source: PriceSource, registry: CalculationRegistry,
        config: KernelConfig, control: ExecutionControl | None = None,
    ):
        self.source = source
        self.registry = registry
        self.config = config
        self.control = control

    def _open_execution(self, control: ExecutionControl):
        connection = None
        try:
            control.check_active()
            connection = connect_private_memory_instance(self.config)
            executor = DuckDBExecutor(connection, control)
            control.start_monitor(connection.interrupt)
            control.check_active()
            return connection, executor
        except BaseException as error:
            cleanup_errors = self._close_execution(control, connection)
            raise_primary_or_cleanup_error_if_any(error, cleanup_errors)

    def _close_execution(
        self, control: ExecutionControl, connection, *, engine=None, inputs=None, output=None,
    ) -> tuple[BaseException, ...]:
        control._assert_working_thread()
        errors = list(control.stop_monitor())
        cleanup_failed = False
        for resource, method in ((engine, "close"), (inputs, "close"), (output, "discard")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except BaseException as exc:
                    errors.append(exc)
                    cleanup_failed = True
        if connection is not None:
            try:
                connection.close()
            except BaseException as exc:
                errors.append(exc)
                cleanup_failed = True
        finished_at = control.clock()
        if not cleanup_failed:
            control.resources_released_at = finished_at
        if control.stop_requested_at is not None:
            elapsed_ms = (finished_at - control.stop_requested_at) * 1000
            if elapsed_ms > self.config.cleanup_reserve_ms:
                errors.append(ResourceCleanupError("Stopping and cleanup exceeded the request's cleanup target"))
        return tuple(errors)
