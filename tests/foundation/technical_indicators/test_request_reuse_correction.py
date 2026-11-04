"""LLD 24.6: the fixed, small source/collector correction checks.

Fixtures follow the producer's GOLD_CN_A_INDEX_MINS_SCHEMA,
SILVER_STOCK_DAILY_SCHEMA and SILVER_ADJ_FACTOR_SCHEMA in DG's
defs/run_contracts/asset_column_schemas.py, rechecked before construction.
Only timing/stop control is substituted. Arrow, Parquet, SQL and calculation
objects remain real; no prior test fixture or historical report is imported.
"""

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.config.settings import Settings
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation import sql_templates
from src.foundation.technical_indicators.calculation.engine import CalculationEngine
from src.foundation.technical_indicators.calculation.history import HistoryRequirement
from src.foundation.technical_indicators.calculation.indicators import create_builtin_registry
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import ResourceLimitError, SourceContractError
from src.foundation.technical_indicators.executor import DuckDBExecutor
from src.foundation.technical_indicators.service import connect_private_memory_instance
from src.foundation.technical_indicators.sources.contracts import (
    PriceReadSelection, ReadRequirement, SourceBatch, SourceDescription,
)
from src.foundation.technical_indicators.sources.read_context import SourceReadContext
from src.foundation.technical_indicators.sources.session import PriceInputSession


_DAY = date(2026, 1, 2)
_MINUTE_SCHEMA = pa.schema([
    ("ts_code", pa.string()), ("freq", pa.int32()), ("trade_date", pa.date32()),
    ("trade_time", pa.timestamp("us")),
    *((name, pa.float64()) for name in ("open", "high", "low", "close", "vol", "amount")),
    ("exchange", pa.string()), ("vwap", pa.float64()),
])
_DAILY_SCHEMA = pa.schema([
    ("ts_code", pa.string()), ("trade_date", pa.date32()),
    *((name, pa.float64()) for name in (
        "open", "high", "low", "close", "pre_close", "change_amount", "pct_chg", "vol", "amount")),
])
_FACTOR_SCHEMA = pa.schema([
    ("ts_code", pa.string()), ("trade_date", pa.date32()), ("adj_factor", pa.float64()),
])


class _Control:
    clock = staticmethod(monotonic)

    def __init__(self, config):
        self.config = config
        self.arrived_at = monotonic()
        self.cleanup_ready = False

    def check_active(self):
        pass

    def _note_sql_returned(self):
        pass


def _config(root, **changes):
    return replace(KernelConfig.from_settings(Settings(_env_file=None)),
                   goldenshare_lake_root=str(root), **changes)


@contextmanager
def _opened(config):
    control = _Control(config)
    connection = connect_private_memory_instance(config)
    executor = DuckDBExecutor(connection, control)
    try:
        yield connection, executor, control
    finally:
        control.cleanup_ready = True
        for name in tuple(executor._live_arrow):
            executor.cleanup_unregister(name)
        for name in tuple(executor._live_tables):
            executor.cleanup_drop(name)
        connection.close()


def _request(**changes):
    return CalculationRequest(**(dict(security_type="stock", ts_code="600000.SH", period="day",
        adjustment="none", calculations=(CalculationInstance("price", "price", {}),), limit=3) | changes))


def _history(fields=frozenset(("close",)), *, preceding=0, warmup=0):
    return HistoryRequirement(fields, preceding, warmup, False, (), "Existing positions")


def _write(path, rows, schema):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    return path


def _minute_rows(count):
    return [dict(ts_code="000001.SH", freq=1, trade_date=_DAY,
        trade_time=datetime(2026, 1, 2, 9, 31) + timedelta(minutes=i),
        open=float(i + 1), high=float(i + 1), low=float(i + 1), close=float(i + 1),
        vol=10.0, amount=100.0, exchange="SSE", vwap=float(i + 1)) for i in range(count)]


def _daily_row(code, day, close):
    return dict(ts_code=code, trade_date=day, open=close, high=close, low=close, close=close,
                pre_close=None, change_amount=None, pct_chg=None, vol=10.0, amount=100.0)


class _MemorySource:
    """Only the first check isolates source location; standard input/SQL stay real."""

    def __init__(self, delivered):
        self.columns = pa.RecordBatch.from_pylist(_minute_rows(delivered), schema=_MINUTE_SCHEMA)
        self.offset = self.eof_calls = 0

    def create_locator(self, executor, requirement, *, read_context):
        times = tuple(datetime(2026, 1, 2, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai"))
                      + timedelta(minutes=i) for i in range(6))
        description = SourceDescription(
            "literal_standard_minutes", "1", "none", None, None, None, "index_point", "share", "CNY",
            "Asia/Shanghai", "trade_time", "literal_origin", None, False, (("none", "none"),), False,
            PriceReadSelection(times[3], times[5], times[0], times[5], 3, 3, True, ()),
            source_projection=("trade_date", "trade_time", "close"),
            standard_projection=(("trade_date", 'CAST(b.trade_date AS DATE)'),
                                 ("trade_time", 'CAST(b.trade_time AS TIMESTAMP)'),
                                 ("close", 'CAST(b.close AS DOUBLE)')),
        )
        return SimpleNamespace(describe=lambda: description, close=lambda: None)

    def open(self, executor, description, requirement, *, read_context):
        source = self

        class Stream:
            def next_batch(self, max_rows):
                if source.offset == source.columns.num_rows:
                    source.eof_calls += 1
                    return None
                chunk = source.columns.slice(source.offset, max_rows)
                first = source.offset + 1
                source.offset += chunk.num_rows
                read_context.record_price_rows(chunk.num_rows)
                return SourceBatch(chunk, first, source.offset, chunk.num_rows, chunk.num_rows, 0, 0)

            def release_current_batch(self):
                pass

            def close(self):
                pass

        return Stream()


def test_reuses_tables_and_only_retains_intermediate_history(tmp_path):
    """Six literal closes, MA4: first valid outputs are 2.5, 3.5 and 4.5."""
    config = _config(tmp_path, batch_rows=2)
    request = _request(security_type="index", ts_code="000001.SH", period="1m",
                       calculations=(CalculationInstance("ma", "ma", {"period": 4}),))
    with _opened(config) as (connection, executor, control):
        registry = create_builtin_registry()
        plan = registry.expand_dependencies(request)
        engine = CalculationEngine(executor, plan)
        engine.prepare()
        history = engine.resolve_history_requirement(config.max_input_rows)
        source = _MemorySource(6)
        context = SourceReadContext(config)
        inputs = PriceInputSession(executor, source, ReadRequirement(request, history, 2, None, None),
                                   read_context=context)
        observed = []
        scalar = executor.scalar

        def observe(sql, bindings=()):
            observed.append(sql)
            return scalar(sql, bindings)

        executor.scalar = observe
        try:
            inputs.prepare()
            for index in range(3):
                batch = inputs.next_batch()
                assert batch.new_row_count == 2
                engine.consume(batch)
                output = engine.output_for(batch).instances[0][1]
                values = connection.execute(
                    f'SELECT value FROM "{output.table_name}" ORDER BY seq').fetchall()
                if index == 1:
                    assert values == [(None,), (2.5,)]
                elif index == 2:
                    assert values == [(3.5,), (4.5,)]
                inputs.retain_required_history()
                engine.release_batch_tables()
                inputs.finish_batch()
            assert inputs.next_batch() is None
            assert source.eof_calls == 1
            assert context.source_rows == 6
            assert sum(s.step_name == "retain_input_history" for s in executor.statistics) == 2
            assert sum(s.step_name == "input_window" for s in executor.statistics) == 2
            assert sum(s.step_name == "rename_table" for s in executor.statistics) == 6
            assert len([sql for sql in observed if "FROM ti_raw_new" in sql]) == 3
            assert all("count(" not in sql.lower() for sql in observed if "FROM ti_raw_new" in sql)
            assert "ti_history" not in inputs._tables
        finally:
            control.cleanup_ready = True
            engine.close()
            inputs.close()
            context.clear_request_metadata()

    # Two existing delivery faults: early EOF and an extra batch after the six
    # selected rows. Both use the same six-position source contract.
    for delivered in (4, 8):
        with _opened(config) as (_, executor, control):
            context = SourceReadContext(config)
            inputs = PriceInputSession(executor, _MemorySource(delivered),
                ReadRequirement(request, _history(preceding=3, warmup=3), 2, None, None),
                read_context=context)
            try:
                inputs.prepare()
                with pytest.raises(SourceContractError) as caught:
                    while (batch := inputs.next_batch()) is not None:
                        inputs.retain_required_history()
                        inputs.finish_batch()
                assert caught.value.reason == "selection_count_mismatch"
            finally:
                control.cleanup_ready = True
                inputs.close()
                context.clear_request_metadata()


def test_locator_stops_after_bounds_and_reuses_footer(tmp_path, monkeypatch):
    """Eight keys locate ranks two and three within the first four-key batch."""
    minute = _write(tmp_path / "gold/quote/major_index_mins/freq=1/trade_date=2026-01-02/part-000.parquet",
                    _minute_rows(8), _MINUTE_SCHEMA)
    opens = []
    original = pq.ParquetFile

    def counted(path, *args, **kwargs):
        opens.append(Path(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pq, "ParquetFile", counted)
    config = _config(tmp_path, batch_rows=4)
    request = _request(security_type="index", ts_code="000001.SH", period="1m", limit=6)
    with _opened(config) as (_, executor, control):
        context = SourceReadContext(config)
        source = LakeTechnicalIndicatorPriceSource(config)
        locator = source.create_locator(executor,
            ReadRequirement(request, _history(warmup=1), 4, None, None), read_context=context)
        try:
            description = locator.describe()
            assert description.selection.target_rows == 6
            assert description.selection.preceding_rows == 1
            assert description.selection.read_start.minute == 32
            assert description.selection.target_start.minute == 33
            assert context.locator_rows == 12
            assert opens.count(minute) == 1
            assert not locator._tables and not locator._registrations
            assert locator._reader is None
        finally:
            control.cleanup_ready = True
            locator.close()
            context.clear_request_metadata()

    dates = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7))
    paths = []
    for i, day in enumerate(dates):
        bad = i == 2
        schema = _DAILY_SCHEMA.set(_DAILY_SCHEMA.get_field_index("close"), pa.field("close", pa.string())) if bad else _DAILY_SCHEMA
        row = _daily_row("600001.SH" if bad else "600000.SH", day, 10.0)
        if bad:
            row["close"] = "unused"
        paths.append(_write(tmp_path / f"silver/quote/stock_daily/trade_date={day}/part-000.parquet", [row], schema))
    config = _config(tmp_path)
    request = _request(limit=1)
    with _opened(config) as (_, executor, control):
        source = LakeTechnicalIndicatorPriceSource(config)
        context = SourceReadContext(config)
        locator = source.create_locator(executor, ReadRequirement(request, _history(), config.batch_rows, None, None),
                                         read_context=context)
        try:
            description = locator.describe()
            assert description.price_paths == (paths[1],)
            assert description.selection.target_start == dates[1]
            assert opens.count(paths[1]) == opens.count(paths[2]) == 1
            assert paths[0] not in opens
        finally:
            control.cleanup_ready = True
            locator.close()
            context.clear_request_metadata()

    cause = MemoryError("selected metadata allocation")

    def fail_selected(self, groups):
        raise cause

    monkeypatch.setattr(LakePriceLocator, "_validate_selected_price_groups", fail_selected)
    with _opened(config) as (_, executor, control):
        context = SourceReadContext(config)
        locator = LakeTechnicalIndicatorPriceSource(config).create_locator(executor,
            ReadRequirement(request, _history(), config.batch_rows, None, None), read_context=context)
        try:
            with pytest.raises(ResourceLimitError) as caught:
                locator.describe()
            assert caught.value.__cause__ is cause
        finally:
            control.cleanup_ready = True
            locator.close()
            context.clear_request_metadata()


def test_reuses_source_templates_and_daily_factors(tmp_path, monkeypatch):
    """Two securities, three dates; latest basis remains outside the second range."""
    days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7))
    prices = ((10.0, 100.0), (20.0, 200.0), (30.0, 300.0))
    factors = ((1.0, 2.0), (2.0, 4.0), (4.0, 8.0))
    for i, day in enumerate(days):
        _write(tmp_path / f"silver/quote/stock_daily/trade_date={day}/part-000.parquet",
            [_daily_row(code, day, prices[i][j]) for j, code in enumerate(("600000.SH", "600001.SH"))],
            _DAILY_SCHEMA)
        _write(tmp_path / f"silver/quote/adj_factor/trade_date={day}/part-000.parquet",
            [dict(ts_code=code, trade_date=day, adj_factor=factors[i][j])
             for j, code in enumerate(("600000.SH", "600001.SH"))], _FACTOR_SCHEMA)
    loaded = []
    resource_files = sql_templates.files

    def observed_files(package):
        actual = resource_files(package)

        def joined(*parts):
            path = actual.joinpath(*parts)

            def read_text(*, encoding):
                loaded.append((package, parts[-1]))
                return path.read_text(encoding=encoding)

            return SimpleNamespace(read_text=read_text)

        return SimpleNamespace(joinpath=joined)

    monkeypatch.setattr(sql_templates, "files", observed_files)
    config = _config(tmp_path)
    source = LakeTechnicalIndicatorPriceSource(config)
    inspected = []
    inspect = source._inspect

    def inspect_once(path, *args, **kwargs):
        inspected.append(Path(path))
        return inspect(path, *args, **kwargs)

    monkeypatch.setattr(source, "_inspect", inspect_once)
    for code, end, expected in (
        ("600000.SH", days[2], [(2.5, 10.0, 100.0), (10.0, 10.0, 100.0), (30.0, 10.0, 100.0)]),
        ("600001.SH", days[1], [(25.0, 10.0, 100.0), (100.0, 10.0, 100.0)]),
    ):
        request = _request(ts_code=code, adjustment="qfq", end=end)
        context = SourceReadContext(config)
        start_loaded, start_inspected = len(loaded), len(inspected)
        with _opened(config) as (connection, executor, control):
            requirement = ReadRequirement(request, _history(frozenset(("close", "volume", "amount"))),
                                          config.batch_rows, None, end)
            inputs = PriceInputSession(executor, source, requirement, read_context=context)
            try:
                inputs.prepare()
                batch = inputs.next_batch()
                assert connection.execute(
                    f'SELECT close,volume,amount FROM "{batch.table_name}" ORDER BY seq').fetchall() == expected
                inputs.retain_required_history()
                inputs.finish_batch()
                assert inputs.next_batch() is None
                assert inputs.conversion_batches == 1
                assert inputs.resolved_description().basis_date == days[2]
                assert sorted(name for _, name in loaded[start_loaded:]) == ["adjust_price.sql", "stage_input.sql"]
                latest = tmp_path / f"silver/quote/adj_factor/trade_date={days[2]}/part-000.parquet"
                assert inspected[start_inspected:].count(latest) == 1
                assert len(inspected[start_inspected:]) == 3
            finally:
                control.cleanup_ready = True
                inputs.close()
                context.clear_request_metadata()
        assert not context._sql_texts and context._basis_row is None


def test_collector_only_saves_target_rows(tmp_path):
    """Two literal positions per period; final fetch may return short chunks."""
    from src.foundation.technical_indicators.calculation.calculation import (
        BatchCalculationOutputs, CalculationOutput, OutputField,
    )
    from src.foundation.technical_indicators.contracts import CalculationStatistics
    from src.foundation.technical_indicators.errors import OutputContractError, OutputReadError
    from src.foundation.technical_indicators.output.collector import OutputCollector
    from src.foundation.technical_indicators.output.contracts import OutputFieldDescription, OutputInstanceDescription
    from src.foundation.technical_indicators.sources.contracts import PriceBatch

    field = OutputField("value", "value", "DOUBLE", True, "Incomplete window is NULL")
    instances = (OutputInstanceDescription("ma", "ma", "1.0.0", (("period", 20),), (
        OutputFieldDescription("value", "DOUBLE", True, "Incomplete window is NULL"),
    )),)
    config = _config(tmp_path)

    def collect(period, fault=None, empty=False, before=False):
        minute = period.endswith("m")
        starts = ((datetime(2026, 1, 2, 9, 31), datetime(2026, 1, 2, 9, 32)) if minute else
                  (date(2026, 1, 5), date(2026, 1, 12)) if period == "week" else
                  (date(2026, 1, 1), date(2026, 2, 1)) if period == "month" else
                  (date(2026, 1, 5), date(2026, 1, 6)))
        ends = ((date(2026, 1, 9), date(2026, 1, 16)) if period == "week" else
                (date(2026, 1, 31), date(2026, 2, 28)) if period == "month" else starts)
        as_of = ((date(2026, 1, 6), date(2026, 1, 13)) if period == "week" else
                 (date(2026, 1, 2), date(2026, 2, 2)) if period == "month" else starts)
        start = date(2026, 1, 6) if period == "week" else None
        if fault == "date":
            start = date(2026, 2, 1)
        request = _request(period=period, limit=2, start=start,
            before=starts[0] if before and not minute else None,
            calculations=(CalculationInstance("ma", "ma", {"period": 20}),))
        time_fields = (("trade_date", "trade_time") if minute else
                       ("trade_date", "period_start", "period_end", "source_as_of"))
        description = SourceDescription(
            source_id="literal_output", contract_version="1", input_adjustment="none",
            basis_rule=None, basis_date=None, basis_value=None, price_unit="CNY",
            volume_unit="lot", amount_unit="thousand_CNY", timezone="Asia/Shanghai",
            period_label_rule="trade_time" if minute else "period_start",
            history_origin_rule="literal_origin", available_through=None,
            supports_partial_period=period in ("week", "month"),
            supported_adjustment_paths=(("none", "none"),), converted=False,
            selection=(PriceReadSelection(None, None, None, None, 0, 0, True, ()) if empty else
                       PriceReadSelection(starts[0], starts[1], starts[0], starts[1], 2, 0, True, ())),
        )
        # The same two monthly rows include one warmup row and one target row.
        # Other periods retain both rows to cover CTAS followed by INSERT.
        warmup = int(period == "month" and not empty)
        target_rows = 0 if empty else 2 - warmup
        with _opened(config) as (connection, executor, control):
            collector = OutputCollector(executor=executor, request=request, instances=instances,
                target_first_seq=1 + warmup, target_rows=target_rows)
            try:
                if not empty:
                    for index, position in enumerate(starts, 1):
                        connection.execute('DROP TABLE IF EXISTS ti_literal_price')
                        connection.execute('DROP TABLE IF EXISTS ti_literal_value')
                        time_ddl = ', '.join(f'{name} {"TIMESTAMP" if name == "trade_time" else "DATE"}'
                                             for name in time_fields)
                        connection.execute(f'CREATE TEMP TABLE ti_literal_price(seq BIGINT,{time_ddl},close DOUBLE)')
                        dates = ((position.date(), position) if minute else
                                 (position, position, ends[index-1], as_of[index-1]))
                        connection.execute('INSERT INTO ti_literal_price VALUES ('+
                            ','.join('?' for _ in range(2+len(dates)))+')', (index, *dates, float(index)))
                        if fault != "table":
                            column = "other DOUBLE" if fault == "field" else "value VARCHAR" if fault == "type" else "value DOUBLE"
                            connection.execute(f'CREATE TEMP TABLE ti_literal_value(seq BIGINT,{column})')
                            connection.execute('INSERT INTO ti_literal_value VALUES (?,?)',
                                (index, "wrong" if fault == "type" else None if index == 1 else 2.0))
                        batch = PriceBatch(
                            table_name="ti_literal_price", new_first_seq=index, new_last_seq=index,
                            new_row_count=1, history_rows=0, time_fields=time_fields,
                            fields=("close",), adjustment="none",
                        )
                        output = CalculationOutput("ti_literal_value", (field,), index, index)
                        collector.append_new_rows(BatchCalculationOutputs(batch, (("ma", output),)))
                        if warmup and index == 1:
                            assert not collector._tables
                            assert not any(item.step_name == "merge_batch" for item in executor.statistics)
                    if fault == "short":
                        connection.execute('DELETE FROM ti_output_tail WHERE seq=2')
                    elif fault == "extra":
                        connection.execute('INSERT INTO ti_output_tail SELECT * FROM ti_output_tail WHERE seq=2')

                reads = []

                class ShortCursor:
                    def __init__(self, cursor):
                        self.cursor = cursor
                        self.description = cursor.description

                    def fetchmany(self, count):
                        rows = self.cursor.fetchmany(min(count, 1))
                        reads.append(len(rows))
                        return rows

                class Connection:
                    def execute(self, sql, bindings=()):
                        cursor = connection.execute(sql, bindings)
                        if 'FROM "ti_output_tail" ORDER BY seq ASC' in sql:
                            return ShortCursor(cursor)
                        return cursor

                    def __getattr__(self, name):
                        return getattr(connection, name)

                executor.connection = Connection()
                stats = CalculationStatistics(0 if empty else 2, 0, 0, 0, 0, 0, 0.0)
                result = collector.build_result(description, stats,
                    read_start=None if empty else starts[0], read_end=None if empty else starts[1])
                assert result.msg == "" and result.range.count == target_rows
                assert dict(result.calculations[0].fields)["value"] == (() if empty else (None, 2.0)[warmup:])
                assert result.times == (() if empty else tuple(
                    value.replace(tzinfo=ZoneInfo("Asia/Shanghai")) if minute else value for value in starts[warmup:]))
                if period in ("week", "month"):
                    assert result.source_as_of == (() if empty else as_of[warmup:])
                else:
                    assert result.source_as_of is None
                selections = [item for item in executor.statistics if item.step_name == "select_result"]
                assert len(selections) == (0 if empty else 1)
                assert not any(item.step_name in ("retain_tail", "count_tail") for item in executor.statistics)
                if empty:
                    assert not collector._tables and reads == []
                else:
                    assert reads == [1] * target_rows + [0]
                    assert len([item for item in executor.statistics if item.step_name == "merge_batch"]) == target_rows
                    assert collector._result_columns == (("trade_time", "value_0_0") if minute else
                        ("period_start", "source_as_of", "value_0_0") if period in ("week", "month") else
                        ("period_start", "value_0_0"))
            finally:
                control.cleanup_ready = True
                collector.discard()

    for period in ("1m", "day", "week", "month"):
        collect(period)
    collect("day", empty=True)
    collect("day", empty=True, before=True)
    for fault, error, reason in (
        ("short", OutputContractError, "fetch_count_mismatch"),
        ("extra", OutputContractError, "fetch_count_mismatch"),
        ("table", OutputReadError, "query_failed"),
        ("field", OutputContractError, "missing_fields"),
        ("type", OutputContractError, "type_mismatch"),
        ("date", OutputContractError, "missing_rows"),
    ):
        with pytest.raises(error) as caught:
            collect("day", fault=fault)
        assert caught.value.reason == reason
