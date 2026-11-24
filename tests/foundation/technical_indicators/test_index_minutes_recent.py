"""Exercise the DG index-minute request from market-data selection to indicator output."""

from dataclasses import replace
from datetime import datetime
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


def _service(root, environment="local"):
    config = build_runtime_config(Settings(
        _env_file=None, APP_ENV=environment, GOLDENSHARE_LAKE_ROOT=str(root),
    ))
    return TechnicalIndicatorService(
        config=config, source=LakeTechnicalIndicatorPriceSource(config), registry=create_builtin_registry(),
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
def test_recent_minute_warmup_and_volume_use_rows_own_date(tmp_path, freq, h, m):
    old, previous, end = _minute(9, 14, 0), _minute(9, 15, 0), _minute(10, h, m)
    codes = ("000001.SH", "399001.SZ")
    _write_minutes(tmp_path, freq, 9, [
        row for code in codes for row in ((code, old, 100, 1000), (code, previous, 104, 1200))
    ])
    _write_minutes(tmp_path, freq, 10, [(code, end, 110, 15) for code in codes])
    service = _service(tmp_path)
    for code, expected_volume, exchange in ((codes[0], 1500, "XSHG"), (codes[1], 15, "XSHE")):
        page = service.calculate_index_minutes_recent(_request(freq, end, code=code), output_limit=MAX_INDEX_MINUTE_LIMIT)
        assert page.result.times == (previous, end)
        assert dict(page.result.calculations[0].fields)["volume"] == (1200, expected_volume)
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
        service.calculate_index_minutes_recent(replace(request, period="90m"), output_limit=MAX_INDEX_MINUTE_LIMIT)
    with pytest.raises(SourceUnsupportedError):
        _service(tmp_path, "prod").calculate_index_minutes_recent(request, output_limit=MAX_INDEX_MINUTE_LIMIT)
    legacy = service.parser.parse(replace(request, start=end, latest_rows=None))
    assert legacy.target.dataset_id == "index_mins_5m"
