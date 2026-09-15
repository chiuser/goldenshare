"""Exact selected-range review, with three independently ready summaries."""
from datetime import date

from src.biz.schemas.wealth.market.trading_assistant.returns import ReviewResponse
from src.biz.schemas.wealth.market.trading_assistant.scopes import CurveQuery, RangeRecordsQuery
from src.biz.schemas.wealth.market.trading_assistant.value_types import decimal_cents
from src.biz.services.wealth.market.trading_assistant.calculation.returns import ProfitResult, profit_result
from .completed_rounds import CompletedRoundsQuery
from .record_summary import RecordSummaryQuery
from .return_curve import ReturnCurveQuery
from .return_statistics import DailyReturnFact, summarize_daily_returns


class ReturnReviewQuery:
    def __init__(self, policy):
        self.curve = ReturnCurveQuery(policy)
        self.records = RecordSummaryQuery(policy)
        self.rounds = CompletedRoundsQuery(policy)

    def read(self, session, *, owner_id, basis, query, cutoff, deadline):
        params = query.model_dump(exclude_unset=True)
        daily = self.curve.read(session, owner_id=owner_id, basis=basis, cutoff=cutoff, deadline=deadline,
            query=CurveQuery(**params, granularity="DAY"))
        facts = (DailyReturnFact(date.fromisoformat(point.periodStartDate),
            profit_result(decimal_cents(point.profitAmount), decimal_cents(point.capitalAmount), participates=True)
            if point.profitAmount is not None else profit_result(0, 0, participates=False)
            if point.dataStatus == "Empty" else ProfitResult("Delayed", None, None, None, point.reason))
            for point in daily.points)
        stats = summarize_daily_returns(facts, start=date.fromisoformat(query.requestedStartDate),
            end=date.fromisoformat(query.requestedEndDate), coverage=daily.coverage)
        closed = self.records.read(session, owner_id=owner_id, basis=basis, query=query, deadline=deadline)
        rounds = self.rounds.read(session, owner_id=owner_id, basis=basis,
            query=RangeRecordsQuery(**params, limit=1), deadline=deadline)
        deadline.remaining_ms()
        return ReviewResponse(scope=daily.scope, requestedStartDate=query.requestedStartDate,
            requestedEndDate=query.requestedEndDate, readContext=basis.context, coverage=daily.coverage,
            dailyStats=stats, closedTrades=dict(closedTradeCount=closed.closedTradeCount,
                dataStatus=closed.closedDataStatus, reason=closed.reason),
            completedRounds=dict(completedRoundCount=rounds.completedRoundCount,
                dataStatus=rounds.coverage.dataStatus, reason=rounds.coverage.reason))
