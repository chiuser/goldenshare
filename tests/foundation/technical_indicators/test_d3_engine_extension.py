"""LLD §19.25: the two approved small engine/template acceptance cases.

The only new price input is the three in-memory bars stated in the LLD. SQL
remains the real fixed implementation; only clock/stop and intentional cleanup
failure are substituted. Expected KDJ values below are independent literals.
"""

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from d3_support import (
    D3Control, ObservedService, assert_closed, close_enough, d3_data, request,
)
from src.foundation.technical_indicators import CalculationInstance
from src.foundation.technical_indicators.calculation.calculation import (
    CalculationDefinition, CalculationOutput, Dependency, OutputField, SqlStep,
)
from src.foundation.technical_indicators.calculation.engine import CalculationEngine
from src.foundation.technical_indicators.calculation.history import HistoryRequirement
from src.foundation.technical_indicators.calculation.indicators import kdj, price
from src.foundation.technical_indicators.calculation.registry import CalculationRegistry
from src.foundation.technical_indicators.calculation.sql_templates import load_sql_templates
from src.foundation.technical_indicators.contracts import normalize_request_and_validate_all_instances
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationExecutionError, OutputContractError, ResourceCleanupError,
)
from src.foundation.technical_indicators.executor import DuckDBExecutor
from src.foundation.technical_indicators.output.collector import OutputCollector
from src.foundation.technical_indicators.service import raise_primary_or_cleanup_error_if_any
from src.foundation.technical_indicators.sources.contracts import PriceBatch


_PACKAGE = "src.foundation.technical_indicators.calculation"
_CLOSE_FIELD = OutputField("close", "close", "DOUBLE", False, "目标价格原样")
_CLOSE_DEFINITION = CalculationDefinition(
    calculation_id="d3_borrowed_close", algorithm_version="1.0.0",
    description="Test-only Calculation borrowing the price dependency's close",
    parameter_specs=(), input_fields=frozenset({"close"}),
    output_fields=(_CLOSE_FIELD,), initialization="目标价格原样",
    history_rule="No preceding bars", units=(("close", "source_price_unit"),),
)


class _BorrowedCloseCalculation:
    """A new complete Calculation, with no engine-specific execution branch."""

    SQL_PACKAGE = _PACKAGE
    SQL_FILES = ()
    TABLE_ROLES = MappingProxyType({})
    FIXED_SQL_STEPS = MappingProxyType({})

    def __init__(self, parameters, events):
        self.parameters = parameters
        self.events = events

    def input_requirement(self):
        return HistoryRequirement(frozenset({"close"}), 0, False, (), "目标价格原样")

    def dependencies(self):
        return (Dependency("price", "price", "1.0.0", ()),)

    def prepare(self, session):
        assert session.parameters == ()
        assert not session.sql_templates
        self.events.append("prepare")
        session.initialized = True

    def consume(self, batch, session):
        assert session.initialized and session.current_batch is batch
        dependency = session.dependencies["price"]
        assert dependency.table_name == batch.table_name
        assert dependency.new_first_seq == batch.new_first_seq
        assert dependency.new_last_seq == batch.new_last_seq
        assert not session.state_tables and not session.batch_tables
        self.events.append("consume")
        return CalculationOutput(dependency.table_name, (_CLOSE_FIELD,),
                                 batch.new_first_seq, batch.new_last_seq)

    def release_batch(self, session):
        assert not session.state_tables and not session.batch_tables
        self.events.append("release_batch")

    def release(self, session):
        assert not session.state_tables and not session.batch_tables
        self.events.append("release")
        session.initialized = False


def _registry(events, calculation_type=_BorrowedCloseCalculation, *, include_kdj):
    registry = CalculationRegistry()
    registry.register(price.DEFINITION, price.PriceCalculation)
    if include_kdj:
        registry.register(kdj.WINDOW_RANGE_DEFINITION, kdj.WindowRangeCalculation)
        registry.register(kdj.DEFINITION, kdj.KDJCalculation)
    registry.register(_CLOSE_DEFINITION, lambda parameters: calculation_type(parameters, events))
    registry.freeze()
    return registry


def _record_executor(state, executor, call):
    """Charge every real SqlStep, including a failed step and cleanup."""
    if executor is not None:
        state.sql_rows += executor.sql_processed_rows
        call.update(
            sql_logical_rows=executor.sql_processed_rows,
            steps=[dict(step_name=item.step_name, logical_input_rows=item.logical_input_rows,
                        output_rows=item.output_rows, failed=item.failed)
                   for item in executor.statistics],
            live_tables=sorted(executor._live_tables), live_arrow=sorted(executor._live_arrow),
        )
    state.save()


def test_new_calculation_and_kdj_boundaries_use_existing_engine(d3_data):
    state = d3_data
    with state.case("new_calculation_kdj_boundaries_and_old_batch"):
        events = []
        registry = _registry(events, include_kdj=True)
        normalized = normalize_request_and_validate_all_instances(request((
            CalculationInstance("borrowed", "d3_borrowed_close", {}),
            CalculationInstance("default", "kdj", {}),
            CalculationInstance("k1", "kdj", {"k_period": 1}),
            CalculationInstance("d1", "kdj", {"d_period": 1}),
        ), period="day", adjustment="none"), state.config)
        plan = registry.expand_dependencies(normalized)
        control = D3Control(state.config)
        service = ObservedService(source=None, registry=registry, config=state.config, control=control)
        connection = executor = engine = collector = inputs = None
        primary_error = None
        cleanup_errors = ()
        call = dict(real_control=False, period="day", source_kind="memory_literal",
                    source_rows=0, input_rows=3, source_files=0, source_open_calls=0,
                    batches=[3], status="running")
        state.calls.append(call)
        state.save()
        try:
            connection, executor = service._open_execution(control)
            table = "ti_d3_extension_prices"
            # This is the fixed LLD literal input, not a production source or a
            # reference generated with a calculation helper.
            executor.declare_table(table)
            inputs = SimpleNamespace(close=lambda: executor.cleanup_drop(table))
            state.input_rows += 3
            state.save()
            executor.execute(SqlStep("d3_extension_fixture", """
                CREATE TEMP TABLE ti_d3_extension_prices AS
                SELECT seq::BIGINT AS seq, trade_date::DATE AS trade_date,
                    trade_date::DATE AS period_start, trade_date::DATE AS period_end,
                    trade_date::DATE AS source_as_of, close::DOUBLE AS open,
                    10.0::DOUBLE AS high, 0.0::DOUBLE AS low, close::DOUBLE AS close,
                    1.0::DOUBLE AS volume, close::DOUBLE AS amount
                FROM (VALUES (1, DATE '2026-01-05', 6.0),
                             (2, DATE '2026-01-06', 9.0),
                             (3, DATE '2026-01-07', 3.0)) bars(seq, trade_date, close)
                """, (), (), (table,), 3))
            batch = PriceBatch(
                table, 1, 3, 3, 0,
                ("trade_date", "period_start", "period_end", "source_as_of"),
                ("open", "high", "low", "close", "volume", "amount"), "none",
            )
            engine = CalculationEngine(executor, plan)
            engine.prepare()
            engine.consume(batch)
            outputs = engine.output_for(batch)
            assert tuple(identity for identity, _ in outputs.instances) == ("borrowed", "default", "k1", "d1")
            assert events == ["prepare", "consume"]
            assert len([item for item in executor.statistics if item.step_name == "kdj_window"]) == 1

            # RSV is 60/90/30. The exact fractions and the decimal values below
            # are fixed in LLD §19.25; no tested formula produces the expected.
            expected = {
                "default": (
                    (53.33333333333333, 65.55555555555556, 53.70370370370370),
                    (51.11111111111111, 55.92592592592592, 55.18518518518518),
                    (57.77777777777778, 84.81481481481481, 50.74074074074074),
                ),
                "k1": (
                    (60.0, 90.0, 30.0),
                    (53.33333333333333, 65.55555555555556, 53.70370370370370),
                    (73.33333333333333, 138.8888888888889, -17.40740740740741),
                ),
                "d1": (
                    (53.33333333333333, 65.55555555555556, 53.70370370370370),
                    (53.33333333333333, 65.55555555555556, 53.70370370370370),
                    (53.33333333333333, 65.55555555555556, 53.70370370370370),
                ),
            }
            for identity, output in outputs.instances:
                projection = "seq,close" if identity == "borrowed" else "seq,k,d,j"
                columns = (("seq", "BIGINT"), ("close", "DOUBLE")) if identity == "borrowed" else (
                    ("seq", "BIGINT"), ("k", "DOUBLE"), ("d", "DOUBLE"), ("j", "DOUBLE"),
                )
                rows = executor.read_result(
                    SqlStep("select_result", f'SELECT {projection} FROM "{output.table_name}" ORDER BY seq',
                            (), (output.table_name,), (), 3),
                    expected_columns=columns, max_rows=3,
                )
                assert tuple(row[0] for row in rows) == (1, 2, 3)
                if identity == "borrowed":
                    assert rows == ((1, 6.0), (2, 9.0), (3, 3.0))
                    assert output.table_name == table
                else:
                    for position, wanted in enumerate(expected[identity], start=1):
                        close_enough(tuple(row[position] for row in rows), wanted)

            before = len(executor.statistics)
            with pytest.raises(CalculationExecutionError, match="price batch"):
                engine.output_for(replace(batch, new_first_seq=0, new_last_seq=2))
            assert len(executor.statistics) == before
            assert engine.output_for(batch) == outputs
            collector = OutputCollector(
                executor=executor, request=normalized, instances=service._describe_output_instances(plan),
            )
            identity, first = outputs.instances[0]
            stale = replace(first, new_first_seq=0, new_last_seq=2)
            old_outputs = replace(outputs, instances=((identity, stale), *outputs.instances[1:]))
            before = len(executor.statistics)
            with pytest.raises(OutputContractError) as caught:
                collector.append_new_rows(old_outputs)
            assert caught.value.reason == "wrong_batch" and caught.value.stage == "append"
            assert len(executor.statistics) == before

            engine.release_batch_tables()
            engine.finish()
            assert events == ["prepare", "consume", "release_batch"]
            assert table in executor._live_tables
            call["status"] = "passed"
        except BaseException as error:
            primary_error = error
            call.update(status="failed", error_type=type(error).__name__, error=str(error))
        finally:
            cleanup_errors = service._close_execution(
                control, connection, engine=engine, inputs=inputs, output=collector,
            )
            call["cleanup_errors"] = [f"{type(error).__name__}: {error}" for error in cleanup_errors]
            _record_executor(state, executor, call)
        raise_primary_or_cleanup_error_if_any(primary_error, cleanup_errors)
        assert events == ["prepare", "consume", "release_batch", "release"]
        assert_closed(service)


def test_template_cache_readonly_cancellation_and_repeat_cleanup(d3_data, monkeypatch):
    state = d3_data
    with state.case("template_cache_readonly_cancel_and_repeat_cleanup"):
        control = D3Control(state.config)
        cached = {
            (_PACKAGE, "rolling_mean.sql"): "fixed rolling-mean text",
            (_PACKAGE, "kdj_window.sql"): "another declared file's text",
            (_PACKAGE, "unknown.sql"): "cached but never implemented",
        }

        class UnknownTemplate:
            SQL_PACKAGE = _PACKAGE
            SQL_FILES = ("unknown.sql",)

        class OnlyRollingMean:
            SQL_PACKAGE = _PACKAGE
            SQL_FILES = ("rolling_mean.sql",)

        before_cache = dict(cached)
        with pytest.raises(CalculationExecutionError, match="not an implemented file"):
            load_sql_templates(UnknownTemplate, request_texts=cached, control=control)
        assert cached == before_cache
        visible = load_sql_templates(OnlyRollingMean, request_texts=cached, control=control)
        assert dict(visible) == {"rolling_mean.sql": "fixed rolling-mean text"}
        with pytest.raises(TypeError):
            visible["rolling_mean.sql"] = "replacement"
        assert cached == before_cache

        class TwoTemplateCalculation(_BorrowedCloseCalculation):
            SQL_FILES = ("smoothing_parameters.sql", "kdj_segment.sql")

        events = []
        registry = _registry(events, TwoTemplateCalculation, include_kdj=False)
        normalized = normalize_request_and_validate_all_instances(request((
            CalculationInstance("borrowed", "d3_borrowed_close", {}),
        ), period="day", adjustment="none"), state.config)
        executor = DuckDBExecutor(None, control)
        engine = CalculationEngine(executor, registry.expand_dependencies(normalized))
        original_read = Path.read_text
        reads = []
        texts = {}

        def stop_after_second_complete_text(path, *args, **kwargs):
            text = original_read(path, *args, **kwargs)
            if path.parent.name == "sql" and path.parent.parent.name == "calculation":
                reads.append(path.name)
                texts[path.name] = text
                state.template_reads.append(str(path.resolve()))
                if path.name == "kdj_segment.sql":
                    control.stopped = True
            return text

        call = dict(real_control=False, source_kind="no_source", source_rows=0, input_rows=0,
                    source_files=0, source_open_calls=0, status="running")
        state.calls.append(call)
        state.save()
        primary_error = None
        cleanup_errors = []
        try:
            with monkeypatch.context() as patch:
                patch.setattr(Path, "read_text", stop_after_second_complete_text)
                with pytest.raises(CalculationCancelledError):
                    engine.prepare()
            assert reads == ["smoothing_parameters.sql", "kdj_segment.sql"]
            assert engine._template_texts == {
                (_PACKAGE, "smoothing_parameters.sql"): texts["smoothing_parameters.sql"],
            }
            assert (_PACKAGE, "kdj_segment.sql") not in engine._template_texts
            assert all(not session.sql_templates for session in engine.sessions.values())
            assert executor.statistics == ()
            assert events == []
            assert control.stop_monitor() == ()

            def fail_release(self, session):
                raise ResourceCleanupError("D3 deliberately injected template cleanup failure")

            with monkeypatch.context() as patch:
                patch.setattr(TwoTemplateCalculation, "release", fail_release)
                with pytest.raises(ResourceCleanupError, match="resource cleanup failed") as caught:
                    engine.close()
            assert isinstance(caught.value.__cause__, ResourceCleanupError)
            assert "injected template cleanup" in str(caught.value.__cause__)
            assert not engine._closed
            assert not engine._template_texts
            assert all(not session.sql_templates for session in engine.sessions.values())
            assert not executor._live_tables and not executor._live_arrow
            engine.close()
            engine.close()
            assert engine._closed
            assert not engine._template_texts
            assert all(not session.sql_templates for session in engine.sessions.values())
            assert executor.statistics == ()
            call.update(status="passed", expected_cleanup_error=type(caught.value).__name__)
        except BaseException as error:
            primary_error = error
            call.update(status="failed", error_type=type(error).__name__, error=str(error))
        finally:
            control.stop_monitor()
            try:
                engine.close()
            except BaseException as error:
                cleanup_errors.append(error)
            call["cleanup_errors"] = [f"{type(error).__name__}: {error}" for error in cleanup_errors]
            _record_executor(state, executor, call)
        raise_primary_or_cleanup_error_if_any(primary_error, tuple(cleanup_errors))
        assert not executor.statistics
        assert not executor._live_tables and not executor._live_arrow
