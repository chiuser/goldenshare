"""One natural month's ledger grid, independent profit and closed summaries."""
from datetime import date

from src.biz.schemas.wealth.market.trading_assistant.returns import CalendarDay, CalendarResponse, MonthSummary
from src.biz.schemas.wealth.market.trading_assistant.scopes import CurveQuery, RangeQuery
from src.biz.schemas.wealth.market.trading_assistant.common import Coverage
from src.biz.schemas.wealth.market.trading_assistant.value_types import decimal_cents
from src.biz.services.wealth.market.trading_assistant.calculation.returns import ProfitResult, profit_result
from src.biz.services.wealth.market.trading_assistant.calculation.periods import calendar_window
from .return_curve import ReturnCurveQuery, curve_coverage
from .return_statistics import DailyReturnFact, summarize_daily_returns
from .return_windows import calendar_dates
from .record_summary import RecordSummaryQuery


class ReturnCalendarQuery:
    def __init__(self, policy):
        self.curve = ReturnCurveQuery(policy)
        self.records = RecordSummaryQuery(policy)

    def read(self, session, *, owner_id, basis, query, cutoff, deadline):
        first = date.fromisoformat(query.month + "-01")
        _, last = calendar_window(first, "MONTH")
        grid = calendar_dates(first)
        params = dict(accountMode=query.accountMode, stockMode="ALL")
        if query.accountId is not None:
            params["accountId"] = query.accountId
        # Include weekends in the source, even though the visible grid omits
        # them. Monthly statistics follow actual market facts, not five columns.
        begin, end = min(first, grid[0]), max(last, grid[-1])
        daily = self.curve.read(session, owner_id=owner_id, basis=basis, cutoff=cutoff, deadline=deadline,
            query=CurveQuery(**params, requestedStartDate=begin.isoformat(), requestedEndDate=end.isoformat(), granularity="DAY"))
        indexed = {p.periodStartDate:p for p in daily.points}
        month_points = [p for p in daily.points if p.periodStartDate[:7] == query.month]
        daily_coverage = curve_coverage(month_points)
        facts = []
        for point in month_points:
            result = (profit_result(decimal_cents(point.profitAmount), decimal_cents(point.capitalAmount), participates=True)
                if point.profitAmount is not None else profit_result(0, 0, participates=False)
                if point.dataStatus == "Empty" else ProfitResult("Delayed", None, None, None, point.reason))
            facts.append(DailyReturnFact(date.fromisoformat(point.periodStartDate), result))
        statistics = summarize_daily_returns(facts, start=first, end=last, coverage=daily_coverage)
        monthly = self.curve.read(session, owner_id=owner_id, basis=basis, cutoff=cutoff, deadline=deadline,
            query=CurveQuery(**params, requestedStartDate=first.isoformat(), requestedEndDate=last.isoformat(), granularity="MONTH"))
        month = monthly.points[0] if monthly.points else None
        closed = self.records.read(session, owner_id=owner_id, basis=basis, deadline=deadline,
            query=RangeQuery(**params, requestedStartDate=first.isoformat(), requestedEndDate=last.isoformat()))
        days = []
        for day in grid:
            identity = day.isoformat()
            point = indexed.get(identity)
            future = day > cutoff.today
            days.append(CalendarDay(date=identity, inSelectedMonth=identity[:7] == query.month,
                temporalState="FUTURE" if future else "TODAY" if day == cutoff.today else "PAST",
                profitAmount=point.profitAmount if point else None,
                capitalAmount=point.capitalAmount if point else None, returnPct=point.returnPct if point else None,
                calculationState=point.dataStatus if point else None,
                reason=(point.reason or "期间无有效收益结果") if point and point.profitAmount is None else None,
                valuationAt=max((a.valuationAt for a in point.accounts if a.valuationAt), default=None) if point else None,
                readContext=basis.context if point else None))
        closed_coverage = Coverage(dataStatus=closed.closedDataStatus, reason=closed.reason,
            isFinal=closed.closedDataStatus in ("Ready", "Empty"), accounts=[])
        completed = [a.calculatedThroughDate for a in daily_coverage.accounts if a.effectiveStartDate is not None]
        deadline.remaining_ms()
        return CalendarResponse(month=query.month, today=cutoff.today.isoformat(),
            calculatedThrough=min(completed) if completed and all(completed) else None,
            days=days, readContext=basis.context, monthSummary=MonthSummary(
                periodProfitAmount=month.profitAmount if month else None,
                periodCapitalAmount=month.capitalAmount if month else None, periodReturnPct=month.returnPct if month else None,
                positiveDayCount=statistics.positiveDayCount or 0, negativeDayCount=statistics.negativeDayCount or 0,
                flatDayCount=statistics.flatDayCount or 0, computedDayCount=statistics.computedDayCount or 0,
                minDailyReturnPct=statistics.minDailyReturn.returnPct if statistics.minDailyReturn else None,
                minDailyReturnDates=statistics.minDailyReturn.dates if statistics.minDailyReturn else [],
                closedTradeCount=closed.closedTradeCount, closedProfitAmount=closed.closedProfitAmount,
                periodCoverage=monthly.coverage, dailyStatsCoverage=daily_coverage, closedCoverage=closed_coverage))
