"""Reconcile civil-date participation, exchange sessions and sealed returns."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.biz.schemas.wealth.market.trading_assistant.common import AccountCoverage, Coverage
from src.biz.services.wealth.market.trading_assistant.calculation.returns import ProfitResult
from .return_days import PublishedReturnDay
from .return_scope import ReturnFactScope, ParticipationDay


@dataclass(frozen=True, slots=True)
class ReturnDayEvidence:
    participation: ParticipationDay
    is_open: bool | None
    published: PublishedReturnDay | None


@dataclass(frozen=True, slots=True)
class CoveredReturnDay:
    day: date
    result: ProfitResult
    data_status: str
    reason: str | None
    valuation_at: datetime | None


@dataclass(frozen=True, slots=True)
class AccountReturnCoverage:
    coverage: Coverage
    days: tuple[CoveredReturnDay, ...]


def cover_return_days(scope: ReturnFactScope, *, start: date, end: date, today: date,
                      evidence: tuple[ReturnDayEvidence, ...], missing_state: str = "Delayed",
                      missing_reason: str = "目标日期收益尚未就绪") -> AccountReturnCoverage:
    """Last complete date stops before the first required-but-unavailable day.

    Inputs contain every civil day in the effective range, not just returned
    snapshots. No-trade holding days and closing sales are still required days.
    """
    if any(type(d) is not date for d in (start, end, today)) or start > end:
        raise ValueError("Invalid coverage range")
    if missing_state not in ("Delayed", "Recalculating", "Error") or not missing_reason:
        raise ValueError("Invalid unavailable return state")
    first = max(start, scope.history_start) if scope.history_start else None
    last = min(end, today)
    if first is None or first > last:
        first = last = None
    expected = (last - first).days + 1 if first else 0
    if len(evidence) != expected:
        raise ValueError("Coverage needs every effective civil date")
    days, issues, complete_through, valuation_at = [], [], None, None
    prefix_complete = True
    for offset, item in enumerate(evidence):
        day = first + timedelta(days=offset)
        if item.participation.day != day or (item.is_open is not None and type(item.is_open) is not bool):
            raise ValueError("Coverage evidence has invalid or unordered dates")
        published = item.published
        if published is not None and published.fact.day != day:
            raise ValueError("Published return does not match the evidence date")
        participates = item.participation.participates
        result, state, reason, valued = ProfitResult("Empty", None, None, None), "Empty", None, None
        if not participates or item.is_open is False:
            if published is not None and published.fact.result.status != "Empty":
                raise ValueError("Published profit contradicts participation/calendar evidence")
            reason = "当前范围无持仓或成交" if not participates else "非交易日"
        elif item.is_open is None or published is None:
            state = "Error" if item.is_open is None else missing_state
            reason = "交易日历尚不可确认" if item.is_open is None else missing_reason
            result = ProfitResult("Delayed", None, None, None, reason)
            issues.append(state)
            prefix_complete = False
        else:
            if published.fact.result.status != "Ready":
                raise ValueError("Participating published day lacks a valid return")
            result, state, valued = published.fact.result, "Ready", published.valuation_at
            valuation_at = valued if valuation_at is None else max(valuation_at, valued)
            if prefix_complete:
                complete_through = day
        days.append(CoveredReturnDay(day, result, state, reason, valued))
    has_results = any(day.data_status == "Ready" for day in days)
    state = ("Partial" if has_results else "Error" if "Error" in issues else
             "Recalculating" if "Recalculating" in issues else "Delayed") if issues else (
             "Ready" if has_results else "Empty")
    reason = (next(day.reason for day in days if day.data_status not in ("Ready", "Empty")) if issues else
              None if has_results else "当前范围无有效收益日")
    account = AccountCoverage(accountId=scope.account.accountId, initializedOn=scope.initialized_on.isoformat(),
        effectiveStartDate=first.isoformat() if first else None, targetThroughDate=last.isoformat() if last else None,
        calculatedThroughDate=complete_through.isoformat() if complete_through else None,
        valuationAt=valuation_at.isoformat() if valuation_at else None, dataStatus=state, reason=reason)
    return AccountReturnCoverage(Coverage(dataStatus=state, reason=reason, isFinal=not issues, accounts=[account]), tuple(days))
