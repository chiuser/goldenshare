"""Synchronous indicator service; one request owns one SQL connection."""

from __future__ import annotations

from typing import TYPE_CHECKING
from time import monotonic

from .configuration.settings import KernelConfig
from .errors import ResourceCleanupError, SourceContractError, SourceUnsupportedError
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

    @staticmethod
    def _describe_output_instances(plan):
        """Copy public result metadata without exposing the execution plan."""
        from .output.contracts import OutputFieldDescription, OutputInstanceDescription

        return tuple(
            OutputInstanceDescription(
                instance_id=identity,
                calculation_id=plan.nodes[index].definition.calculation_id,
                algorithm_version=plan.nodes[index].definition.algorithm_version,
                parameters=plan.nodes[index].parameters,
                fields=tuple(OutputFieldDescription(
                    name=field.name, sql_type=field.sql_type, nullable=field.nullable,
                    initialization_rule=field.initialization_rule,
                ) for field in plan.nodes[index].definition.output_fields),
            ) for identity, index in plan.instances
        )

    def calculate(self, request):
        """Compute the requested region and return a detached immutable result."""
        from .calculation.engine import CalculationEngine
        from .contracts import CalculationStatistics, normalize_request_and_validate_all_instances
        from .output.collector import OutputCollector
        from .output.encoding import measure_result_utf8
        from .sources.contracts import ReadRequirement
        from .sources.read_context import SourceReadContext
        from .sources.session import PriceInputSession

        control = self.control or ExecutionControl(arrived_at=monotonic(), config=self.config)
        normalized = normalize_request_and_validate_all_instances(request, self.config)
        plan = self.registry.expand_dependencies(normalized)
        instances = self._describe_output_instances(plan)
        read_context = SourceReadContext(self.config)
        connection = executor = inputs = engine = output = None
        result = primary_error = None
        try:
            control.check_active()
            connection, executor = self._open_execution(control)
            engine = CalculationEngine(executor, plan)
            engine.prepare()
            history = engine.resolve_history_requirement(self.config.max_input_rows)
            requirement = ReadRequirement(
                normalized, history, self.config.batch_rows,
                history_start=None, processing_end=normalized.end,
            )
            inputs = PriceInputSession(executor, self.source, requirement, read_context=read_context)
            inputs.prepare()
            output = OutputCollector(executor=executor, request=normalized, instances=instances)
            while True:
                control.check_active()
                batch = inputs.next_batch()
                if batch is None:
                    break
                engine.consume(batch)
                output.append_new_rows(engine.output_for(batch))
                inputs.retain_required_history()
                engine.release_batch_tables()
                inputs.finish_batch()
                control.check_active()
            engine.finish()
            statistics = CalculationStatistics(
                source_rows=read_context.source_rows,
                sql_processed_rows=executor.sql_processed_rows,
                source_files=read_context.source_files,
                source_file_bytes=read_context.source_file_bytes,
                locator_rows=read_context.locator_rows,
                price_conversion_batches=inputs.conversion_batches,
                elapsed_ms=(control.clock() - control.arrived_at) * 1000,
            )
            result = output.build_result(
                inputs.resolved_description(), statistics,
                read_start=inputs.read_start, read_end=inputs.read_end,
                expected_rows=inputs.resolved_description().selection.target_rows,
            )
            measure_result_utf8(result, control=control, max_bytes=self.config.max_output_bytes)
            control.check_active()
        except BaseException as exc:
            primary_error = exc
        finally:
            cleanup_errors = self._close_execution(
                control, connection, engine=engine, inputs=inputs, output=output,
            )
        raise_primary_or_cleanup_error_if_any(primary_error, cleanup_errors)
        control.check_active()
        return result

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
