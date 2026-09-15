"""M5 READ-02/05/06: participation is not publication and gaps are not zero."""
from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from src.biz.queries.wealth.market.trading_assistant.return_coverage import ReturnDayEvidence, cover_return_days
from src.biz.queries.wealth.market.trading_assistant.return_days import PublishedReturnDay
from src.biz.queries.wealth.market.trading_assistant.return_scope import ParticipationDay, ReturnFactScope
from src.biz.queries.wealth.market.trading_assistant.return_statistics import DailyReturnFact, summarize_daily_returns
from src.biz.schemas.wealth.market.trading_assistant.common import AccountRef
from src.biz.services.wealth.market.trading_assistant.calculation.returns import profit_result

ACCOUNT = "00000000-0000-0000-0000-000000000001"
SCOPE = ReturnFactScope(AccountRef(accountId=ACCOUNT, name="测试", brokerName="券商"), 1, 1,
    UUID(int=2), date(2026, 9, 11), date(2026, 9, 7), None)


def evidence(day, *, opening=100, closing=100, trades=0, is_open=True, profit=100, missing=False):
    day = date(2026, 9, day)
    participation = ParticipationDay(day, opening, closing, trades)
    result = profit_result(profit, 10000, participates=True) if participation.participates and is_open else profit_result(0, 0, participates=False)
    published = None if missing else PublishedReturnDay(DailyReturnFact(day, result), UUID(int=day.day),
        datetime(day.year, day.month, day.day, 7, tzinfo=timezone.utc), None, 0, 0)
    return ReturnDayEvidence(participation, is_open, published)


def covered(values, *, scope=SCOPE, start=7, end=11, today=11, state="Delayed"):
    return cover_return_days(scope, start=date(2026, 9, start), end=date(2026, 9, end),
        today=date(2026, 9, today), evidence=tuple(values), missing_state=state)


def test_real_history_precedes_account_submission_and_hold_without_trade_counts():
    result = covered([evidence(i) for i in range(7, 12)])
    coverage = result.coverage
    assert coverage.dataStatus == "Ready" and coverage.isFinal
    assert coverage.accounts[0].initializedOn == "2026-09-11"
    assert coverage.accounts[0].effectiveStartDate == "2026-09-07"
    assert coverage.accounts[0].calculatedThroughDate == "2026-09-11"
    stats = summarize_daily_returns((DailyReturnFact(d.day, d.result) for d in result.days),
        start=date(2026, 9, 7), end=date(2026, 9, 11), coverage=coverage)
    assert stats.computedDayCount == 5


def test_gap_does_not_advance_complete_through_to_later_available_date():
    result = covered([evidence(7), evidence(8, missing=True), evidence(9), evidence(10), evidence(11)])
    assert result.coverage.dataStatus == "Partial" and not result.coverage.isFinal
    assert result.coverage.accounts[0].calculatedThroughDate == "2026-09-07"
    assert result.days[1].result.profit_cents is None
    assert result.days[-1].result.profit_cents == 100


def test_initial_gap_has_no_complete_through_even_if_last_day_is_ready():
    result = covered([evidence(7, missing=True), evidence(8)], end=8)
    assert result.coverage.accounts[0].calculatedThroughDate is None
    assert result.coverage.dataStatus == "Partial"


def test_closing_sale_still_counts_and_subsequent_cash_is_not_flat():
    result = covered([evidence(7, opening=100, closing=0, trades=1, profit=0),
                      evidence(8, opening=0, closing=0, missing=True)], end=8)
    assert [d.data_status for d in result.days] == ["Ready", "Empty"]
    assert result.days[0].result.return_pct == "0.00"
    assert result.days[1].result.return_pct is None
    assert result.coverage.dataStatus == "Ready"


def test_closed_exchange_day_needs_no_snapshot_even_with_holdings():
    result = covered([evidence(11), evidence(12, is_open=False, missing=True),
                      evidence(13, is_open=False, missing=True)], start=11, end=13, today=13)
    assert result.coverage.isFinal
    assert result.coverage.accounts[0].calculatedThroughDate == "2026-09-11"


@pytest.mark.parametrize("state", ["Delayed", "Recalculating", "Error"])
def test_unpublished_results_keep_actual_failure_state(state):
    result = covered([evidence(7, missing=True)], end=7, state=state)
    assert result.coverage.dataStatus == state and not result.coverage.isFinal
    assert result.days[0].result.profit_cents is None


def test_missing_calendar_not_inferred_from_weekday():
    result = covered([evidence(7, is_open=None, missing=True)], end=7)
    assert result.coverage.dataStatus == "Error"
    assert result.days[0].reason == "交易日历尚不可确认"


def test_cash_does_not_require_missing_stock_results():
    result = covered([evidence(7, opening=0, closing=0, missing=True)], end=7, state="Recalculating")
    assert result.coverage.dataStatus == "Empty" and result.coverage.isFinal


def test_target_clips_future_and_unrelated_stock_has_no_invented_history():
    result = covered([evidence(7)], end=11, today=7)
    assert result.coverage.accounts[0].targetThroughDate == "2026-09-07"
    for scope, start, end, today in ((replace(SCOPE, history_start=None), 7, 11, 11), (SCOPE, 12, 13, 11)):
        result = covered([], scope=scope, start=start, end=end, today=today)
        assert result.coverage.dataStatus == "Empty"
        assert result.coverage.accounts[0].effectiveStartDate is None
        assert result.coverage.accounts[0].targetThroughDate is None


@pytest.mark.parametrize("values", [[], [evidence(8)], [evidence(7), evidence(7)]])
def test_missing_duplicate_or_wrong_date_evidence_rejected(values):
    with pytest.raises(ValueError):
        covered(values, end=7 if len(values) < 2 else 8)


def test_conflicting_published_result_rejected():
    day = evidence(7)
    with pytest.raises(ValueError, match="contradicts"):
        covered([replace(day, is_open=False)], end=7)
    with pytest.raises(ValueError, match="invalid or unordered"):
        covered([replace(day, is_open=1)], end=7)
    with pytest.raises(ValueError):
        ParticipationDay(date(2026, 9, 7), -1, 0, 0)
