"""Approved small failure cases only, sharing the same literal three prices.

Faults intentionally corrupt an internal result after real computation, or
replace only a stop/read/cleanup boundary. Every negative request must fail as
a whole and close actual SQL resources. None creates a real Control thread.
"""

from dataclasses import replace

import pytest

from d3_support import D3Control, ObservedService, TracedSource, d3_data, request
from src.foundation.technical_indicators import CalculationInstance
from src.foundation.technical_indicators.calculation.calculation import SqlStep
from src.foundation.technical_indicators.calculation.engine import CalculationEngine
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationExecutionError, OutputContractError, OutputEncodingError, OutputReadError,
    ResourceCleanupError, ResourceLimitError, SourceReadError,
)


def _literal_request():
    return request((CalculationInstance("ma","ma",{"period":2}),),period="day",adjustment="none")


def _literal_config(state, **changes):
    return replace(state.config, goldenshare_lake_root=str(state.literal_root), **changes)


def _clean_failed_call(state):
    assert state.calls[-1]["status"] == "failed"
    assert state.calls[-1]["live_tables"] == []
    assert state.calls[-1]["live_arrow"] == []


@pytest.mark.parametrize("fault,reason", [
    ("missing_field","missing_fields"),("missing_row","missing_rows"),("wrong_type","type_mismatch"),
])
def test_missing_result_field_row_and_type_fail_whole_request(d3_data, monkeypatch, fault, reason):
    state = d3_data
    original = CalculationEngine.output_for

    def corrupt(self, batch):
        result = original(self,batch)
        table = result.instances[0][1].table_name
        # Injection is test-owned; the product never exposes arbitrary SQL.
        if fault=="missing_field":
            sql = f'ALTER TABLE "{table}" DROP COLUMN value'
        elif fault=="wrong_type":
            sql = f'ALTER TABLE "{table}" ALTER COLUMN value TYPE VARCHAR'
        else:
            sql = f'DELETE FROM "{table}" WHERE seq=2'
        self.executor.execute(SqlStep("d3_test_corrupt_result",sql,(),(table,),(table,),3))
        return result

    with state.case("output_contract_"+fault):
        monkeypatch.setattr(CalculationEngine,"output_for",corrupt)
        with pytest.raises(OutputContractError) as caught:
            state.run(_literal_request(),config=_literal_config(state))
        assert caught.value.reason == reason
        assert caught.value.stage in {"append","inspect"}
        _clean_failed_call(state)


def test_stop_and_source_read_failure_do_not_become_empty_success(d3_data, monkeypatch):
    state = d3_data
    original = CalculationEngine.output_for

    def stop_after_calculation(self,batch):
        result = original(self,batch)
        self.executor.control.stopped = True
        return result

    with state.case("stop_and_read_failure"):
        with monkeypatch.context() as patch:
            patch.setattr(CalculationEngine,"output_for",stop_after_calculation)
            with pytest.raises(CalculationCancelledError):
                state.run(_literal_request(),config=_literal_config(state))
            _clean_failed_call(state)

        class ReadFailure(TracedSource):
            def open(self,*args,**kwargs):
                stream = super().open(*args,**kwargs)

                class Broken:
                    def next_batch(self,max_rows):
                        stream.next_batch(max_rows)
                        raise SourceReadError("D3 deliberate source-read failure")

                    def release_current_batch(self):
                        stream.release_current_batch()

                    def close(self):
                        stream.close()

                return Broken()

        config = _literal_config(state)
        with pytest.raises(SourceReadError,match="deliberate"):
            state.run(_literal_request(),config=config,source=ReadFailure(config))
        _clean_failed_call(state)


def test_actual_input_limit_and_cleanup_failure_remain_errors(d3_data, monkeypatch):
    state = d3_data
    with state.case("input_limit_and_cleanup_failure"):
        with pytest.raises(ResourceLimitError):
            state.run(_literal_request(),config=_literal_config(state,max_input_rows=2))
        _clean_failed_call(state)
        original = CalculationEngine.close

        def fail_after_real_cleanup(self):
            original(self)
            raise ResourceCleanupError("D3 deliberately reported cleanup failure")

        monkeypatch.setattr(CalculationEngine,"close",fail_after_real_cleanup)
        with pytest.raises(ResourceCleanupError,match="cleanup"):
            state.run(_literal_request(),config=_literal_config(state))
        _clean_failed_call(state)


def test_strict_utf8_exact_limit_and_nonfinite_errors(d3_data):
    from src.foundation.technical_indicators.output.encoding import encode_response_utf8

    state = d3_data
    with state.case("strict_utf8_boundaries"):
        payload = {"msg":"全部"}
        expected = '{"msg":"全部"}'.encode("utf-8")
        control = D3Control(state.config)
        assert len(expected)>len('{"msg":"全部"}')
        assert encode_response_utf8(payload,control=control,max_bytes=len(expected)+1) == expected
        assert encode_response_utf8(payload,control=control,max_bytes=len(expected)) == expected
        with pytest.raises(ResourceLimitError):
            encode_response_utf8(payload,control=control,max_bytes=len(expected)-1)
        with pytest.raises(OutputEncodingError):
            encode_response_utf8({"bad":float("nan")},control=control,max_bytes=1000)
        with pytest.raises(OutputEncodingError):
            encode_response_utf8({"bad":object()},control=control,max_bytes=1000)


def test_result_fetch_continues_after_short_batch_and_preserves_fetch_error(d3_data):
    state = d3_data
    with state.case("complete_result_fetch"):
        control = D3Control(state.config)
        service = ObservedService(source=None,registry=None,config=state.config,control=control)
        connection, executor = service._open_execution(control)
        state.input_rows += 3
        try:
            executor.execute(SqlStep("d3_read_fixture",
                "CREATE TEMP TABLE ti_d3_read AS SELECT i::BIGINT AS seq,i::DOUBLE AS value FROM range(1,4) t(i)",
                (),(),("ti_d3_read",),3))
            step = SqlStep("select_result","SELECT seq,value FROM ti_d3_read ORDER BY seq",
                           (),("ti_d3_read",),(),3)

            class ShortCursor:
                def __init__(self, actual, fail=False):
                    self.actual, self.description, self.calls = actual, actual.description, 0
                    self.fail = fail

                def fetchmany(self, count):
                    assert count<=8192
                    self.calls += 1
                    if self.fail and self.calls==2:
                        raise OSError("D3 deliberate fetch failure")
                    return self.actual.fetchmany(1)

            class ConnectionView:
                def __init__(self, fail=False):
                    self.fail = fail
                    self.cursor = None

                def execute(self, sql, bindings):
                    self.cursor = ShortCursor(connection.execute(sql,bindings), self.fail)
                    return self.cursor

            normal = ConnectionView()
            executor.connection = normal
            result = executor.read_result(step,expected_columns=(("seq","BIGINT"),("value","DOUBLE")),max_rows=3)
            assert result == ((1,1.0),(2,2.0),(3,3.0))
            assert normal.cursor.calls == 4
            failed = ConnectionView(fail=True)
            executor.connection = failed
            with pytest.raises(OutputReadError) as caught:
                executor.read_result(step,expected_columns=(("seq","BIGINT"),("value","DOUBLE")),max_rows=3)
            assert caught.value.reason == "fetch_failed" and caught.value.stage == "final_fetch"
            assert isinstance(caught.value.__cause__,OSError)
            assert not executor._executing
        finally:
            executor.connection = connection
            control.stop_monitor()
            executor.cleanup_drop("ti_d3_read")
            errors = service._close_execution(control,connection)
            state.sql_rows += executor.sql_processed_rows
            state.queries.extend(dict(name="executor_"+s.step_name,logical_input_rows=s.logical_input_rows,
                                      output_rows=s.output_rows,status="failed" if s.failed else "passed",
                                      elapsed_seconds=s.elapsed_ms/1000)
                                 for s in executor.statistics)
            state.save()
            assert not errors and not executor._live_tables


def test_borrowed_tables_and_fixed_template_boundaries(d3_data, monkeypatch):
    import io
    from pathlib import Path

    from src.foundation.technical_indicators.calculation.sql_templates import load_sql_templates

    state = d3_data
    original = CalculationEngine.output_for

    def check_ownership(self,batch):
        result = original(self,batch)
        for session in self.sessions.values():
            if "macd_segment" in session.allowed_step_names:
                before = len(self.executor.statistics)
                with pytest.raises(CalculationExecutionError):
                    session.execute(SqlStep("macd_segment","SELECT 1",(),("ti_price_new",),(),1))
                # Even putting a borrowed name in a mutable cleanup list does
                # not transfer ownership of the input or another dependency.
                session.batch_tables.append(batch.table_name)
                try:
                    with pytest.raises(CalculationExecutionError):
                        session.drop_owned_table(batch.table_name)
                finally:
                    session.batch_tables.remove(batch.table_name)
                assert len(self.executor.statistics)==before
            if session.dependencies:
                borrowed = next(iter(session.dependencies.values())).table_name
                before = len(self.executor.statistics)
                session.batch_tables.append(borrowed)
                try:
                    with pytest.raises(CalculationExecutionError):
                        session.drop_owned_table(borrowed)
                finally:
                    session.batch_tables.remove(borrowed)
                assert len(self.executor.statistics)==before
        return result

    with state.case("borrowed_tables_and_fixed_templates"):
        with monkeypatch.context() as patch:
            patch.setattr(CalculationEngine,"output_for",check_ownership)
            result, service, _ = state.run(request((
                CalculationInstance("macd","macd",{"fast":2,"slow":3,"signal":2}),
                CalculationInstance("boll","boll",{"period":2}),
            ),period="day",adjustment="none"),config=_literal_config(state))
            assert result.range.count==3
            assert service.observed_executor._live_tables==set()

        opened = []
        actual_open = io.open

        def observe(file,*args,**kwargs):
            opened.append(str(file))
            return actual_open(file,*args,**kwargs)

        class InvalidTemplate:
            SQL_PACKAGE = "src.foundation.technical_indicators.calculation"
            SQL_FILES = ("../macd_segment.sql",)

        with monkeypatch.context() as patch:
            patch.setattr(io,"open",observe)
            with pytest.raises(CalculationExecutionError):
                load_sql_templates(InvalidTemplate,request_texts={},control=D3Control(state.config))
        assert opened==[]

        from src.foundation.technical_indicators.output.collector import OutputCollector
        captured = []
        initialize = OutputCollector.__init__

        def capture(self,*args,**kwargs):
            captured.append(self)
            initialize(self,*args,**kwargs)

        def fail_second_output_file(file,*args,**kwargs):
            if isinstance(file,(str,Path)) and Path(file).name=="retain_tail.sql":
                raise OSError("D3 deliberate package-text read failure")
            return actual_open(file,*args,**kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(OutputCollector,"__init__",capture)
            patch.setattr(io,"open",fail_second_output_file)
            with pytest.raises(CalculationExecutionError) as caught:
                state.run(_literal_request(),config=_literal_config(state))
        assert isinstance(caught.value.__cause__,OSError)
        assert captured and not captured[0]._templates and not captured[0]._template_texts
        assert state.calls[-1]["source_rows"]==0
        _clean_failed_call(state)
