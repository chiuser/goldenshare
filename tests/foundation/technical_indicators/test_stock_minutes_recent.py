"""Exercise the stock minute path with the producer's Silver Parquet schema."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.configuration.datasets import DATASET_LOCATIONS, DG_RECENT_STOCK_MINUTE_DATASETS
from goldenshare_technical_indicators.errors import (
    CalculationUnsupportedError, ResourceLimitError, SourceContractError, SourceUnsupportedError,
)
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
from src.foundation.clients.local_lake.technical_indicator_price_source import (
    LakeTechnicalIndicatorPriceSource, _LakePriceStream,
)
from src.foundation.config.settings import Settings, technical_indicator_config_from_settings


SHANGHAI = ZoneInfo("Asia/Shanghai")
CODE = "600519.SH"
PRICE = {"calculation_id": "price", "parameters": {}}
MACD = {"calculation_id": "macd", "parameters": {"fast": 12, "slow": 26, "signal": 9}}
KDJ = {"calculation_id": "kdj", "parameters": {}}
NINE = {"calculation_id": "nineturn", "parameters": {}}
REGULAR_30 = ((10, 0), (10, 30), (11, 0), (11, 30), (13, 30), (14, 0), (14, 30), (15, 0))


def minute(day, h, m):
    return datetime(2026, 11, day, h, m, tzinfo=SHANGHAI)


def _write_minutes(root, freq, day, bars):
    path = root / f"silver/quote/stk_mins/freq={freq}/trade_date=2026-11-{day:02}/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    # As in official DG Silver: local naive TIMESTAMP, date, integral frequency, DOUBLE measure fields.
    schema = pa.schema([
        ("ts_code", pa.string()), ("freq", pa.int32()), ("trade_date", pa.date32()),
        ("trade_time", pa.timestamp("us")),
        *((field, pa.float64()) for field in ("open", "high", "low", "close", "vol", "amount")),
        ("exchange", pa.string()),
    ])
    rows = [
        dict(ts_code=CODE, freq=freq, trade_date=stamp.date(), trade_time=stamp.replace(tzinfo=None),
             open=o, high=h, low=l, close=c, vol=vol, amount=amount, exchange="XSHG")
        for stamp, o, h, l, c, vol, amount in bars
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    return path


def _write_factor(root, day, factor):
    path = root / f"silver/quote/adj_factor/trade_date=2026-11-{day:02}/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "ts_code": [CODE], "trade_date": [minute(day, 0, 0).date()], "adj_factor": [float(factor)],
    }), path)


def _service(root, *, backend="dg", enabled=True, batch_rows=8192):
    locations = deepcopy(DATASET_LOCATIONS)
    if enabled and backend == "dg":
        for dataset in DG_RECENT_STOCK_MINUTE_DATASETS.values():
            locations[dataset]["dg"]["enabled_adjustments"] = ("qfq",)
    config = technical_indicator_config_from_settings(
        Settings(_env_file=None, GOLDENSHARE_LAKE_ROOT=str(root), TECHNICAL_INDICATOR_BATCH_ROWS=batch_rows),
        data_location=backend, dataset_locations=locations,
    )
    return TechnicalIndicatorService(
        config=config, source=LakeTechnicalIndicatorPriceSource(config), registry=create_builtin_registry(),
    )


def _request(end, *, freq=30, count=2, start=None, calculations=(PRICE, MACD, KDJ, NINE)):
    return CalculationRequest(
        security_type="stock", ts_code=CODE, period=f"{freq}m", adjustment="qfq",
        end=end, start=start, latest_rows=count, calculations=calculations,
    )


def _results(page):
    return {result.calculation_id: dict(result.fields) for result in page.result.calculations}


def test_stock_30m_shares_one_adjustment_across_price_and_all_indicators(tmp_path, monkeypatch):
    # The raw close halves across the event, making the correctly adjusted closes all 10.
    previous = _write_minutes(tmp_path, 30, 16, [
        (minute(16, 14, 30), 20, 22, 18, 20, 10, 100),
        (minute(16, 15, 0), 20, 22, 18, 20, 12, 120),
    ])
    current = _write_minutes(tmp_path, 30, 17, [
        (minute(17, 9, 30), 9, 99, 1, 8, 3, 30),
        (minute(17, 10, 0), 10, 11, 9, 10, 7, 70),
        (minute(17, 10, 30), 10, 11, 9, 10, 10, 100),
    ])
    _write_factor(tmp_path, 16, 2)
    _write_factor(tmp_path, 17, 4)
    reads = []
    read_rows = LakePriceLocator._read_rows

    def track_reads(locator, sql, bindings, **kwargs):
        if "read_parquet" in sql:
            reads.append(bindings[0])
        return read_rows(locator, sql, bindings, **kwargs)

    def fail_reopen(*args):
        pytest.fail("Already-selected stock minutes were read again")

    monkeypatch.setattr(LakePriceLocator, "_read_rows", track_reads)
    monkeypatch.setattr(_LakePriceStream, "_open_file", fail_reopen)
    end = minute(17, 10, 15)
    page = _service(tmp_path).calculate_stock_minutes_recent(_request(end), output_limit=500)
    assert page.result.times == (minute(16, 15, 0), minute(17, 10, 0))
    assert reads == [[str(previous), str(current)]]
    assert page.selection.preceding_rows == 1
    assert page.source_facts.has_more
    assert page.source_facts.target_exchanges == ("XSHG", "XSHG")
    assert page.result.source.input_adjustment == "none"
    assert page.result.series.adjustment == "qfq"
    assert page.result.price_adjustment.basis_value == 4
    assert page.result.statistics.price_conversion_batches == 1
    assert page.result.statistics.source_rows == 4
    assert _results(page)["price"] == {
        "open": (10, 8), "high": (11, 11), "low": (9, 8), "close": (10, 10),
        "volume": (12, 10), "amount": (120, 100),
    }
    assert _results(page)["macd"] == {"dif": (0, 0), "dea": (0, 0), "hist": (0, 0)}
    expected_k = (2 * 50 + (10 - 8) / (11 - 8) * 100) / 3
    expected_d = (2 * 50 + expected_k) / 3
    kdj = _results(page)["kdj"]
    assert kdj["k"] == pytest.approx((50.0, expected_k))
    assert kdj["d"] == pytest.approx((50.0, expected_d))
    assert kdj["j"] == pytest.approx((50.0, 3 * expected_k - 2 * expected_d))
    assert _results(page)["nineturn"] == {"up_count": (0, 0), "down_count": (0, 0)}


def test_stock_30m_bounds_targets_only_and_ignores_factor_for_probe(tmp_path):
    _write_minutes(tmp_path, 30, 16, [
        (minute(16, 15, 0), 20, 22, 18, 20, 12, 120),
    ])
    _write_minutes(tmp_path, 30, 17, [
        (minute(17, 9, 30), 8, 8, 8, 8, 3, 30),
        (minute(17, 10, 0), 10, 11, 9, 10, 7, 70),
        (minute(17, 10, 30), 10, 11, 9, 10, 10, 100),
    ])
    _write_factor(tmp_path, 17, 4)
    service = _service(tmp_path)
    end = minute(17, 10, 15)

    # An older quote proves there is another page. PRICE has zero warmup.
    page = service.calculate_stock_minutes_recent(_request(end, count=1, calculations=(PRICE,)), output_limit=500)
    assert page.result.times == (minute(17, 10, 0),)
    assert page.source_facts.has_more

    page = service.calculate_stock_minutes_recent(
        _request(end, start=minute(17, 0, 0), count=500, calculations=(PRICE,)), output_limit=500,
    )
    assert page.result.times == (minute(17, 10, 0),)
    assert not page.source_facts.has_more

    with pytest.raises(SourceContractError, match="2026-11-16"):
        service.calculate_stock_minutes_recent(_request(end), output_limit=500)

    empty = service.calculate_stock_minutes_recent(
        _request(minute(17, 9, 45), start=minute(17, 0, 0)), output_limit=500,
    )
    assert empty.result is None and not empty.source_facts.has_more


def test_stock_30m_nine_turn_continues_from_warmup_and_caps_at_thirteen(tmp_path):
    timeline = []
    for day in (16, 17, 18):
        slots = REGULAR_30 if day != 18 else REGULAR_30[:3]
        bars = [(minute(day, 9, 30), 8, 8, 8, 8, 1, 10)]
        for hour, minute_of_hour in slots:
            stamp = minute(day, hour, minute_of_hour)
            close = 10 + len(timeline)
            timeline.append(stamp)
            bars.append((stamp, close, close + 1, close - 1, close, 2, 20))
        _write_minutes(tmp_path, 30, day, bars)
        _write_factor(tmp_path, day, 4)
    page = _service(tmp_path, batch_rows=4).calculate_stock_minutes_recent(
        _request(timeline[-1], count=8, calculations=(NINE,)), output_limit=500,
    )
    assert page.result.times == tuple(timeline[11:])
    assert _results(page)["nineturn"]["up_count"] == (8, 9, 10, 11, 12, 13, 13, 13)
    assert _results(page)["nineturn"]["down_count"] == (0,) * 8
    assert page.result.statistics.price_conversion_batches == 1


def test_stock_recent_minute_limit_and_enablement_remain_scoped(tmp_path):
    (tmp_path / "silver/quote/stk_mins/freq=30").mkdir(parents=True)
    request = _request(minute(17, 15, 0), count=501, calculations=(PRICE,))
    service = _service(tmp_path)
    assert service.calculate_stock_minutes_recent(request, output_limit=1000).result is None
    with pytest.raises(ResourceLimitError):
        service.calculate_stock_minutes_recent(request, output_limit=500)
    for backend, enabled in (("dg", False), ("prod_pg", True)):
        with pytest.raises(SourceUnsupportedError):
            _service(tmp_path, backend=backend, enabled=enabled).calculate_stock_minutes_recent(request, output_limit=1000)
    with pytest.raises(SourceUnsupportedError):
        service.calculate_stock_minutes_recent(replace(request, adjustment="none"), output_limit=1000)
    for period in ("30m", "90m", "120m"):
        with pytest.raises(SourceUnsupportedError):
            service.calculate_with_source(replace(request, period=period, latest_rows=500))


@pytest.mark.parametrize(("freq", "first_regular", "open_", "high", "low", "volume", "amount"), (
    (1, (9, 30), 24, 28, 20, 3, 30),
    (5, (9, 35), 22, 25, 21, 10, 100),
    (15, (9, 45), 22, 25, 21, 10, 100),
    (60, (10, 30), 22, 25, 21, 10, 100),
))
def test_stock_base_frequencies_keep_their_own_auction_and_nine_turn_rules(
    tmp_path, freq, first_regular, open_, high, low, volume, amount,
):
    auction = (minute(17, 9, 30), 24, 28, 20, 22, 3, 30)
    regular = (minute(17, *first_regular), 23, 25, 21, 24, 7, 70)
    _write_minutes(tmp_path, freq, 17, [auction] if freq == 1 else [auction, regular])
    _write_factor(tmp_path, 17, 4)
    service = _service(tmp_path)
    indicators = (PRICE, MACD, KDJ, NINE) if freq == 60 else (PRICE, MACD, KDJ)
    request = _request(minute(17, 15, 0), freq=freq, calculations=indicators)
    result = service.calculate_stock_minutes_recent(request, output_limit=500)
    assert result.result.times == (minute(17, *first_regular),)
    assert _results(result)["price"] == {
        "open": (open_,), "high": (high,), "low": (low,),
        "close": (22 if freq == 1 else 24,), "volume": (volume,), "amount": (amount,),
    }
    assert result.result.statistics.price_conversion_batches == 1
    if freq == 60:
        assert _results(result)["nineturn"]["up_count"] == (0,)
    else:
        with pytest.raises(CalculationUnsupportedError):
            service.calculate_stock_minutes_recent(replace(request, calculations=(NINE,)), output_limit=500)


@pytest.mark.parametrize(("target", "base", "slots", "ends", "highs", "volumes"), (
    (90, 30, REGULAR_30, ((11, 0), (14, 0), (15, 0)), (14, 17, 19), (7, 15, 15)),
    (120, 60, ((10, 30), (11, 30), (14, 0), (15, 0)), ((11, 30), (15, 0)), (13, 15), (4, 7)),
))
def test_stock_derived_minutes_use_dg_windows_and_share_adjusted_prices(
    tmp_path, target, base, slots, ends, highs, volumes,
):
    # DG groups consecutive regular bars through the lunch break and attaches
    # the 09:30 auction only to the first window (cn_a_derived_minute_bars.py).
    _write_minutes(tmp_path, base, 16, [
        (minute(16, *clock), 22, 24, 18, 20, 2, 20) for clock in slots[-2:]
    ])
    _write_minutes(tmp_path, base, 17, [
        (minute(17, 9, 30), 9, 99, 1, 8, 1, 10),
        *((minute(17, *clock), 11, 11 + i, 9, 10, i, 10 * i) for i, clock in enumerate(slots, 1)),
    ])
    _write_factor(tmp_path, 16, 2)
    _write_factor(tmp_path, 17, 4)
    service = _service(tmp_path)
    request = _request(minute(17, 15, 0), freq=target, count=len(ends))
    page = service.calculate_stock_minutes_recent(request, output_limit=500)
    assert page.result.times == tuple(minute(17, *clock) for clock in ends)
    assert page.selection.preceding_rows == 1
    assert page.source_facts.has_more
    assert page.result.statistics.price_conversion_batches == 1
    results = _results(page)
    assert results["price"] == {
        "open": (8,) + (11,) * (len(ends) - 1),
        "high": highs,
        "low": (8,) + (9,) * (len(ends) - 1),
        "close": (10,) * len(ends),
        "volume": volumes,
        "amount": tuple(10 * volume for volume in volumes),
    }
    assert results["macd"] == dict.fromkeys(("dif", "dea", "hist"), (0,) * len(ends))
    # The previous day's adjusted window is (high=12, low=9, close=10).
    # Its RSV is 100/3, so it advances K and D before today's first target.
    prior_k = (2 * 50 + 100 / 3) / 3
    prior_d = (2 * 50 + prior_k) / 3
    expected_k = (2 * prior_k + (10 - 8) / (highs[0] - 8) * 100) / 3
    expected_d = (2 * prior_d + expected_k) / 3
    assert results["kdj"]["j"][0] == pytest.approx(3 * expected_k - 2 * expected_d)
    assert results["nineturn"] == dict.fromkeys(("up_count", "down_count"), (0,) * len(ends))

    continuation = service.calculate_stock_minutes_recent(
        replace(request, end=minute(17, 10, 59) if target == 90 else minute(17, 11, 29)),
        output_limit=500,
    )
    assert continuation.result.times == (minute(16, 15, 0),)
    assert _results(continuation)["price"] == {
        "open": (11,), "high": (12,), "low": (9,), "close": (10,),
        "volume": (4,), "amount": (40,),
    }
    assert not continuation.source_facts.has_more


def test_stock_minute_large_limit_uses_target_date_range_before_reading_prices(tmp_path, monkeypatch):
    for day in (14, 15, 16, 17):
        _write_minutes(tmp_path, 30, day, [
            (minute(day, 9, 30), 8, 8, 8, 8, 1, 8),
            *((minute(day, *clock), 8, 8, 8, 8, 2, 16) for clock in REGULAR_30),
        ])
    _write_factor(tmp_path, 17, 4)
    opened = []
    original = LakePriceLocator._read_rows

    def read(locator, sql, bindings, **kwargs):
        if "base_bars" in sql and "read_parquet" in sql:
            opened.extend(bindings[0])
        return original(locator, sql, bindings, **kwargs)

    monkeypatch.setattr(LakePriceLocator, "_read_rows", read)
    page = _service(tmp_path).calculate_stock_minutes_recent(
        _request(minute(17, 15, 0), freq=90, start=minute(17, 0, 0), count=10_000, calculations=(PRICE,)),
        output_limit=10_000,
    )
    assert page.result.times == (minute(17, 11, 0), minute(17, 14, 0), minute(17, 15, 0))
    assert not page.source_facts.has_more
    assert len(opened) <= 2
    assert all("trade_date=2026-11-16" in path or "trade_date=2026-11-17" in path for path in opened)
