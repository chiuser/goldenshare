"""Approved curve periods and scope coverage within one fixed read context."""
from datetime import date
from uuid import UUID

from src.biz.schemas.wealth.market.trading_assistant.common import AccountCoverage, Coverage
from src.biz.schemas.wealth.market.trading_assistant.returns import CurvePoint, CurveResponse
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from .record_scope import read_record_scope
from .return_periods import PeriodReturnsQuery
from .return_scope import ReturnScopeQuery
from .return_windows import curve_windows


def curve_coverage(points):
    """Fold ordered point coverage without crossing any account's first gap."""
    accounts, blocked = {}, set()
    for point in points:
        for current in point.accounts:
            key = current.accountId
            previous = accounts.get(key)
            issue = current.dataStatus not in ("Ready", "Empty")
            if previous is None:
                accounts[key] = current
            else:
                statuses = {previous.dataStatus, current.dataStatus}
                incomplete = bool(statuses - {"Ready", "Empty"})
                ready = bool(statuses & {"Ready", "Partial"})
                status = ("Partial" if ready else "Error" if "Error" in statuses else
                    "Recalculating" if "Recalculating" in statuses else "Delayed") if incomplete else (
                    "Ready" if ready else "Empty")
                accounts[key] = AccountCoverage(accountId=key, initializedOn=previous.initializedOn,
                    effectiveStartDate=previous.effectiveStartDate or current.effectiveStartDate,
                    targetThroughDate=current.targetThroughDate or previous.targetThroughDate,
                    calculatedThroughDate=previous.calculatedThroughDate if key in blocked else (
                        current.calculatedThroughDate or previous.calculatedThroughDate),
                    valuationAt=current.valuationAt or previous.valuationAt, dataStatus=status,
                    reason=previous.reason if key in blocked else current.reason if issue else None)
            if issue:
                blocked.add(key)
    values = list(accounts.values())
    issues = [a for a in values if a.dataStatus not in ("Ready", "Empty")]
    ready = any(a.dataStatus in ("Ready", "Partial") for a in values)
    status = ("Partial" if ready else "Error" if any(a.dataStatus == "Error" for a in issues) else
        "Recalculating" if any(a.dataStatus == "Recalculating" for a in issues) else "Delayed") if issues else (
        "Ready" if ready else "Empty")
    return Coverage(dataStatus=status, reason=issues[0].reason if issues else None,
                    isFinal=not issues, accounts=values)


class ReturnCurveQuery:
    def __init__(self, policy):
        self.policy = policy
        self.periods = PeriodReturnsQuery(policy)
        self.history = ReturnScopeQuery(policy)

    def read(self, session, *, owner_id, basis, query, cutoff, deadline):
        scope, _ = read_record_scope(session, owner_id=owner_id, basis=basis, query=query,
                                     deadline=deadline, policy=self.policy)
        start, end = date.fromisoformat(query.requestedStartDate), date.fromisoformat(query.requestedEndDate)
        history_start = None
        for reference in basis.context.accounts:
            deadline.remaining_ms()
            account_scope = self.history.read(session, owner_id=owner_id, basis=basis,
                account_id=UUID(reference.accountId), stock=query.tsCode, deadline=deadline)
            first = account_scope.history_start
            if first is not None:
                history_start = first if history_start is None else min(history_start, first)
        points = []
        for window in curve_windows(start, end, granularity=query.granularity, today=cutoff.today):
            deadline.remaining_ms()
            period = self.periods.read(session, owner_id=owner_id, basis=basis, start=window.start,
                end=window.end, today=cutoff.today, stock=query.tsCode, deadline=deadline)
            result = period.result
            points.append(CurvePoint(**period.coverage.model_dump(), periodStartDate=window.start.isoformat(),
                periodEndDate=window.end.isoformat(), isPeriodEnded=window.is_ended,
                profitAmount=format_cents(result.profit_cents) if result.status == "Ready" else None,
                capitalAmount=format_cents(result.capital_cents) if result.status == "Ready" else None,
                returnPct=result.return_pct))
        deadline.remaining_ms()
        return CurveResponse(scope=scope, requestedStartDate=query.requestedStartDate,
            historyStartDate=history_start.isoformat() if history_start else None,
            requestedEndDate=query.requestedEndDate, granularity=query.granularity,
            readContext=basis.context, coverage=curve_coverage(points), points=points)
