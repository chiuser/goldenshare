"""M5 REVIEW-02/03/04: one exact statistics source, no database writes."""
from datetime import date

import pytest

from src.biz.queries.wealth.market.trading_assistant.return_statistics import DailyReturnFact, summarize_daily_returns
from src.biz.schemas.wealth.market.trading_assistant.common import Coverage
from src.biz.services.wealth.market.trading_assistant.calculation.returns import aggregate_returns, profit_result


START, END = date(2026, 9, 1), date(2026, 9, 30)


def fact(day, profit=0, capital=10000):
    return DailyReturnFact(date(2026, 9, day), profit_result(profit, capital, participates=capital > 0))


def stats(days, state="Ready", final=True):
    return summarize_daily_returns(iter(days), start=START, end=END,
        coverage=Coverage(dataStatus=state, reason=None if state == "Ready" else "测试覆盖状态",
                          isFinal=final, accounts=[]))


def test_exact_extrema_not_rounded_display_values():
    result = stats([fact(1, 1003, 100000), fact(2, 1004, 100000)])
    assert result.maxDailyReturn.returnPct == result.minDailyReturn.returnPct == "1.00"
    assert result.maxDailyReturn.dates == ["2026-09-02"]
    assert result.minDailyReturn.dates == ["2026-09-01"]


def test_exact_ties_keep_all_dates_in_order_and_unbounded_integer_precision():
    huge = 10 ** 80
    result = stats([fact(1, huge, huge * 3), fact(2, huge * 2, huge * 6), fact(3, -1, 3)])
    assert result.maxDailyReturn.dates == ["2026-09-01", "2026-09-02"]
    assert result.maxDailyReturn.returnPct == "33.33"
    assert result.minDailyReturn.returnPct == "-33.33"
    assert (result.positiveDayCount, result.negativeDayCount, result.flatDayCount, result.computedDayCount) == (2, 1, 0, 3)


def test_all_zero_is_not_no_valid_days_and_every_date_is_both_extrema():
    result = stats([fact(1), fact(2), fact(3)])
    assert result.resultKind == "HAS_VALID_DAYS"
    assert result.flatDayCount == result.computedDayCount == 3
    assert result.positiveDayCount == result.negativeDayCount == 0
    assert result.minDailyReturn == result.maxDailyReturn
    assert result.minDailyReturn.dates == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert result.minDailyReturn.returnPct == "0.00"


@pytest.mark.parametrize("days", [[], [fact(1, 0, 0)]])
def test_confirmed_no_participation_is_not_a_flat_day(days):
    result = stats(days)
    assert result.resultKind == "NO_VALID_DAYS"
    assert result.computedDayCount == result.flatDayCount == 0
    assert result.maxDailyReturn is result.minDailyReturn is None


@pytest.mark.parametrize("state", ["Delayed", "Recalculating", "Error", "Partial"])
def test_unavailable_without_any_valid_day_has_unknown_counts(state):
    result = stats([fact(1, None)], state, False)
    assert result.resultKind == "UNDETERMINED"
    assert result.computedDayCount is result.positiveDayCount is result.negativeDayCount is result.flatDayCount is None
    assert result.maxDailyReturn is result.minDailyReturn is None
    assert not result.isFinal


def test_partial_only_counts_complete_days_not_missing_or_cash():
    result = stats([fact(1, 5), fact(2, None), fact(3, 0, 0), fact(4, -5)], "Partial", False)
    assert result.resultKind == "HAS_VALID_DAYS" and not result.isFinal
    assert (result.positiveDayCount, result.negativeDayCount, result.flatDayCount, result.computedDayCount) == (1, 1, 0, 2)


def test_accounts_are_aggregated_before_counting_days_without_averaging_rates():
    day = aggregate_returns((profit_result(100, 1000, participates=True),
                             profit_result(-100, 10000, participates=True)))
    result = stats([DailyReturnFact(START, day)])
    assert result.computedDayCount == result.flatDayCount == 1
    assert result.maxDailyReturn.returnPct == "0.00"
    missing = aggregate_returns((profit_result(100, 1000, participates=True),
                                 profit_result(None, 10000, participates=True)))
    assert stats([DailyReturnFact(START, missing)], "Delayed", False).computedDayCount is None


@pytest.mark.parametrize("days", [
    [fact(2), fact(1)], [fact(1), fact(1)],
    [DailyReturnFact(date(2026, 8, 31), profit_result(1, 10, participates=True))],
    [DailyReturnFact(date(2026, 10, 1), profit_result(1, 10, participates=True))],
])
def test_duplicates_unordered_and_neighbouring_month_dates_rejected(days):
    with pytest.raises(ValueError, match="unique ordered dates"):
        stats(days)


@pytest.mark.parametrize("state,days,final", [
    ("Ready", [fact(1, None)], True), ("Empty", [fact(1)], True),
    ("Delayed", [fact(1)], False), ("Recalculating", [fact(1)], False), ("Error", [fact(1)], False),
])
def test_coverage_cannot_lie_about_results(state, days, final):
    with pytest.raises(ValueError):
        stats(days, state, final)


def test_inverted_range_rejected_and_input_results_remain_unchanged():
    values = (fact(1, 5), fact(2, 0), fact(3, -10))
    original = tuple(values)
    assert stats(values) == stats(iter(values))
    assert values == original
    with pytest.raises(ValueError, match="Invalid statistics range"):
        summarize_daily_returns(values, start=END, end=START,
            coverage=Coverage(dataStatus="Ready", reason=None, isFinal=True, accounts=[]))
