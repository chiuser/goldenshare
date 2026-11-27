"""Exercise the DG index-minute request from market-data selection to indicator output."""

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.errors import ResourceLimitError, SourceUnsupportedError
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from src.app.runtime.technical_indicators.composition import build_runtime_config
from src.foundation.clients.local_lake.major_index_mins_contract import MAX_INDEX_MINUTE_LIMIT
from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
from src.foundation.clients.local_lake.technical_indicator_price_source import (
    LakeTechnicalIndicatorPriceSource, _LakePriceStream,
)
from src.foundation.config.settings import Settings


SHANGHAI = ZoneInfo("Asia/Shanghai")
PRICE = {"calculation_id": "price", "parameters": {}}
MA2 = {"calculation_id": "ma", "parameters": {"period": 2}}
NINE_TURN = {"calculation_id": "nineturn", "parameters": {}}


def _service(root, environment="local", *, enable_index_minute_nine_turn=False):
    config = build_runtime_config(Settings(
        _env_file=None, APP_ENV=environment, GOLDENSHARE_LAKE_ROOT=str(root),
    ))
    return TechnicalIndicatorService(
        config=config, source=LakeTechnicalIndicatorPriceSource(config),
        registry=create_builtin_registry(enable_index_minute_nine_turn=enable_index_minute_nine_turn),
    )


def _request(freq, end, *, code="000001.SH", count=2, start=None):
    return CalculationRequest(
        security_type="index", ts_code=code, period=f"{freq}m", adjustment="none",
        start=start, end=end, latest_rows=count, calculations=(PRICE, MA2),
    )


def _minute(day, h, m):
    return datetime(2026, 11, day, h, m, tzinfo=SHANGHAI)


def _write_minutes(root, freq, day, bars):
    # Field types follow the confirmed formal DG major-index Gold Parquet contract.
    # Prices and quantities are chosen to make the expected MA and conversion independent.
    path = root / f"gold/quote/major_index_mins/freq={freq}/trade_date=2026-11-{day:02}/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([
        ("ts_code", pa.string()), ("freq", pa.int32()), ("trade_date", pa.date32()),
        ("trade_time", pa.timestamp("us")),
        *((field, pa.float64()) for field in ("open", "high", "low", "close", "vol", "amount")),
        ("exchange", pa.string()), ("vwap", pa.float64()),
    ])
    pq.write_table(pa.Table.from_pylist([
        dict(ts_code=code, freq=freq, trade_date=stamp.date(), trade_time=stamp.replace(tzinfo=None),
             open=close, high=close + 2, low=close - 2, close=close, vol=volume,
             amount=9000, exchange="XSHG" if code.endswith(".SH") else "XSHE", vwap=None)
        for code, stamp, close, volume in bars
    ], schema=schema), path)
    return path


@pytest.mark.parametrize(("freq", "h", "m"), ((1, 9, 30), (5, 9, 35), (15, 9, 45), (30, 10, 0), (60, 10, 30)))
@pytest.mark.parametrize("day", (10, 25))
def test_recent_minute_warmup_keeps_stored_shares_across_dates(tmp_path, freq, h, m, day):
    old, previous, end = _minute(day - 1, 14, 0), _minute(day - 1, 15, 0), _minute(day, h, m)
    codes = ("000001.SH", "399001.SZ")
    _write_minutes(tmp_path, freq, day - 1, [
        row for code in codes for row in ((code, old, 100, 1000), (code, previous, 104, 1200))
    ])
    _write_minutes(tmp_path, freq, day, [(code, end, 110, 15) for code in codes])
    service = _service(tmp_path)
    for code, exchange in ((codes[0], "XSHG"), (codes[1], "XSHE")):
        page = service.calculate_index_minutes_recent(_request(freq, end, code=code), output_limit=MAX_INDEX_MINUTE_LIMIT)
        assert page.result.times == (previous, end)
        assert dict(page.result.calculations[0].fields)["volume"] == (1200, 15)
        assert dict(page.result.calculations[0].fields)["amount"] == (9000, 9000)
        assert dict(page.result.calculations[1].fields)["value"] == (102, 107)
        assert page.selection.read_start == old and page.selection.preceding_rows == 1
        assert page.source_facts.has_more and page.source_facts.target_exchanges == (exchange, exchange)
        assert page.result.statistics.source_files == 2


def test_recent_minute_reads_multiple_files_in_one_sql_and_keeps_start_for_targets_only(tmp_path, monkeypatch):
    code = "000001.SH"
    session_times = ((10, 30), (11, 30), (14, 0), (15, 0))
    previous = _write_minutes(tmp_path, 60, 9, [
        (code, _minute(9, h, m), 100 + offset, 1000) for offset, (h, m) in enumerate(session_times)
    ])
    current = _write_minutes(tmp_path, 60, 10, [
        (code, _minute(10, h, m), 104 + offset, 10) for offset, (h, m) in enumerate(session_times)
    ])
    reads = []
    read = LakePriceLocator._read_rows

    def record(locator, sql, bindings, **kwargs):
        if "read_parquet" in sql:
            reads.append(bindings[0])
        return read(locator, sql, bindings, **kwargs)

    def fail_reopen(*args):
        pytest.fail("The calculation must consume the retained minute rows")

    monkeypatch.setattr(LakePriceLocator, "_read_rows", record)
    monkeypatch.setattr(_LakePriceStream, "_open_file", fail_reopen)
    service = _service(tmp_path)
    end = _minute(10, 15, 0)
    page = service.calculate_index_minutes_recent(_request(60, end, count=5), output_limit=MAX_INDEX_MINUTE_LIMIT)
    assert reads == [[str(previous), str(current)]]
    assert page.result.times == (_minute(9, 15, 0), *(_minute(10, h, m) for h, m in session_times))
    assert page.result.statistics.locator_rows == 6
    assert page.source_facts.has_more

    page = service.calculate_index_minutes_recent(
        _request(60, end, count=5, start=_minute(10, 0, 0)), output_limit=MAX_INDEX_MINUTE_LIMIT,
    )
    assert len(page.result.times) == 4 and page.selection.read_start == _minute(9, 15, 0)
    assert dict(page.result.calculations[1].fields)["value"][0] == 103.5
    assert not page.source_facts.has_more


def test_recent_minute_limit_and_dataset_are_scoped_to_dg(tmp_path):
    end = _minute(10, 9, 35)
    _write_minutes(tmp_path, 5, 10, [("000001.SH", end, 110, 15)])
    service = _service(tmp_path)
    request = _request(5, end, count=501)
    page = service.calculate_index_minutes_recent(request, output_limit=MAX_INDEX_MINUTE_LIMIT)
    assert page.result.times == (end,)
    assert not page.source_facts.has_more
    empty = service.calculate_index_minutes_recent(
        replace(request, end=_minute(9, 15, 0)), output_limit=MAX_INDEX_MINUTE_LIMIT,
    )
    assert empty.result is None and not empty.source_facts.has_more
    with pytest.raises(ResourceLimitError):
        service.calculate_with_source(request)
    with pytest.raises(ResourceLimitError):
        service.calculate_index_minutes_recent(
            replace(request, latest_rows=MAX_INDEX_MINUTE_LIMIT + 1), output_limit=MAX_INDEX_MINUTE_LIMIT,
        )
    with pytest.raises(SourceUnsupportedError):
        _service(tmp_path, "prod").calculate_index_minutes_recent(request, output_limit=MAX_INDEX_MINUTE_LIMIT)
    legacy = service.parser.parse(replace(request, start=end, latest_rows=None))
    assert legacy.target.dataset_id == "index_mins_5m"


def test_recent_minute_nine_turn_uses_prewarm_and_shares_the_chart_read(tmp_path, monkeypatch):
    # 17 rising closes, then an equal comparison and three down comparisons.
    closes = (*range(100, 117), 113, 90, 89, 88)
    times = tuple(_minute(10, 9, 35) + timedelta(minutes=5 * offset) for offset in range(len(closes)))
    price_file = _write_minutes(tmp_path, 5, 10, [
        ("000001.SH", time, close, 10) for time, close in zip(times, closes, strict=True)
    ])
    reads = []
    original_read = LakePriceLocator._read_rows

    def record(locator, sql, bindings, **kwargs):
        if "read_parquet" in sql:
            reads.append(bindings[0])
        return original_read(locator, sql, bindings, **kwargs)

    monkeypatch.setattr(LakePriceLocator, "_read_rows", record)
    service = _service(tmp_path, enable_index_minute_nine_turn=True)
    request = _request(5, times[-1], count=5, start=times[-5])
    for calculations in ((NINE_TURN,), (*request.calculations, NINE_TURN)):
        reads.clear()
        page = service.calculate_index_minutes_recent(
            replace(request, calculations=calculations), output_limit=MAX_INDEX_MINUTE_LIMIT,
        )
        assert reads == [[str(price_file)]]
        assert page.selection.preceding_rows == 16
        assert page.result.times == times[-5:]
        assert dict(page.result.calculations[-1].fields) == {
            "up_count": (13, 0, 0, 0, 0),
            "down_count": (0, 0, 1, 2, 3),
        }


def _write_silver_minutes(root, freq, day, slots):
    # Silver has VARCHAR freq and derives trade_date from the local trade_time.
    path = root / f"silver/quote/major_index_mins/freq={freq}min/trade_date=2026-11-{day:02}/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([
        ("ts_code", pa.string()), ("freq", pa.string()), ("trade_time", pa.timestamp("us")),
        *((field, pa.float64()) for field in ("open", "high", "low", "close", "vol", "amount")),
        ("exchange", pa.string()), ("vwap", pa.float64()),
    ])
    pq.write_table(pa.Table.from_pylist([
        dict(ts_code="000001.SH", freq=f"{freq}min", trade_time=_minute(day, h, m).replace(tzinfo=None),
             open=price, high=99 if (h, m) == (9, 30) else price + 3,
             low=1 if (h, m) == (9, 30) else price - 2,
             close=price + 1, vol=10, amount=100, exchange="XSHG", vwap=None)
        for h, m, price in slots
    ], schema=schema), path)
    return path


@pytest.mark.parametrize(("freq", "base", "slot_count", "current_slots"), (
    (90, 30, 4, ((11, 0), (14, 0), (15, 0))),
    (120, 60, 3, ((11, 30), (15, 0))),
))
@pytest.mark.parametrize("day", (10, 25))
def test_derived_minutes_reuse_selection_and_sum_stored_shares(
    tmp_path, monkeypatch, freq, base, slot_count, current_slots, day,
):
    prices = ((9, 30, 9), (10, 30, 25), (11, 30, 40), (14, 0, 55), (15, 0, 65))
    if base == 30:
        prices += ((10, 0, 20), (11, 0, 31), (13, 30, 50), (14, 30, 60))
    previous = _write_silver_minutes(tmp_path, base, day - 1, prices)
    current = _write_silver_minutes(tmp_path, base, day, prices)
    reads = []
    read = LakePriceLocator._read_rows

    def record(locator, sql, bindings, **kwargs):
        if "read_parquet" in sql:
            reads.append(bindings[0])
        return read(locator, sql, bindings, **kwargs)

    monkeypatch.setattr(LakePriceLocator, "_read_rows", record)
    request = _request(freq, _minute(day, 15, 0), count=len(current_slots) + 1)
    result = _service(tmp_path).calculate_index_minutes_recent(request, output_limit=MAX_INDEX_MINUTE_LIMIT)
    assert reads == [[str(previous), str(current)]]
    assert result.result.times == (_minute(day - 1, 15, 0), *(_minute(day, h, m) for h, m in current_slots))
    assert result.selection.preceding_rows == 1 and result.source_facts.has_more
    assert result.source_facts.target_exchanges == ("XSHG",) * len(result.result.times)
    fields = dict(result.result.calculations[0].fields)
    assert fields["volume"][:2] == (20, slot_count * 10)
    assert fields["amount"][:2] == (200, slot_count * 100)
    assert fields["open"][1] == fields["low"][1] == 10
    assert fields["high"][1] == (34 if freq == 90 else 43)
    morning_close = 32 if freq == 90 else 41
    assert fields["close"][1] == morning_close
    assert dict(result.result.calculations[1].fields)["value"][1] == (66 + morning_close) / 2


@pytest.mark.parametrize(("freq", "base", "morning"), ((90, 30, (11, 0)), (120, 60, (11, 30))))
def test_derived_minutes_use_available_rows_of_completed_windows(tmp_path, freq, base, morning):
    _write_silver_minutes(tmp_path, base, 9, ((9, 30, 9),))
    _write_silver_minutes(tmp_path, base, 10, ((10, 30, 25), (14, 0, 55)))
    service = _service(tmp_path)
    request = _request(freq, _minute(10, 13, 40))
    page = service.calculate_index_minutes_recent(request, output_limit=MAX_INDEX_MINUTE_LIMIT)
    assert page.result.times == (_minute(10, *morning),)
    assert dict(page.result.calculations[0].fields) == {
        "open": (25,), "high": (28,), "low": (23,), "close": (26,), "volume": (10,), "amount": (100,),
    }
    assert page.selection.preceding_rows == 0 and not page.source_facts.has_more
    empty = service.calculate_index_minutes_recent(
        replace(request, end=_minute(10, 10, 45)), output_limit=MAX_INDEX_MINUTE_LIMIT,
    )
    assert empty.result is None
    with pytest.raises(SourceUnsupportedError):
        _service(tmp_path, "prod").calculate_index_minutes_recent(request, output_limit=MAX_INDEX_MINUTE_LIMIT)


@pytest.mark.parametrize(("freq", "base", "target_times", "closes", "up", "down"), (
    (90, 30, ((11, 0), (14, 0), (15, 0)), (42, 66, 76), (0, 1, 2), (1, 0, 0)),
    (120, 60, ((11, 30), (15, 0)), (51, 76), (1, 2), (0, 0)),
))
def test_index_minute_nine_turn_compares_derived_window_closes(tmp_path, freq, base, target_times, closes, up, down):
    # The two earlier days repeat. The last day's base prices are all ten points higher.
    slots = ((9, 30, 9), (10, 30, 25), (11, 30, 40), (14, 0, 55), (15, 0, 65))
    if base == 30:
        slots += ((10, 0, 20), (11, 0, 31), (13, 30, 50), (14, 30, 60))
    for day in (6, 9, 10):
        increase = 10 if day == 10 else 0
        _write_silver_minutes(tmp_path, base, day, tuple((h, m, price + increase) for h, m, price in slots))

    service = _service(tmp_path, enable_index_minute_nine_turn=True)
    request = replace(_request(freq, _minute(10, 15, 0), count=len(target_times)), calculations=(PRICE, NINE_TURN))
    page = service.calculate_index_minutes_recent(request, output_limit=MAX_INDEX_MINUTE_LIMIT)
    assert page.result.times == tuple(_minute(10, h, m) for h, m in target_times)
    assert dict(page.result.calculations[0].fields)["close"] == closes
    assert dict(page.result.calculations[1].fields) == {"up_count": up, "down_count": down}
