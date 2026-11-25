"""Synchronous indicator service; one request owns one SQL connection."""

from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import TYPE_CHECKING
from time import monotonic

from .configuration.settings import KernelConfig
from .calculation.history import INITIALIZATION_ERROR_BUDGET, STOCK_WEEKLY_INITIALIZATION_ERROR_BUDGET
from .errors import OutputContractError, RequestInvalidError, ResourceCleanupError, ResourceLimitError, _clear_error_frames
from .execution_control import ExecutionControl
from .executor import DuckDBExecutor
from .request_parser import CalculationRequestParser, _build_read_requirement
from .sources.contracts import CalculationWithSource

if TYPE_CHECKING:
    from .calculation.registry import CalculationRegistry
    from .contracts import CalculationRequest
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
        self.parser = CalculationRequestParser(config, registry)
        self.config = config
        self.control = control

    @staticmethod
    def _describe_output_instances(plan):
        """Copy public result metadata without exposing the execution plan."""
        from .output.contracts import OutputFieldDescription, OutputInstanceDescription

        return tuple(
            OutputInstanceDescription(
                calculation_index=calculation_index,
                calculation_id=plan.nodes[index].definition.calculation_id,
                algorithm_version=plan.nodes[index].definition.algorithm_version,
                parameters=plan.nodes[index].parameters,
                fields=tuple(OutputFieldDescription(
                    name=field.name, sql_type=field.sql_type, nullable=field.nullable,
                    initialization_rule=field.initialization_rule,
                ) for field in plan.nodes[index].definition.output_fields),
            ) for calculation_index, index in plan.instances
        )

    def calculate(self, request, *, output_rows=None, warmup_error_budget=None):
        """Compute the requested region and return a detached immutable result."""
        return self._calculate_request(
            request, output_rows=output_rows, warmup_error_budget=warmup_error_budget,
        )[0]

    def calculate_with_source(
        self, request, *, output_rows=None, warmup_error_budget=None, require_current_period_end_date=False,
    ) -> CalculationWithSource:
        """Return the calculation and the source facts selected by the same read."""
        return self._calculate_request(
            request, output_rows=output_rows, warmup_error_budget=warmup_error_budget,
            include_source_facts=True, require_current_period_end_date=require_current_period_end_date,
        )

    def calculate_index_minutes_recent(self, request, *, output_limit: int) -> CalculationWithSource:
        """Use the local index-minute limit supplied by the trusted application caller."""
        if type(output_limit) is not int or output_limit <= 0:
            raise RequestInvalidError("The index-minute output limit must be a positive integer")
        return self._calculate_request(
            request, include_source_facts=True, index_minute_output_limit=output_limit,
        )

    def calculate_stock_minutes_recent(
        self, request: CalculationRequest, *, output_limit: int,
    ) -> CalculationWithSource:
        """Calculate DG stock minutes with the trusted application's output limit."""
        if type(output_limit) is not int or output_limit <= 0:
            raise RequestInvalidError("The stock-minute output limit must be a positive integer")
        return self._calculate_request(
            request, include_source_facts=True, stock_minute_output_limit=output_limit,
        )

    def _calculate_request(
        self, request, *, output_rows=None, warmup_error_budget=None, include_source_facts=False,
        require_current_period_end_date=False, index_minute_output_limit=None, stock_minute_output_limit=None,
    ):
        control = self.control or ExecutionControl(arrived_at=monotonic(), config=self.config)
        prepared = None
        try:
            control.check_active()
            if index_minute_output_limit is None and stock_minute_output_limit is None:
                prepared = self._prepare_calculation(request)
            else:
                prepared = self.parser.parse(
                    request, index_minute_output_limit=index_minute_output_limit,
                    stock_minute_output_limit=stock_minute_output_limit,
                )
            if output_rows is not None:
                if type(output_rows) is not int or output_rows not in (100, 500):
                    raise RequestInvalidError("output_rows must select 100 or 500")
                prepared = replace(prepared, max_output_rows=min(output_rows, self.config.max_output_rows))
                if request.latest_rows is not None and request.latest_rows > prepared.max_output_rows:
                    raise ResourceLimitError("Target positions exceed max_output_rows")
            if warmup_error_budget is not None:
                if warmup_error_budget not in (INITIALIZATION_ERROR_BUDGET, STOCK_WEEKLY_INITIALIZATION_ERROR_BUDGET):
                    raise RequestInvalidError("Unknown recursive indicator warmup precision")
                prepared = replace(prepared, warmup_error_budget=warmup_error_budget)
            if include_source_facts:
                prepared = replace(prepared, include_source_facts=True,
                                   require_current_period_end_date=require_current_period_end_date)
            return self._calculate_library(prepared, control=control)
        finally:
            prepared = None

    def _prepare_calculation(self, request):
        """Prepare parameters and resolve the dataset without opening resources."""
        return self.parser.parse(request)

    def _build_input_session(self, prepared, engine, executor, read_context, *, collect_target_ohlc=False):
        from .sources.session import PriceInputSession

        engine.prepare()
        history = engine.resolve_history_requirement(
            self.config.max_input_rows, warmup_error_budget=prepared.warmup_error_budget,
        )
        if collect_target_ohlc:
            history = replace(history, fields=history.fields | {"open", "high", "low", "close"})
        requirement = _build_read_requirement(prepared, history, batch_rows=self.config.batch_rows)
        return PriceInputSession(executor, self.source, requirement, read_context=read_context)

    def _calculate_library(self, prepared, *, control, collect_target_ohlc=False):
        result = None
        try:
            result = self._calculate_result(prepared, control=control, collect_target_ohlc=collect_target_ohlc)
            control.check_active()
            return result
        except BaseException as error:
            result = prepared = None
            _clear_error_frames(error)
            raise
        finally:
            result = prepared = None

    def _calculate_result(self, prepared, *, control, collect_target_ohlc=False):
        """Own the single calculation and cleanup flow, without JSON encoding."""
        from .calculation.engine import CalculationEngine
        from .calculation.calculation import SqlStep
        from .contracts import CalculationStatistics
        from .output.collector import OutputCollector
        from .sources.read_context import SourceReadContext

        normalized, plan = prepared.request, prepared.plan
        read_context = SourceReadContext(self.config)
        connection = executor = inputs = engine = output = None
        result = primary_error = None
        target_ohlc = [] if collect_target_ohlc else None
        try:
            control.check_active()
            connection, executor = self._open_execution(control)
            engine = CalculationEngine(executor, plan)
            inputs = self._build_input_session(prepared, engine, executor, read_context,
                                               collect_target_ohlc=collect_target_ohlc)
            inputs.prepare()
            description = inputs.resolved_description()
            if description.selection.target_rows:
                output = OutputCollector(
                    executor=executor, request=normalized, instances=self._describe_output_instances(plan),
                    selection=description.selection,
                )
                while True:
                    control.check_active()
                    batch = inputs.next_batch()
                    if batch is None:
                        break
                    engine.consume(batch)
                    output.append_new_rows(engine.output_for(batch))
                    if target_ohlc is not None:
                        start = max(description.selection.preceding_rows + 1, batch.new_first_seq)
                        if start <= batch.new_last_seq:
                            target_ohlc.extend(executor.read_result(SqlStep(
                                "collect_target_ohlc",
                                f"SELECT open, high, low, close FROM {batch.table_name} "
                                "WHERE seq BETWEEN ? AND ? ORDER BY seq",
                                (start, batch.new_last_seq), (batch.table_name,), (), batch.new_row_count,
                            ), expected_columns=tuple((name, "DOUBLE") for name in ("open", "high", "low", "close")),
                                max_rows=batch.new_last_seq - start + 1))
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
                    description, statistics,
                    read_start=inputs.read_start, read_end=inputs.read_end,
                )
                if target_ohlc is not None and len(target_ohlc) != len(result.times):
                    raise OutputContractError("Target OHLC and calculated dates differ", reason="count_mismatch",
                                              stage="collect_target_ohlc")
                if target_ohlc is not None and any(
                    value is None or not isfinite(value) for row in target_ohlc for value in row
                ):
                    raise OutputContractError("Target OHLC must be finite", reason="invalid_value",
                                              stage="collect_target_ohlc")
            control.check_active()
        except BaseException as exc:
            primary_error = exc
            result = None
        finally:
            cleanup_errors = self._close_execution(
                control, connection, engine=engine, inputs=inputs, output=output,
            )
            read_context.clear_request_metadata()
        try:
            raise_primary_or_cleanup_error_if_any(primary_error, cleanup_errors)
            control.check_active()
            if prepared.include_source_facts:
                return CalculationWithSource(result, description.selection, description.source_facts)
            return result, description.selection.preceding_rows, None if target_ohlc is None else tuple(target_ohlc)
        finally:
            result = output = inputs = engine = executor = connection = prepared = plan = None

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
