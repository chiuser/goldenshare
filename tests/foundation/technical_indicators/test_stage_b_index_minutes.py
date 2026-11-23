"""Index minute read cases based on the verified Gold and Prod physical layouts."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from time import monotonic
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.calculation.engine import CalculationEngine
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.configuration.datasets import DATASET_LOCATIONS
from goldenshare_technical_indicators.errors import (
    ResourceLimitError, SourceContractError, SourceReadError, SourceUnsupportedError,
)
from goldenshare_technical_indicators.execution_control import ExecutionControl
from goldenshare_technical_indicators.request_parser import _build_read_requirement
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from goldenshare_technical_indicators.sources.read_context import SourceReadContext
from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
from src.foundation.clients.local_lake.technical_indicator_price_source import (
    LakeTechnicalIndicatorPriceSource, _LakePriceStream,
)
from src.foundation.clients.technical_indicator_postgres import _minute_price_column, _price_scope
from src.foundation.config.settings import Settings, technical_indicator_config_from_settings


SHANGHAI = ZoneInfo("Asia/Shanghai")
PRICE = {"calculation_id": "price", "parameters": {}}
MA2 = {"calculation_id": "ma", "parameters": {"period": 2}}
SH, SZ = "000001.SH", "399001.SZ"
FIELDS = ("open", "high", "low", "close", "vol", "amount")


def _time(minute):
    return datetime(2026, 11, 17, 9, minute, tzinfo=SHANGHAI)


def _setup(root, backend, first, last, *, code=SH, limit=2, prewarm=False):
    locations = deepcopy(DATASET_LOCATIONS)
    locations["index_mins_5m"][backend]["enabled_adjustments"] = ("none",)
    config = technical_indicator_config_from_settings(Settings(
        _env_file=None, GOLDENSHARE_LAKE_ROOT=str(root), TECHNICAL_INDICATOR_BATCH_ROWS=1,
        TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS=limit,
    ), data_location=backend, dataset_locations=locations)
    request = CalculationRequest(
        security_type="index", ts_code=code, period="5m", adjustment="none",
        start=_time(first), end=_time(last), calculations=(PRICE, MA2) if prewarm else (PRICE,),
    )
    return config, request


def _write_gold(root, code, minutes, *, day=17, hour=9, close=105):
    # Gold schema from the formal 2026-11-17 Parquet. Values are synthetic.
    path = root / f"gold/quote/index_mins/freq=5/trade_date=2026-11-{day:02}/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([
        ("ts_code", pa.string()), ("freq", pa.int32()), ("trade_date", pa.date32()), ("trade_time", pa.timestamp("us")),
        *((name, pa.float64()) for name in FIELDS),
    ])
    stamps = (datetime(2026, 11, day, hour, minute) for minute in minutes)
    rows = [dict(ts_code=code, freq=5, trade_date=stamp.date(), trade_time=stamp,
                 open=100, high=110, low=95, close=close, vol=7, amount=250) for stamp in stamps]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, row_group_size=1)
    return path


@contextmanager
def _dg(root, first, last, **kwargs):
    config, request = _setup(root, "dg", first, last, **kwargs)
    service = TechnicalIndicatorService(config=config, source=LakeTechnicalIndicatorPriceSource(config),
                                        registry=create_builtin_registry())
    prepared = service._prepare_calculation(request)
    context = SourceReadContext(config)
    control = ExecutionControl(arrived_at=monotonic(), config=config)
    connection, executor = service._open_execution(control)
    engine = CalculationEngine(executor, prepared.plan)
    inputs = None
    try:
        inputs = service._build_input_session(prepared, engine, executor, context)
        inputs.prepare()
        yield inputs, connection, context
    finally:
        assert not service._close_execution(control, connection, engine=engine, inputs=inputs)


def _batches(inputs, connection):
    result = []
    while inputs.next_batch() is not None:
        result.append(connection.execute(
            "SELECT trade_time, volume, amount FROM ti_price_window ORDER BY seq"
        ).fetchall())
        inputs.retain_required_history()
        inputs.finish_batch()
    return result


@pytest.mark.parametrize(("code", "volume"), ((SH, 700), (SZ, 7)))
def test_dg_uses_gold_opening_and_keeps_normal_minute_gap(tmp_path, code, volume):
    _write_gold(tmp_path, code, (35, 45))
    with _dg(tmp_path, 35, 45, code=code) as (inputs, connection, ctx):
        desc = inputs.resolved_description()
        assert (desc.selection.target_start, desc.selection.target_end) == (_time(35), _time(45))
        assert (desc.price_unit, desc.volume_unit, desc.amount_unit) == ("index_point", "share", "CNY")
        assert _batches(inputs, connection) == [[(_time(35).replace(tzinfo=None), volume, 250)],
                                                [(_time(45).replace(tzinfo=None), volume, 250)]]
        assert ctx.source_rows == 2
    with pytest.raises(ResourceLimitError, match="max_output_rows"):
        with _dg(tmp_path, 35, 45, code=code, limit=1):
            pytest.fail("Two business positions must exceed a one-position limit")


def test_dg_uses_0935_in_warmup_and_reports_empty_through_0930(tmp_path):
    _write_gold(tmp_path, SH, (35, 40, 45))
    with _dg(tmp_path, 40, 45, prewarm=True) as (inputs, connection, ctx):
        selection = inputs.resolved_description().selection
        assert (selection.read_start, selection.target_start, selection.preceding_rows) == (_time(35), _time(40), 1)
        windows = _batches(inputs, connection)
        assert [len(window) for window in windows] == [1, 2, 2]
        assert ctx.source_rows == 3
    with pytest.raises(SourceReadError) as error:
        with _dg(tmp_path, 30, 30):
            pytest.fail("Gold does not return an auction as a business bar")
    assert error.value.detail == "数据缺失"


def test_dg_reuses_selected_minutes_and_the_previous_days_last_bar(tmp_path, monkeypatch):
    _write_gold(tmp_path, SH, (0,), day=13, hour=15)
    # Different closes demonstrate that the first MA value uses the earlier day.
    previous = _write_gold(tmp_path, SH, (55,), day=16, hour=14, close=101)
    current = _write_gold(tmp_path, SH, (35, 40, 45))
    reads = []
    read = LakePriceLocator._read_rows

    def record(locator, sql, bindings, **kwargs):
        if "read_parquet" in sql:
            reads.append(bindings[0])
        return read(locator, sql, bindings, **kwargs)

    def fail_reopen(*args):
        pytest.fail("The minute stream must use the already selected price rows")

    monkeypatch.setattr(LakePriceLocator, "_read_rows", record)
    monkeypatch.setattr(_LakePriceStream, "_open_file", fail_reopen)
    config, request = _setup(tmp_path, "dg", 35, 40, prewarm=True)
    service = TechnicalIndicatorService(config=config, source=LakeTechnicalIndicatorPriceSource(config),
                                        registry=create_builtin_registry())
    result = service.calculate(request)

    assert result.times == (_time(35), _time(40))
    assert result.source.read_start == datetime(2026, 11, 16, 14, 55, tzinfo=SHANGHAI)
    assert result.calculations[1].fields == (("value", (103.0, 105.0)),)
    assert result.statistics.source_rows == 3
    assert reads == [str(current), str(previous)]


def test_dg_rejects_duplicate_and_unverified_index(tmp_path):
    _write_gold(tmp_path, SH, (35, 35))
    with pytest.raises(SourceContractError, match="overlap"):
        with _dg(tmp_path, 35, 45):
            pytest.fail("Duplicate timestamps are not missing-minute gaps")
    with pytest.raises(SourceUnsupportedError):
        with _dg(tmp_path, 35, 45, code="000002.SH"):
            pytest.fail("The volume unit has not been verified for this index")


@pytest.mark.parametrize(("minutes", "expected"), (
    ((30, 35, 45), [(35, 90, 102, 90, 100, 14, 36), (45, 100, 102, 96, 100, 8, 30)]),
    ((35, 45), [(45, 100, 102, 96, 100, 8, 30)]),
    ((30, 45), [(45, 100, 102, 96, 100, 8, 30)]),
))
def test_prod_sql_uses_matching_auction_even_before_lower_bound(tmp_path, minutes, expected):
    # Verify the expression with an isolated SQL fixture. The real Prod
    # index lookup, cursor and PostgreSQL types are exercised by the smoke audit.
    config, request = _setup(tmp_path, "prod_pg", 35, 45)
    control = ExecutionControl(arrived_at=monotonic(), config=config)
    service = TechnicalIndicatorService(config=config, source=None, registry=create_builtin_registry())
    prepared = service._prepare_calculation(request)
    connection, executor = service._open_execution(control)
    engine = CalculationEngine(executor, prepared.plan)
    try:
        engine.prepare()
        history = engine.resolve_history_requirement(config.max_input_rows)
        requirement = _build_read_requirement(prepared, history, batch_rows=1)
        relation, filters, identity = _price_scope(requirement, requested_columns=FIELDS)
        connection.execute("CREATE SCHEMA core_serving")
        connection.execute("""
            CREATE TABLE core_serving.index_minute_bar(
                ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, vol DOUBLE, amount DOUBLE,
                PRIMARY KEY(ts_code, freq, trade_time)
            )
        """)
        base = {
            30: (97, 98, 89, 90, 6, 6),
            35: (100, 102, 96, 100, 8, 30),
            45: (100, 102, 96, 100, 8, 30),
        }
        rows = [(SH, "5min", _time(minute).replace(tzinfo=None), *base[minute]) for minute in minutes]
        # An auction for a different index or frequency cannot fill a missing match.
        rows.extend(((SZ, "5min", _time(30).replace(tzinfo=None), *base[30]),
                     (SH, "15min", _time(30).replace(tzinfo=None), *base[30])))
        connection.executemany("INSERT INTO core_serving.index_minute_bar VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        columns = ", ".join(map(_minute_price_column, FIELDS))
        sql = (f"SELECT minute(b.trade_time), {columns} FROM {relation} WHERE {filters} "
               f"AND b.trade_time BETWEEN %s AND %s ORDER BY b.trade_time")
        bounds = (_time(35).replace(tzinfo=None), _time(45).replace(tzinfo=None))
        assert connection.execute(sql.replace("%s", "?"), (*identity, *bounds)).fetchall() == expected
    finally:
        assert not service._close_execution(control, connection, engine=engine)
