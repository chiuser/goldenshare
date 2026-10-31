"""Stock daily integration LLD §04–06, §16.2; A contracts only in this stage.

Dates, parameter tuples and errors below are independent LLD literals. No DB,
source, calculation, Control or Web app is opened; C will cover prepare/assemble.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.biz.api.wealth.market.stock_detail_dependencies import get_stock_daily_kline_backend
from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContext
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_calculations import (
    STOCK_DAILY_ALGORITHM_VERSIONS, STOCK_DAILY_CALCULATIONS, STOCK_DAILY_OUTPUT_FIELDS,
    build_calculation_request, validate_stock_daily_request,
)
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_contracts import (
    StockDailyKlineInput, StockDailyKlineRequest, StockDailyKlineRow,
)
from src.foundation.technical_indicators.calculation.indicators import create_builtin_registry


def _request(**overrides):
    return replace(StockDailyKlineRequest(
        "600000.SH", "day", "forward", None, None, None, 300, False,
    ), **overrides)


def _row(day):
    return StockDailyKlineRow(day, 10.0, 11.0, 9.0, 10.0, 10.0, 0.0, 0.0,
                             100.0, 1000.0, None, None)


def _source(bars, request=None):
    context = MarketPageContext(
        "CN_A", date(2026, 1, 9), date(2026, 1, 8), True, "CLOSED",
        datetime(2026, 1, 9, 16, tzinfo=ZoneInfo("Asia/Shanghai")), "explicit",
    )
    return StockDailyKlineInput(
        request or _request(), context, "600000.SH", "浦发银行", date(2026, 1, 9), bars,
    )


def test_request_and_fixed_calculations():
    expected = (
        ("ma5", "ma", {"period": 5}), ("ma10", "ma", {"period": 10}),
        ("ma20", "ma", {"period": 20}), ("ma30", "ma", {"period": 30}),
        ("ma60", "ma", {"period": 60}), ("ma90", "ma", {"period": 90}),
        ("ma250", "ma", {"period": 250}),
        ("boll", "boll", {"period": 20, "multiplier": 2}),
        ("macd", "macd", {"fast": 12, "slow": 26, "signal": 9}),
        ("kdj", "kdj", {"window": 9, "k_period": 3, "d_period": 3}),
    )
    assert tuple((item.instance_id, item.calculation_id, dict(item.parameters))
                 for item in STOCK_DAILY_CALCULATIONS) == expected
    assert dict(STOCK_DAILY_ALGORITHM_VERSIONS) == {
        "ma": "1.0.0", "boll": "1.0.0", "macd": "2.0.0", "kdj": "2.0.0",
    }
    assert dict(STOCK_DAILY_OUTPUT_FIELDS) == {
        "ma": ("value",), "boll": ("middle", "upper", "lower"),
        "macd": ("dif", "dea", "hist"), "kdj": ("k", "d", "j"),
    }
    registry = create_builtin_registry()
    for item in STOCK_DAILY_CALCULATIONS:
        definition = registry.resolve(item.calculation_id)
        definition.validate_parameters(item.parameters)
        assert "day" in definition.supported_periods
        assert definition.algorithm_version == STOCK_DAILY_ALGORITHM_VERSIONS[item.calculation_id]
        assert tuple(field.name for field in definition.output_fields) == STOCK_DAILY_OUTPUT_FIELDS[item.calculation_id]
    for changed, message in (
        ({"period": "week", "adjustment": "qfq", "limit": 0}, "股票详情首期只支持 period=day"),
        ({"adjustment": "qfq", "limit": 0}, "股票详情首期只支持 adjustment=forward"),
        ({"limit": 0}, "limit 必须在 1 到 2000 之间"),
        ({"limit": 2001}, "limit 必须在 1 到 2000 之间"),
        ({"start_date": date(2026, 1, 9), "end_date": date(2026, 1, 8)}, "startDate 不能晚于 endDate"),
    ):
        with pytest.raises(ValueError) as caught:
            validate_stock_daily_request(_request(**changed))
        assert str(caught.value) == message
    for limit in (1, 300, 1000, 2000):
        validate_stock_daily_request(_request(ts_code="UNKNOWN", limit=limit))
    # The old rule compares explicit start/end only, not the eventual context.
    validate_stock_daily_request(_request(start_date=date(2026, 1, 12)))
    source = _source((_row(date(2026, 1, 5)), _row(date(2026, 1, 6))))
    calculation = build_calculation_request(source)
    assert (calculation.security_type, calculation.ts_code, calculation.period,
            calculation.adjustment, calculation.start, calculation.end,
            calculation.limit, calculation.before) == (
        "stock", "600000.SH", "day", "qfq", date(2026, 1, 5), date(2026, 1, 6), 2, None,
    )
    assert calculation.calculations == STOCK_DAILY_CALCULATIONS
    assert source.request.limit == 300 and source.query_end_date == date(2026, 1, 9)
    assert build_calculation_request(_source(())) is None


def test_input_is_detached_and_immutable():
    row = _row(date(2026, 1, 5))
    original = [row]
    source = _source(original)
    original.append(_row(date(2026, 1, 6)))
    assert source.bars == (row,) and isinstance(source.bars, tuple)
    assert source.bars[0].turnover_rate is None
    for target, attribute, replacement in (
        (source, "bars", ()), (source.request, "limit", 1),
        (row, "close_qfq", 12.0), (source.context, "source", "default"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(target, attribute, replacement)
    with pytest.raises(TypeError):
        STOCK_DAILY_CALCULATIONS[0].parameters["period"] = 30
    with pytest.raises(TypeError):
        STOCK_DAILY_ALGORITHM_VERSIONS["ma"] = "other"
    with pytest.raises(TypeError):
        STOCK_DAILY_OUTPUT_FIELDS["ma"] = ("other",)
    with pytest.raises(TypeError):
        _source([{"trade_date": date(2026, 1, 5)}])
    with pytest.raises(TypeError):
        replace(source, context={})
    with pytest.raises(TypeError):
        replace(row, close_qfq=[])
    with pytest.raises(TypeError):
        _request(trade_date=datetime(2026, 1, 5))
    with pytest.raises(RuntimeError, match="Stock daily kline backend is not installed"):
        get_stock_daily_kline_backend()
