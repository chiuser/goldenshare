"""Public nine-turn contract with independently specified day-bar sequences."""

from datetime import date, datetime, time, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

import pyarrow as pa
import pytest

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.discovery import SourceCapability, describe_calculation, list_calculations
from goldenshare_technical_indicators.errors import CalculationCancelledError, CalculationUnsupportedError
from goldenshare_technical_indicators.execution_control import ExecutionControl
from goldenshare_technical_indicators.executor import DuckDBExecutor
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from src.app.runtime.technical_indicators.composition import build_runtime_config
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.config.settings import Settings
from test_stage_b_stock_daily import CODE, PRICE, _write


NINE_TURN = {"calculation_id": "nineturn", "parameters": {}}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _write_daily_lake(root, closes):
    # Physical schemas match the DG stock daily, calendar, lifecycle and suspension fixtures
    # in test_stage_b_stock_daily, plus the audited DG stock adjustment factor date and value.
    first = date(2026, 1, 5)
    days = []
    calendar = []
    day = first
    while len(days) < len(closes):
        is_open = day.weekday() < 5
        calendar.append(dict(exchange="SSE", trade_date=day, is_open=is_open))
        if is_open:
            days.append(day)
        day += timedelta(days=1)
    _write(root, "silver/calendar/trade_calendar/full/part-000.parquet",
           [("exchange", pa.string()), ("trade_date", pa.date32()), ("is_open", pa.bool_())], calendar)
    _write(root, "silver/basic/stock_lifecycle/full/part-000.parquet",
           [("ts_code", pa.string()), ("list_date", pa.date32()), ("delist_date", pa.date32())],
           [dict(ts_code=CODE, list_date=first, delist_date=None)])
    for index, (day, close) in enumerate(zip(days, closes, strict=True)):
        factor = 1.0 if index < len(days) // 2 else 2.0
        raw_close = close * 2.0 / factor
        _write(root, f"silver/quote/stock_daily/trade_date={day}/part-000.parquet",
               [("ts_code", pa.string()), ("trade_date", pa.date32()),
                *((key, pa.float64()) for key in ("open", "high", "low", "close", "vol", "amount"))],
               [dict(ts_code=CODE, trade_date=day, open=raw_close, high=raw_close, low=raw_close,
                     close=raw_close, vol=10.0, amount=100.0)])
        _write(root, f"silver/quote/adj_factor/trade_date={day}/part-000.parquet",
               [("ts_code", pa.string()), ("trade_date", pa.date32()), ("adj_factor", pa.float64())],
               [dict(ts_code=CODE, trade_date=day, adj_factor=factor)])
        _write(root, f"silver/quote/stock_suspend_daily/trade_date={day}/part-000.parquet",
               [("ts_code", pa.string()), ("trade_date", pa.date32()),
                ("suspend_type", pa.string()), ("suspend_timing", pa.string())], [])
    return tuple(days)


def _config(root, *, batch_rows=64):
    return build_runtime_config(Settings(
        _env_file=None,
        APP_ENV="local",
        GOLDENSHARE_LAKE_ROOT=str(root),
        TECHNICAL_INDICATOR_BATCH_ROWS=batch_rows,
    ))


def _service(config, *, control=None):
    return TechnicalIndicatorService(
        config=config, source=LakeTechnicalIndicatorPriceSource(config),
        registry=create_builtin_registry(), control=control,
    )


def _request(first, last, *, kind="stock", period="day", adjustment="qfq", calculations=(NINE_TURN,)):
    return CalculationRequest(
        security_type=kind, ts_code=CODE if kind == "stock" else "000001.SH",
        period=period, adjustment=adjustment, calculations=calculations,
        start=datetime.combine(first, time(9, 35), SHANGHAI),
        end=datetime.combine(last, time(9, 35), SHANGHAI),
    )


def test_discovery_advertises_enabled_daily_and_adjusted_stock_period_sources(tmp_path):
    config = _config(tmp_path)
    registry = create_builtin_registry()
    description = describe_calculation(registry, "nineturn", config=config)
    assert description in list_calculations(registry, config=config)
    assert description.source_supported
    assert set(description.source_capabilities) == {
        SourceCapability("stock", "day", "none", "stock_daily"),
        SourceCapability("stock", "day", "qfq", "stock_daily"),
        SourceCapability("index", "day", "none", "index_daily"),
        SourceCapability("stock", "week", "qfq", "stock_weekly"),
        SourceCapability("stock", "month", "qfq", "stock_monthly"),
    }
    definition = description.definition
    assert definition.algorithm_version == "1.0.0"
    assert definition.parameter_specs == ()
    assert definition.input_fields == {"close"}
    assert definition.supported_periods == ("day",)
    assert [(field.name, field.sql_type, field.nullable) for field in definition.output_fields] == [
        ("up_count", "DOUBLE", False),
        ("down_count", "DOUBLE", False),
    ]


@pytest.mark.parametrize("period", ("5m", "week", "month"))
def test_rejects_enabled_non_daily_sources(tmp_path, period):
    day = date(2026, 1, 5)
    service = _service(_config(tmp_path))
    with pytest.raises(CalculationUnsupportedError, match="requested period"):
        service.calculate(_request(day, day, kind="index", period=period, adjustment="none"))


def test_rejects_parameters(tmp_path):
    day = date(2026, 1, 5)
    service = _service(_config(tmp_path))
    with pytest.raises(CalculationUnsupportedError, match="Unknown calculation parameter"):
        service.calculate(_request(day, day, calculations=(
            {"calculation_id": "nineturn", "parameters": {"period": 4}},
        )))


@pytest.fixture
def up_then_down_lake(tmp_path):
    # The first 20 prices rise. At position 20 the close equals position 16,
    # then falls for 15 comparisons before the final close reverses direction.
    return _write_daily_lake(tmp_path, (*range(20), *range(16, 0, -1), 5))


@pytest.mark.parametrize("batch_rows", (1, 12, 16, 64))
def test_counts_across_batches_and_trims_the_warmup(tmp_path, up_then_down_lake, batch_rows):
    days = up_then_down_lake
    service = _service(_config(tmp_path, batch_rows=batch_rows))
    full = service.calculate(_request(days[0], days[-1]))
    expected_up = (0,) * 4 + tuple(range(1, 13)) + (13,) * 4 + (0,) * 16 + (1,)
    expected_down = (0,) * 21 + tuple(range(1, 13)) + (13,) * 3 + (0,)
    assert full.times == days
    assert full.calculations[0].parameters == ()
    assert full.calculations[0].fields == (("up_count", expected_up), ("down_count", expected_down))

    start = 19
    subset = service.calculate(_request(days[start], days[-1]))
    assert subset.times == days[start:]
    assert subset.source.read_start == days[start - 16]
    assert subset.statistics.source_rows == len(subset.times) + 16
    assert subset.calculations[0].fields == (
        ("up_count", expected_up[start:]), ("down_count", expected_down[start:]),
    )


@pytest.mark.parametrize(("first_close", "count"), ((0, 13), (4, 12)))
def test_sixteenth_preceding_close_changes_the_first_output(tmp_path, first_close, count):
    # Prices at positions 1 through 16 are identical between these two cases.
    days = _write_daily_lake(tmp_path, (first_close, *range(1, 17)))
    result = _service(_config(tmp_path, batch_rows=16)).calculate(_request(days[-1], days[-1]))
    assert result.times == (days[-1],)
    assert result.statistics.source_rows == 17
    assert result.calculations[0].fields == (("up_count", (count,)), ("down_count", (0,)))


def test_adding_nine_turn_shares_the_existing_adjusted_prices(tmp_path, up_then_down_lake):
    days = up_then_down_lake
    service = _service(_config(tmp_path))
    calculations = (PRICE, *(
        {"calculation_id": name, "parameters": {}} for name in ("ma", "boll", "macd", "kdj")
    ))
    baseline = service.calculate(_request(days[18], days[-1], calculations=calculations))
    combined = service.calculate(_request(days[18], days[-1], calculations=(*calculations, NINE_TURN)))
    raw = service.calculate(_request(days[18], days[-1], adjustment="none"))
    assert combined.times == baseline.times == raw.times
    assert combined.calculations[:-1] == baseline.calculations
    assert combined.statistics.source_rows == baseline.statistics.source_rows == len(days)
    assert combined.statistics.source_files == baseline.statistics.source_files
    assert combined.statistics.price_conversion_batches == baseline.statistics.price_conversion_batches == 1
    # Raw closes fall at the factor change. The prepared adjusted closes continue upwards.
    assert dict(raw.calculations[0].fields)["down_count"][0] == 1
    assert dict(combined.calculations[-1].fields)["up_count"][0] == 13


def test_cancellation_releases_both_owned_tables_and_retry_starts_fresh(tmp_path, up_then_down_lake, monkeypatch):
    days = up_then_down_lake
    config = _config(tmp_path, batch_rows=12)
    control = ExecutionControl(arrived_at=monotonic(), config=config)
    request = _request(days[13], days[-1])
    execute = DuckDBExecutor.execute
    cleanup_drop = DuckDBExecutor.cleanup_drop
    cleaned = []

    def cancel_after_output(executor, step):
        result = execute(executor, step)
        if step.name == "nineturn_batch":
            control.request_stop("cancel")
        return result

    def record_drop(executor, name):
        if name.startswith("ti_nineturn_"):
            cleaned.append(name)
        return cleanup_drop(executor, name)

    with monkeypatch.context() as patch:
        patch.setattr(DuckDBExecutor, "execute", cancel_after_output)
        patch.setattr(DuckDBExecutor, "cleanup_drop", record_drop)
        with pytest.raises(CalculationCancelledError):
            _service(config, control=control).calculate(request)
    assert cleaned == ["ti_nineturn_output_0", "ti_nineturn_state_0"]
    assert control.resources_released_at is not None
    retry = _service(config).calculate(request)
    assert retry.times == days[13:]
    assert dict(retry.calculations[0].fields)["up_count"][:5] == (10, 11, 12, 13, 13)
