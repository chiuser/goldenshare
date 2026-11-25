"""Stage-two period boundaries; request and JSON expectations are independent literals.

Only calculation/source facts are substituted. The real period assembler and
Pydantic models verify that daily-only rails do not enter weekly/monthly JSON.
"""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from goldenshare_technical_indicators.contracts import CalculationValues, PeriodBarMetadata
from src.biz.schemas.wealth.market.stock_detail import StockDetailStockRefDto
from src.biz.services.wealth.market.stock_detail.stock_period_kline_service import (
    StockPeriodContext, StockPeriodKlineService,
)
from tests.stock_daily_kline_helpers import result_for
from tests.test_stock_daily_kline_service import _request, _source


@pytest.mark.parametrize("period", ["week", "month"])
def test_period_requests_keep_the_original_calculation_set(period):
    day = date(2026, 1, 9)
    context = StockPeriodContext(_source(()).context, StockDetailStockRefDto(tsCode="600000.SH"), day, ())
    calls = []

    def calculate(request, **options):
        calls.append((request, options))
        return "calculated"

    request = _request(period=period, limit=100)
    assert StockPeriodKlineService.calculate(context, request, SimpleNamespace(calculate_with_source=calculate)) == "calculated"
    captured, options = calls[0]
    assert [(item["calculation_id"], dict(item["parameters"])) for item in captured.calculations] == [
        *(("ma", {"period": n}) for n in (5, 10, 20, 30, 60, 90, 250)),
        ("boll", {"period": 20, "multiplier": 2}),
        ("macd", {"fast": 12, "slow": 26, "signal": 9}),
        ("kdj", {"window": 9, "k_period": 3, "d_period": 3}),
        ("price", {}), ("nineturn", {}),
    ]
    assert captured.period == period and captured.adjustment == "qfq"
    assert captured.latest_rows == (100 if period == "week" else None)
    assert options["output_rows"] == (100 if period == "week" else None)
    assert options["require_current_period_end_date"] is True


@pytest.mark.parametrize("period", ["week", "month"])
def test_period_json_keeps_original_factors_dates_and_cursor(period):
    day = date(2026, 1, 9)
    previous = date(2026, 1, 2) if period == "week" else date(2025, 12, 31)
    context = StockPeriodContext(_source(()).context, StockDetailStockRefDto(tsCode="600000.SH"), day, ())
    base = result_for("600000.SH", (day,))
    common = tuple(item for item in base.calculations if item.calculation_id != "trend_channel")
    counts = CalculationValues("nineturn", "1.0.0", (), (("up_count", (0,)), ("down_count", (0,))))
    result = replace(base, source_as_of=(day,), period_bars=(PeriodBarMetadata(date(2026, 1, 5) if period == "week" else date(2026, 1, 1), day, 1.5),),
                     calculations=(*common, counts))
    calculated = SimpleNamespace(result=result, source_facts=SimpleNamespace(
        current_period_bar=None, previous_target_date=previous,
    ))
    payload = StockPeriodKlineService.assemble(
        context, _request(period=period, limit=100), calculated, max_output_rows=500, price_source="literal",
    ).model_dump(mode="json")
    assert payload["period"] == period and payload["bars"][0]["tradeDate"] == "2026-01-09"
    assert payload["bars"][0]["factors"] == {
        "ma": {f"ma{n}": 10 for n in (5, 10, 20, 30, 60, 90, 250)},
        "boll": {"upper": 10, "middle": 10, "lower": 10},
        "macd": {"dif": 10, "dea": 10, "macd": 10}, "kdj": {"k": 10, "d": 10, "j": 10},
    }
    assert payload["meta"] == {
        "count": 1, "limit": 100 if period == "week" else 500,
        "startDate": None, "endDate": "2026-01-09", "nextEndDate": "2026-01-02" if period == "week" else "2025-12-31",
    }
    assert payload["nineTurnMarkers"] == []
