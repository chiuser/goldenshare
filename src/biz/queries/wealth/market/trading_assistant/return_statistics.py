"""One exact daily-statistics projection for review and calendar (§4.13.2).

Inputs are already aggregated for one owned account/stock scope and fixed
publication. This module never averages rates or turns missing days into zero.
"""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from src.biz.schemas.wealth.market.trading_assistant.common import Coverage
from src.biz.schemas.wealth.market.trading_assistant.returns import DailyReturnExtreme, DailyStats
from src.biz.services.wealth.market.trading_assistant.calculation.precision import compare_return
from src.biz.services.wealth.market.trading_assistant.calculation.returns import ProfitResult


@dataclass(frozen=True, slots=True)
class DailyReturnFact:
    day: date
    result: ProfitResult

    def __post_init__(self):
        if type(self.day) is not date or not isinstance(self.result, ProfitResult):
            raise ValueError("Invalid daily return fact")


def summarize_daily_returns(days: Iterable[DailyReturnFact], *, start: date, end: date,
                            coverage: Coverage) -> DailyStats:
    """Consume an ordered stream once; retain only tied extreme dates.

    Coverage must be established by the caller against the expected calendar,
    not inferred from the last available row. Out-of-window rows are rejected
    so a calendar's neighbouring-month cells cannot enter its month summary.
    """
    if type(start) is not date or type(end) is not date or start > end:
        raise ValueError("Invalid statistics range")
    counts = [0, 0, 0]
    low = high = None
    low_dates, high_dates = [], []
    previous = None
    missing = False
    for fact in days:
        if not start <= fact.day <= end or (previous is not None and fact.day <= previous):
            raise ValueError("Daily statistics require unique ordered dates inside the range")
        previous = fact.day
        result = fact.result
        if result.status == "Delayed":
            missing = True
            continue
        if result.status == "Empty":
            continue
        counts[0 if result.profit_cents > 0 else 1 if result.profit_cents < 0 else 2] += 1
        low_order = -1 if low is None else compare_return(
            result.profit_cents, result.capital_cents, low.profit_cents, low.capital_cents)
        high_order = 1 if high is None else compare_return(
            result.profit_cents, result.capital_cents, high.profit_cents, high.capital_cents)
        if low_order < 0:
            low, low_dates = result, [fact.day.isoformat()]
        elif low_order == 0:
            low_dates.append(fact.day.isoformat())
        if high_order > 0:
            high, high_dates = result, [fact.day.isoformat()]
        elif high_order == 0:
            high_dates.append(fact.day.isoformat())
    count = sum(counts)
    if missing and coverage.dataStatus in ("Ready", "Empty"):
        raise ValueError("Complete coverage contains missing daily results")
    if coverage.dataStatus == "Empty" and count:
        raise ValueError("Empty coverage contains valid daily results")
    if coverage.dataStatus in ("Delayed", "Recalculating", "Error") and count:
        raise ValueError("Available subset requires Partial coverage")
    determined = count > 0 or coverage.dataStatus in ("Ready", "Empty")
    return DailyStats(
        positiveDayCount=counts[0] if determined else None,
        negativeDayCount=counts[1] if determined else None,
        flatDayCount=counts[2] if determined else None,
        computedDayCount=count if determined else None,
        minDailyReturn=DailyReturnExtreme(returnPct=low.return_pct, dates=low_dates) if low else None,
        maxDailyReturn=DailyReturnExtreme(returnPct=high.return_pct, dates=high_dates) if high else None,
        dataStatus=coverage.dataStatus, reason=coverage.reason, isFinal=coverage.isFinal,
        resultKind="HAS_VALID_DAYS" if count else "NO_VALID_DAYS" if determined else "UNDETERMINED",
    )
