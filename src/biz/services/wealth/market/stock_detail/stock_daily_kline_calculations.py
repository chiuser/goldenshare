"""The stock daily API's fixed requests; no indicator arithmetic or source access."""

from datetime import datetime, time
from types import MappingProxyType
from zoneinfo import ZoneInfo

from goldenshare_technical_indicators.contracts import CalculationRequest

from .stock_daily_kline_contracts import StockDailyKlineInput, StockDailyKlineRequest


def _item(calculation_id, **parameters):
    return MappingProxyType({"calculation_id": calculation_id, "parameters": MappingProxyType(parameters)})


STOCK_DAILY_CALCULATIONS = (
    *(_item("ma", period=period) for period in (5, 10, 20, 30, 60, 90, 250)),
    _item("boll", period=20, multiplier=2),
    _item("macd", fast=12, slow=26, signal=9),
    _item("kdj", window=9, k_period=3, d_period=3),
    _item("price"),
)
_NINE_TURN_CALCULATION = _item("nineturn")
STOCK_DAILY_ALGORITHM_VERSIONS = MappingProxyType({
    "ma": "1.0.0", "boll": "1.0.0", "macd": "2.0.0", "kdj": "2.0.0", "price": "1.0.0",
    "nineturn": "1.0.0",
})
STOCK_DAILY_OUTPUT_FIELDS = MappingProxyType({
    "ma": ("value",), "boll": ("middle", "upper", "lower"),
    "macd": ("dif", "dea", "hist"), "kdj": ("k", "d", "j"),
    "price": ("open", "high", "low", "close", "volume", "amount"),
    "nineturn": ("up_count", "down_count"),
})


def stock_daily_calculations(*, include_nine_turn: bool):
    if include_nine_turn:
        return (*STOCK_DAILY_CALCULATIONS, _NINE_TURN_CALCULATION)
    return STOCK_DAILY_CALCULATIONS


def validate_stock_daily_request(request: StockDailyKlineRequest) -> None:
    """Apply the API rules in order; unknown codes reach the DB later."""
    if request.period != "day":
        raise ValueError("股票详情首期只支持 period=day")
    if request.adjustment != "forward":
        raise ValueError("股票详情首期只支持 adjustment=forward")
    if request.limit < 1 or request.limit > 500:
        raise ValueError("limit 必须在 1 到 500 之间")
    if (request.start_date is not None and request.end_date is not None
            and request.start_date > request.end_date):
        raise ValueError("startDate 不能晚于 endDate")


def is_stock_detail_first_page(request: StockDailyKlineRequest) -> bool:
    return (
        request.trade_date is not None
        and request.end_date == request.trade_date
        and request.start_date is None
    )


def build_calculation_request(
    source: StockDailyKlineInput, *, include_nine_turn: bool = False,
) -> CalculationRequest | None:
    """Use actual returned dates; the kernel determines its own preceding history."""
    if not source.bars:
        return None
    return CalculationRequest(
        security_type="stock", ts_code=source.ts_code, period="day", adjustment="qfq",
        calculations=stock_daily_calculations(include_nine_turn=include_nine_turn),
        start=datetime.combine(source.bars[0].trade_date, time.min, ZoneInfo("Asia/Shanghai")),
        end=datetime.combine(source.bars[-1].trade_date, time.min, ZoneInfo("Asia/Shanghai")),
    )
