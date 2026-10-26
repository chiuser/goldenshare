"""LLD 19.33.7: the eight approved, finite fourth-batch repair checks.

No work runs at import time. This file owns its pytest directory and never
calls d3_data or writes the D3 report. Canonical minute/day/period fields follow
the verified producer contracts already recorded in d3_reference and the LLD.
Only stop signals and deliberate handoff faults are substituted; Arrow,
Parquet, DuckDB, parameter SQL, indicator SQL and normal result reads are real.
"""

from contextlib import contextmanager
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from types import SimpleNamespace
from zoneinfo import ZoneInfo

_PROGRAM_STARTED = monotonic()

import pytest

from d3_reference import DAILY_DATES, MACD_REFERENCE
from d3_support import D3Control
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.calculation import SqlStep
from src.foundation.technical_indicators.calculation.engine import CalculationEngine
from src.foundation.technical_indicators.calculation.indicators import create_builtin_registry
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationExecutionError, OutputContractError,
    RequestInvalidError, ResourceCleanupError, ResourceLimitError, SourceContractError,
    SourceReadError, SourceUnsupportedError,
)
from src.foundation.technical_indicators.output.collector import OutputCollector
from src.foundation.technical_indicators.service import TechnicalIndicatorService, connect_private_memory_instance


_REPORT = Path(__file__).resolve().parents[3] / "reports/technical_indicator_kernel_fourth_batch_fix"
_OLD_REFERENCE = _REPORT.parent / "technical_indicator_kernel_d3_20261025/independent_reference.json"
_MA = (5, 10, 20, 30, 60, 90, 250)


def _request(calculations=None, **changes):
    return CalculationRequest(**(dict(security_type="stock", ts_code="600000.SH", period="1m",
        calculations=calculations or (CalculationInstance("price", "price", {}),), limit=1000) | changes))


def _default_calculations():
    return (CalculationInstance("macd", "macd", {}), CalculationInstance("kdj", "kdj", {}),
            *(CalculationInstance("ma" + str(n), "ma", {"period": n}) for n in _MA),
            CalculationInstance("boll", "boll", {}), CalculationInstance("price", "price", {}))


def _values(result):
    return {item.instance_id: dict(item.fields) for item in result.calculations}


def _close(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if want is None:
            assert got is None
        else:
            assert got is not None and abs(got - want) <= 1e-8 + 1e-10 * abs(want)


class _Source:
    """Observe the genuine locator and stream without changing their data."""

    def __init__(self, config):
        self.actual = LakeTechnicalIndicatorPriceSource(config)
        self.context = None
        self.requirement = self.description = None
        self.batches, self.locators, self.streams = [], [], []
        self.actual_price_rows = self.open_calls = 0
        self.selection_delta = 0

    def __getattr__(self, name):
        return getattr(self.actual, name)

    def create_locator(self, executor, requirement, *, read_context):
        self.context, self.requirement = read_context, requirement
        record = read_context.record_price_rows

        def charge(rows):
            self.actual_price_rows += rows
            return record(rows)

        read_context.record_price_rows = charge
        actual = self.actual.create_locator(executor, requirement, read_context=read_context)
        self.locators.append(actual)
        source = self

        class Locator:
            def describe(self):
                description = actual.describe()
                if source.selection_delta:
                    description = replace(description, selection=replace(description.selection,
                        target_rows=description.selection.target_rows + source.selection_delta))
                source.description = description
                return description

            def close(self):
                return actual.close()

        return Locator()

    def open(self, executor, description, requirement, *, read_context):
        self.open_calls += 1
        actual = self.actual.open(executor, description, requirement, read_context=read_context)
        self.streams.append(actual)
        source = self

        class Stream:
            def next_batch(self, max_rows):
                batch = actual.next_batch(max_rows)
                if batch is not None:
                    source.batches.append(batch.selected_rows)
                return batch

            def release_current_batch(self):
                return actual.release_current_batch()

            def close(self):
                return actual.close()

        return Stream()


class _Service(TechnicalIndicatorService):
    def _open_execution(self, control):
        connection, executor = super()._open_execution(control)
        self.observed_connection, self.observed_executor = connection, executor
        self.warmups = []
        original = executor.read_control_row

        def observed(step, *, expected_columns):
            row = original(step, expected_columns=expected_columns)
            if step.name == "read_warmup_rows":
                self.warmups.append(row)
            return row

        executor.read_control_row = observed
        return connection, executor


class _State:
    def __init__(self, root):
        from src.foundation.config.settings import Settings
        self.root, self.started = root, _PROGRAM_STARTED
        self.saved = json.loads((_REPORT / "progress.json").read_text())
        self.elapsed_before = self.saved["elapsed_seconds"]
        self.input_rows = self.saved["input_rows"]
        self.sql_rows = self.saved["sql_logical_rows"]
        self.locator_rows = self.saved["locator_rows"]
        assert self.saved["real_controls"] == 0
        self.calls, self.queries = [], []
        self.config = KernelConfig.from_settings(Settings(_env_file=None, GOLDENSHARE_LAKE_ROOT=str(root)))
        self.references = json.loads(_OLD_REFERENCE.read_text())
        self.last_service = self.last_source = None

    def save(self):
        elapsed = self.elapsed_before + monotonic() - self.started
        self.saved.update(input_rows=self.input_rows, sql_logical_rows=self.sql_rows,
            locator_rows=self.locator_rows, real_controls=0, elapsed_seconds=elapsed,
            fixture_root=str(self.root),
            calls=self.calls, queries=self.queries,
            remaining=dict(input_rows=35000-self.input_rows, sql_logical_rows=1000000-self.sql_rows,
                           locator_rows=40000-self.locator_rows, real_controls=0,
                           program_seconds=30, total_seconds=300-elapsed))
        (_REPORT / "progress.json").write_text(json.dumps(self.saved, ensure_ascii=False, indent=2) + "\n")

    def budget(self):
        assert self.input_rows <= 35000
        assert self.sql_rows <= 1000000
        assert self.locator_rows <= 40000
        assert monotonic()-self.started < 30
        assert self.elapsed_before+monotonic()-self.started < 300

    @contextmanager
    def case(self, name):
        node = "tests/foundation/technical_indicators/test_fourth_batch_fix.py::" + name
        assert node not in self.saved["completed_nodes"], "Do not rerun an already completed acceptance node"
        attempt = dict(kind="approved_acceptance", node=node, status="running")
        self.saved["attempts"].append(attempt)
        self.save()
        try:
            yield
            self.budget()
            attempt["status"] = "passed"
            self.saved["completed_nodes"].append(node)
        except BaseException as error:
            attempt.update(status="failed_stop_without_retry", error_type=type(error).__name__, error=str(error))
            self.saved["status"] = "failed_acceptance_stop_without_retry"
            raise
        finally:
            self.save()

    def query(self, connection, name, sql, *, rows, bindings=()):
        self.sql_rows += rows
        event = dict(name=name, logical_rows=rows, status="running")
        self.queries.append(event)
        self.save()
        self.budget()
        try:
            result = connection.execute(sql, bindings).fetchall()
            event.update(status="passed", output_rows=len(result))
            return result
        except BaseException as error:
            event.update(status="failed", error_type=type(error).__name__)
            raise
        finally:
            self.save()

    def run(self, request, *, root="minutes", config=None, source=None, expected_cleanup_error=False):
        import duckdb
        config = config or replace(self.config, goldenshare_lake_root=str(self.root/root))
        source = source or _Source(config)
        service = _Service(source=source, registry=create_builtin_registry(), config=config, control=D3Control(config))
        self.last_service, self.last_source = service, source
        call = dict(period=request.period, status="running", root=root)
        self.calls.append(call)
        self.save()
        try:
            result = service.calculate(request)
            call["status"] = "passed"
            return result, service, source
        except BaseException as error:
            call.update(status="failed", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            self.input_rows += source.actual_price_rows
            self.locator_rows += source.context.locator_rows if source.context is not None else 0
            executor = getattr(service, "observed_executor", None)
            logical = executor.sql_processed_rows if executor is not None else 0
            self.sql_rows += logical
            call.update(source_rows=source.actual_price_rows, locator_rows=(source.context.locator_rows if source.context else 0),
                sql_logical_rows=logical, batches=source.batches, open_calls=source.open_calls,
                warmups=service.warmups if executor else [],
                live_tables=sorted(executor._live_tables) if executor else [],
                live_arrow=sorted(executor._live_arrow) if executor else [],
                steps=[dict(name=s.step_name, rows=s.logical_input_rows, output=s.output_rows, failed=s.failed)
                       for s in executor.statistics] if executor else [])
            if executor is not None:
                assert not executor._live_tables and not executor._live_arrow
                assert service.control.cleanup_ready
                if expected_cleanup_error:
                    assert service.control.resources_released_at is None
                else:
                    assert service.control.resources_released_at is not None
                self.sql_rows += 1  # Conservative charge for this deliberately rejected query.
                with pytest.raises(duckdb.ConnectionException, match="[Cc]losed"):
                    service.observed_connection.execute("SELECT 1")
            assert all(locator._closed for locator in source.locators)
            assert all(stream._closed for stream in source.streams)
            self.save()

    def prepare(self):
        import duckdb
        import pyarrow as pa
        import pyarrow.parquet as pq
        con = duckdb.connect(":memory:", config={"threads":1,"memory_limit":"128MiB","max_temp_directory_size":"0B"})
        try:
            self.query(con, "fixture_numbered_prices", """CREATE TEMP TABLE d3_bars AS
              WITH numbered AS (SELECT i::BIGINT AS seq,10000+3*(i%11)-5*(i%7) AS cents,
                DATE '2024-01-02'+CAST(floor((i-1)/240) AS INTEGER) AS day,
                (i-1)%240 AS minute_index FROM range(1,4001) t(i))
              SELECT *,CAST(day AS TIMESTAMP)+CASE WHEN minute_index<120
                THEN INTERVAL 9 HOUR+INTERVAL 31 MINUTE+minute_index*INTERVAL 1 MINUTE
                ELSE INTERVAL 13 HOUR+INTERVAL 1 MINUTE+(minute_index-120)*INTERVAL 1 MINUTE
                END AS bar_time FROM numbered ORDER BY seq""", rows=4000)
            self.input_rows += 4000
            for folder, count in (("minutes",4000),("short",1600)):
                path = self.root/folder/"gold/quote/stk_mins_qfq/freq=1/ts_code=600000.SH/year=2024/part-000.parquet"
                path.parent.mkdir(parents=True)
                copied = self.query(con, "fixture_"+folder, """COPY (
                    SELECT '600000.SH'::VARCHAR ts_code,day::DATE trade_date,bar_time::TIMESTAMP trade_time,
                     cents/100.0 AS open,(cents+100)/100.0 AS high,(cents-100)/100.0 AS low,
                     cents/100.0 AS close,100.0::DOUBLE AS vol,1000.0::DOUBLE AS amount
                    FROM d3_bars WHERE seq<=$count ORDER BY seq)
                    TO $target (FORMAT PARQUET,ROW_GROUP_SIZE 8192)""", rows=count,
                    bindings={"count":count,"target":str(path)})
                assert copied == [(count,)]
                if folder == "short":
                    self.input_rows += 1600
                schema = pq.read_schema(path)
                assert tuple((field.name, field.type) for field in schema) == (
                    ("ts_code",pa.string()),("trade_date",pa.date32()),("trade_time",pa.timestamp("us")),
                    *((name,pa.float64()) for name in ("open","high","low","close","vol","amount")))
            self.times = tuple(row[0].replace(tzinfo=ZoneInfo("Asia/Shanghai")) for row in
                self.query(con,"fixture_times","SELECT bar_time FROM d3_bars ORDER BY seq",rows=4000))
            for label, fast, slow, signal in (("macd9",9,65,9),("macd10",10,69,10)):
                target = _REPORT/("reference_4000_"+label+".json")
                if target.exists():
                    reference = json.loads(target.read_text())
                else:
                    self.input_rows += 4000
                    reference = self.query(con,"reference_"+label,MACD_REFERENCE,rows=8000,
                                           bindings=(fast,slow,signal,4000))
                    target.write_text(json.dumps(reference,separators=(",",":"))+"\n")
                assert len(reference) == 4000
                assert tuple(reference[0]) == (1,0.0,0.0,0.0)
                self.references[label] = reference
            for i,text in enumerate(DAILY_DATES):
                for folder in ("daily", "literal"):
                    if folder == "literal" and i >= 3:
                        continue
                    price = (10.0 if i<10 else 6.0) if folder == "daily" else (10.0,12.0,11.0)[i]
                    day = date.fromisoformat(text)
                    path = self.root/folder/f"silver/quote/stock_daily/trade_date={text}/part-000.parquet"
                    path.parent.mkdir(parents=True)
                    assert self.query(con,"fixture_"+folder,"""COPY (
                        SELECT '600000.SH'::VARCHAR ts_code,$day::DATE trade_date,
                          $price::DOUBLE AS open,$price::DOUBLE AS high,$price::DOUBLE AS low,$price::DOUBLE AS close,
                          100.0::DOUBLE vol,1000.0::DOUBLE amount)
                        TO $target (FORMAT PARQUET)""",rows=1,
                        bindings={"day":day,"price":price,"target":str(path)}) == [(1,)]
                    self.input_rows += 1
                path = self.root/f"daily/silver/quote/adj_factor/trade_date={text}/part-000.parquet"
                path.parent.mkdir(parents=True)
                assert self.query(con,"fixture_factor","""COPY (
                    SELECT '600000.SH'::VARCHAR ts_code,$day::DATE trade_date,$factor::DOUBLE adj_factor)
                    TO $target (FORMAT PARQUET)""",rows=1,
                    bindings={"day":day,"factor":1.0 if i<10 else 2.0,"target":str(path)}) == [(1,)]
                self.input_rows += 1
            self.save()
        finally:
            con.close()


@pytest.fixture(scope="session")
def fourth_data(tmp_path_factory):
    parent = tmp_path_factory.mktemp("technical_indicator_fourth_fix")
    owned = TemporaryDirectory(prefix="owned_",dir=parent)
    state = None
    try:
        state = _State(Path(owned.name))
        try:
            state.prepare()
        except BaseException as error:
            state.saved.update(status="failed_fixture_stop_without_retry",
                               fixture_error=dict(type=type(error).__name__,message=str(error)))
            state.save()
            raise
        yield state
    finally:
        owned.cleanup()
        if state is not None:
            assert not state.root.exists()
            state.saved["fixture_cleanup"] = "owned_directory_removed"
            state.save()


def _compare(result, state, first, last, *, macd="macd", kdj=False, windows=False):
    assert result.times == state.times[first:last]
    assert result.range.count == last-first
    actual = _values(result)
    if macd:
        for column,name in enumerate(("dif","dea","hist"),1):
            reference = tuple(row[column] for row in state.references[macd][first:last])
            _close(actual[macd][name],reference)
            for got,want in zip(actual[macd][name],reference):
                if abs(want)>1e-8:
                    assert (got>0)==(want>0)
            near = [(got,want) for got,want in zip(actual[macd][name],reference) if abs(want)<=1e-8]
            if near:
                state.saved.setdefault("near_zero_checks",[]).append(dict(
                    calculation=macd,field=name,first=first,last=last,count=len(near),
                    sign_differences=sum((got>0)!=(want>0) or (got<0)!=(want<0) for got,want in near)))
    if kdj:
        for column,name in enumerate(("k","d","j"),1):
            _close(actual["kdj"][name],tuple(row[column] for row in state.references["kdj"][first:last]))
    if windows:
        rows = state.references["windows"][first:last]
        for column,n in enumerate(_MA,4):
            _close(actual["ma"+str(n)]["value"],tuple(row[column] for row in rows))
        for name,column in (("middle",11),("upper",13),("lower",14)):
            _close(actual["boll"][name],tuple(row[column] for row in rows))
        for name,column in (("open",1),("close",1),("high",2),("low",3)):
            _close(actual["price"][name],tuple(row[column] for row in rows))
        assert actual["price"]["volume"] == (100.0,)*(last-first)
        assert actual["price"]["amount"] == (1000.0,)*(last-first)


def test_default_two_pages_and_shared_input(fourth_data):
    state = fourth_data
    with state.case("test_default_two_pages_and_shared_input"):
        first, service, source = state.run(_request(_default_calculations()))
        _compare(first,state,3000,4000,kdj=True,windows=True)
        assert first.kernel_version == "2.0.0" and source.batches == [1500] and source.open_calls == 1
        assert first.statistics.source_rows == 1500 and first.statistics.price_conversion_batches == 0
        assert service.warmups == [(500,False),(500,False)]
        assert source.description.selection.preceding_rows == 500
        assert not source.description.selection.reached_source_origin
        assert first.source.read_start == state.times[2500]
        assert sum(s.step_name=="rolling_mean" for s in service.observed_executor.statistics)==7
        previous, _, source = state.run(_request(_default_calculations(),before=first.times[0]))
        _compare(previous,state,2000,3000,kdj=True,windows=True)
        assert source.batches == [1500] and previous.statistics.source_rows == 1500
        assert previous.times[-1]<first.times[0] and not set(previous.times)&set(first.times)


def test_used_parameters_choose_dynamic_warmup(fourth_data):
    state = fourth_data
    with state.case("test_used_parameters_choose_dynamic_warmup"):
        calculations = tuple(CalculationInstance(label,"macd",dict(fast=f,slow=s,signal=g))
            for label,f,s,g in (("macd",12,26,9),("macd9",9,65,9),("macd10",10,69,10)))
        result, service, source = state.run(_request(calculations))
        for identity in ("macd","macd9","macd10"):
            _compare(result,state,3000,4000,macd=identity)
        assert service.warmups == [(500,False),(1163,False),(1235,False)]
        assert source.requirement.history.warmup_rows == 1235
        assert source.batches == [2235] and source.open_calls == 1
        assert result.statistics.source_rows == 2235


def test_1600_history_returns_1000_then_600_then_empty(fourth_data):
    state = fourth_data
    with state.case("test_1600_history_returns_1000_then_600_then_empty"):
        calculations = _default_calculations()
        first, _, source = state.run(_request(calculations),root="short")
        _compare(first,state,600,1600,kdj=True,windows=True)
        assert source.batches == [1500] and not source.description.selection.reached_source_origin
        oldest, _, source = state.run(_request(calculations,before=first.times[0]),root="short")
        _compare(oldest,state,0,600,kdj=True,windows=True)
        assert source.batches == [600] and source.description.selection.reached_source_origin
        assert _values(oldest)["macd"]["dif"][0] == _values(oldest)["macd"]["dea"][0] == _values(oldest)["macd"]["hist"][0] == 0.0
        assert _values(oldest)["ma20"]["value"][:19] == (None,)*19
        empty, _, source = state.run(_request(calculations,before=oldest.times[0]),root="short")
        assert empty.times == () and empty.range.count == 0 and empty.msg == "已经加载全部数据了"
        assert source.open_calls == 0 and empty.source.read_start is empty.source.read_end is None
        assert tuple(item.instance_id for item in empty.calculations) == tuple(item.instance_id for item in calculations)
        assert dict(empty.calculations[0].parameters) == {"fast":12,"slow":26,"signal":9}


def test_short_origin_is_allowed_when_required_warmup_exceeds_capacity(fourth_data):
    state = fourth_data
    with state.case("test_short_origin_is_allowed_when_required_warmup_exceeds_capacity"):
        selected = _request((CalculationInstance("macd10","macd",dict(fast=10,slow=69,signal=10)),))
        config = replace(state.config,goldenshare_lake_root=str(state.root/"short"),max_input_rows=1600)
        result, _, source = state.run(selected,config=config)
        _compare(result,state,600,1600,macd="macd10")
        assert source.batches == [1600] and source.description.selection.reached_source_origin
        # A literal internal handoff with an insufficient finite prefix must
        # fail before opening a price reader, rather than shorten R or B.
        from src.foundation.technical_indicators.sources.session import PriceInputSession
        description = replace(source.description,selection=replace(source.description.selection,reached_source_origin=False))
        inputs = PriceInputSession(SimpleNamespace(control=SimpleNamespace(config=config)),None,
            source.requirement,read_context=None)
        inputs.description = description
        with pytest.raises(ResourceLimitError):
            inputs._validate_selection()


def test_daily_files_are_combined_and_adjustment_basis_is_page_independent(fourth_data):
    state = fourth_data
    with state.case("test_daily_files_are_combined_and_adjustment_basis_is_page_independent"):
        calculations = (CalculationInstance("price","price",{}),CalculationInstance("ma20","ma",dict(period=20)))
        latest, _, source = state.run(_request(calculations,period="day",limit=11),root="daily")
        assert source.batches == [21] and latest.statistics.price_conversion_batches == 1
        earliest, _, source = state.run(_request(calculations,period="day",limit=10,before=latest.times[0]),root="daily")
        assert source.batches == [10] and earliest.statistics.price_conversion_batches == 1
        assert earliest.times+latest.times == tuple(date.fromisoformat(text) for text in DAILY_DATES)
        assert _values(earliest)["price"]["close"]+_values(latest)["price"]["close"] == (5.0,)*10+(6.0,)*11
        assert earliest.price_adjustment.basis_date == latest.price_adjustment.basis_date == date(2026,2,2)
        assert earliest.price_adjustment.basis_value == latest.price_adjustment.basis_value == 2.0
        combined = _values(earliest)["ma20"]["value"]+_values(latest)["ma20"]["value"]
        assert combined[:19] == (None,)*19
        _close(combined[19:],(5.5,5.55))


def test_period_keys_use_existing_time_semantics(fourth_data):
    import duckdb
    state = fourth_data
    with state.case("test_period_keys_use_existing_time_semantics"):
        root = state.root/"weekly"
        path = root/"silver/quote/stock_weekly/week_end=2026-10-23/part-000.parquet"
        path.parent.mkdir(parents=True)
        con = duckdb.connect(":memory:",config={"threads":1,"max_temp_directory_size":"0B"})
        try:
            for as_of,close in (("20261020",5.0),("20261021",6.0)):
                replacement = root/"current_week_replacement.parquet"
                assert state.query(con,"fixture_current_week","""COPY (SELECT '600000.SH'::VARCHAR ts_code,
                    '20261023'::VARCHAR trade_date,$asof::VARCHAR end_date,
                    10::DECIMAL(18,4) AS open,14::DECIMAL(18,4) AS high,8::DECIMAL(18,4) AS low,12::DECIMAL(18,4) AS close,
                    5::DECIMAL(18,4) open_qfq,7::DECIMAL(18,4) high_qfq,4::DECIMAL(18,4) low_qfq,$close::DECIMAL(18,4) close_qfq,
                    20::DECIMAL(18,4) open_hfq,28::DECIMAL(18,4) high_hfq,16::DECIMAL(18,4) low_hfq,24::DECIMAL(18,4) close_hfq,
                    12::DECIMAL(20,4) vol,34::DECIMAL(20,4) amount) TO $target (FORMAT PARQUET)""",rows=1,
                    bindings={"asof":as_of,"close":close,"target":str(replacement)}) == [(1,)]
                replacement.replace(path)
                state.input_rows += 1
                cutoff = date(2026,10,20) if as_of=="20261020" else date(2026,10,21)
                result, _, source = state.run(_request(period="week",end=cutoff),root="weekly")
                assert source.batches == [1] and result.times == (date(2026,10,19),)
                assert result.source_as_of == (cutoff,) and _values(result)["price"]["close"] == (close,)
            with pytest.raises(SourceUnsupportedError):
                state.run(_request(period="week",end=date(2026,10,20)),root="weekly")
            empty, _, source = state.run(_request(period="week",end=date(2026,9,1)),root="weekly")
            assert empty.times == () and empty.msg == "" and source.open_calls == 0
            assert dict(empty.calculations[0].parameters) == {} and empty.calculations[0].algorithm_version == "1.0.0"
        finally:
            con.close()


def test_warmup_control_and_selection_contracts(fourth_data,monkeypatch):
    state = fourth_data
    with state.case("test_warmup_control_and_selection_contracts"):
        # A valid identity K/D request resolves its window without price input.
        config = state.config
        control = D3Control(config)
        con = connect_private_memory_instance(config)
        from src.foundation.technical_indicators.executor import DuckDBExecutor
        from src.foundation.technical_indicators.contracts import normalize_request_and_validate_all_instances
        executor = DuckDBExecutor(con,control)
        selected = normalize_request_and_validate_all_instances(_request((CalculationInstance("kdj","kdj",dict(window=9,k_period=1,d_period=1)),)),config)
        registry = create_builtin_registry()
        engine = CalculationEngine(executor,registry.expand_dependencies(selected))
        try:
            engine.prepare()
            requirement = engine.resolve_history_requirement(config.max_input_rows)
            assert requirement.warmup_rows == requirement.preceding_rows == 8 and not requirement.requires_source_origin
            session = engine.sessions[engine.plan.instances[0][1]]
            original = executor.read_control_row
            for row,valid in (((8,False),True),((None,True),True),((None,False),False),((8,1),False)):
                with monkeypatch.context() as patch:
                    patch.setattr(executor,"read_control_row",lambda *args,**kwargs:row)
                    if valid:
                        assert session.read_control_row("read_warmup_rows") == row
                    else:
                        with pytest.raises(CalculationExecutionError):
                            session.read_control_row("read_warmup_rows")
            assert executor.read_control_row == original
            with pytest.raises(CalculationExecutionError):
                session.read_control_row("business_supplied_query")
            with pytest.raises(CalculationExecutionError):
                session.execute(SqlStep("business_supplied_file","SELECT 1",(),(),(),0))
            from src.foundation.technical_indicators.calculation.sql_templates import load_sql_templates
            class ReplacedFiles:
                SQL_PACKAGE = "src.foundation.technical_indicators.calculation"
                SQL_FILES = ("business_supplied.sql",)
            with pytest.raises(CalculationExecutionError):
                load_sql_templates(ReplacedFiles,request_texts={},control=control)
            with pytest.raises(CalculationExecutionError):
                session.drop_owned_table("ti_price_window")
        finally:
            control.stop_monitor()
            engine.close()
            state.sql_rows += executor.sql_processed_rows
            con.close()
            state.save()
        # Existing D3 invalid-coefficient literal: valid fast/signal must not
        # hide a slow component whose DOUBLE beta cannot be represented.
        with pytest.raises(RequestInvalidError):
            state.run(_request((CalculationInstance("macd","macd",dict(fast=12,slow=1152921504606846976,signal=9)),)),root="literal")
        assert state.calls[-1]["source_rows"] == 0 and state.calls[-1]["open_calls"] == 0


def test_locator_failure_and_cleanup_are_not_empty_success(fourth_data,monkeypatch):
    from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
    state = fourth_data
    with state.case("test_locator_failure_and_cleanup_are_not_empty_success"):
        selected = _request(period="day",adjustment="none",limit=4)
        normal, _, _ = state.run(selected,root="literal")
        assert normal.times == tuple(date.fromisoformat(text) for text in DAILY_DATES[:3])
        assert _values(normal)["price"]["close"] == (10.0,12.0,11.0)
        original_describe = LakePriceLocator.describe
        with monkeypatch.context() as patch:
            def stopped(self):
                result = original_describe(self)
                self.control.stopped = True
                return result
            patch.setattr(LakePriceLocator,"describe",stopped)
            with pytest.raises(CalculationCancelledError):
                state.run(selected,root="literal")
        original_count = LakePriceLocator._count_group
        with monkeypatch.context() as patch:
            def read_failed(self,*args):
                original_count(self,*args)
                raise SourceReadError("fourth-fix deliberate key-reader failure")
            patch.setattr(LakePriceLocator,"_count_group",read_failed)
            with pytest.raises(SourceReadError,match="key-reader"):
                state.run(selected,root="literal")
        original_close = CalculationEngine.close
        with monkeypatch.context() as patch:
            def close_failed(self):
                original_close(self)
                raise ResourceCleanupError("fourth-fix deliberate cleanup failure")
            patch.setattr(CalculationEngine,"close",close_failed)
            with pytest.raises(ResourceCleanupError,match="cleanup"):
                state.run(selected,root="literal",expected_cleanup_error=True)
        original_retain = OutputCollector._retain
        with monkeypatch.context() as patch:
            def lose_row(self,batch):
                original_retain(self,batch)
                self.executor.execute(SqlStep("fourth_fix_test_delete_tail_row",
                    "DELETE FROM ti_output_tail WHERE seq=(SELECT max(seq) FROM ti_output_tail)",
                    (),("ti_output_tail",),("ti_output_tail",),3))
                self._tail_rows = 2
            patch.setattr(OutputCollector,"_retain",lose_row)
            with pytest.raises(OutputContractError) as caught:
                state.run(selected,root="literal")
            assert (caught.value.reason,caught.value.stage) == ("fetch_count_mismatch","final_query")
            assert caught.value.diagnostics == {"expected_count":3,"actual_count":2}
            assert not any(step["name"]=="select_result" for step in state.calls[-1]["steps"])
        with monkeypatch.context() as patch:
            def lose_table(self,batch):
                original_retain(self,batch)
                self._drop("ti_output_tail")
                self._tail_rows = 0
            patch.setattr(OutputCollector,"_retain",lose_table)
            with pytest.raises(OutputContractError) as caught:
                state.run(selected,root="literal")
            assert (caught.value.reason,caught.value.stage) == ("fetch_count_mismatch","final_query")
            assert caught.value.diagnostics == {"expected_count":3,"actual_count":0}
        config = replace(state.config,goldenshare_lake_root=str(state.root/"literal"))
        source = _Source(config)
        source.selection_delta = 1
        with pytest.raises(SourceContractError) as caught:
            state.run(selected,config=config,source=source)
        assert caught.value.reason == "selection_count_mismatch"
        assert (caught.value.expected_count,caught.value.actual_count) == (4,3)
        assert not any(step["name"]=="count_tail" for step in state.calls[-1]["steps"])
