"""The stock daily API's fixed requests; no indicator arithmetic or source access."""

from types import MappingProxyType

from src.foundation.technical_indicators.contracts import CalculationInstance, CalculationRequest

from .stock_daily_kline_contracts import StockDailyKlineInput, StockDailyKlineRequest


STOCK_DAILY_CALCULATIONS = (
    *(CalculationInstance(f"ma{period}", "ma", {"period": period})
      for period in (5, 10, 20, 30, 60, 90, 250)),
    CalculationInstance("boll", "boll", {"period": 20, "multiplier": 2}),
    CalculationInstance("macd", "macd", {"fast": 12, "slow": 26, "signal": 9}),
    CalculationInstance("kdj", "kdj", {"window": 9, "k_period": 3, "d_period": 3}),
)
STOCK_DAILY_ALGORITHM_VERSIONS = MappingProxyType({
    "ma": "1.0.0", "boll": "1.0.0", "macd": "2.0.0", "kdj": "2.0.0",
})
STOCK_DAILY_OUTPUT_FIELDS = MappingProxyType({
    "ma": ("value",), "boll": ("middle", "upper", "lower"),
    "macd": ("dif", "dea", "hist"), "kdj": ("k", "d", "j"),
})


def validate_stock_daily_request(request: StockDailyKlineRequest) -> None:
    """Preserve the old API rules and their order; unknown codes reach the DB later."""
    if request.period != "day":
        raise ValueError("股票详情首期只支持 period=day")
    if request.adjustment != "forward":
        raise ValueError("股票详情首期只支持 adjustment=forward")
    if request.limit < 1 or request.limit > 2000:
        raise ValueError("limit 必须在 1 到 2000 之间")
    if (request.start_date is not None and request.end_date is not None
            and request.start_date > request.end_date):
        raise ValueError("startDate 不能晚于 endDate")


def build_calculation_request(source: StockDailyKlineInput) -> CalculationRequest | None:
    """Use actual returned dates; the kernel determines its own preceding history."""
    if not source.bars:
        return None
    return CalculationRequest(
        security_type="stock", ts_code=source.ts_code, period="day", adjustment="qfq",
        calculations=STOCK_DAILY_CALCULATIONS,
        start=source.bars[0].trade_date, end=source.bars[-1].trade_date,
        limit=len(source.bars), before=None,
    )
