"""Single-account/single-stock range reduction; whole-account capital is separate."""
from dataclasses import dataclass, replace
from datetime import date, timedelta

from src.biz.schemas.wealth.market.trading_assistant.common import AccountCoverage, Coverage

from src.biz.services.wealth.market.trading_assistant.calculation.periods import stock_period_return
from src.biz.services.wealth.market.trading_assistant.calculation.returns import ProfitResult, profit_result
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader, MarketFactsUnavailable
from .return_coverage import ReturnDayEvidence, cover_return_days
from .return_days import PublishedReturnDaysQuery, PublishedReturnsUnavailable
from .return_scope import ReturnScopeQuery
from .return_statistics import DailyReturnFact
from .return_stock_days import PublishedStockReturnDaysQuery
from .calculation_status import CalculationStatusQuery


@dataclass(frozen=True, slots=True)
class StockPeriodRead:
    result: ProfitResult
    coverage: Coverage


class StockPeriodReturnsQuery:
    def __init__(self, policy):
        self.policy = policy
        self.scopes = ReturnScopeQuery(policy)
        self.days = PublishedReturnDaysQuery(policy)
        self.stocks = PublishedStockReturnDaysQuery(policy)
        self.market = MarketFactsReader(policy)
        self.status = CalculationStatusQuery(policy)

    def read(self, session, *, owner_id, basis, account_id, stock, start, end, today, deadline):
        """An internal range reader. Page-sized evidence is reduced immediately.

        No historical transaction arrays or daily denominators are retained.
        The caller chooses a natural week/month or the literal review range.
        """
        if not stock or any(type(d) is not date for d in (start, end, today)) or start > end:
            raise ValueError("Invalid single-stock range")
        scope = self.scopes.read(session, owner_id=owner_id, basis=basis, account_id=account_id,
                                 stock=stock, deadline=deadline)
        first = max(start, scope.history_start) if scope.history_start else None
        last = min(end, today)
        if first is None or first > last:
            coverage = cover_return_days(scope, start=start, end=end, today=today, evidence=()).coverage
            return StockPeriodRead(profit_result(0, 0, participates=False), coverage)
        opening = investment = profit = 0
        has_stock = has_ready = False
        missing = False
        reason = None
        error = False
        through = valuation = None
        unavailable_state, unavailable_reason = None, None
        begin = first
        while begin <= last:
            deadline.remaining_ms()
            finish = min(last, begin + timedelta(days=self.policy.page_rows - 1))
            participation = self.scopes.participation(session, scope=scope, start=begin, end=finish, deadline=deadline)
            try:
                calendar = {day.trade_date: day.is_open for day in self.market.read_calendar(session, "SSE", begin, finish, deadline).days}
            except MarketFactsUnavailable:
                calendar = {}
            try:
                published = {item.fact.day: item for item in self.days.page(session, basis=basis,
                    account_id=account_id, start=begin, end=finish, deadline=deadline).items}
            except PublishedReturnsUnavailable:
                published = {}
            if unavailable_state is None and any(p.participates and calendar.get(p.day) and p.day not in published for p in participation):
                progress = self.status.read(session, owner_id=owner_id, account_id=account_id, deadline=deadline)
                unavailable_state = "Error" if progress.stage == "FAILED" else (
                    "Delayed" if progress.stage in ("WAITING_DATA", "PUBLISHED") else "Recalculating")
                unavailable_reason = progress.reason or "目标日期收益尚未就绪"
            evidence = []
            for item in participation:
                snapshot = published.get(item.day) if item.participates and calendar.get(item.day) else None
                if snapshot is not None:
                    page = self.stocks.page(session, owner_id=owner_id, basis=basis, account_id=account_id,
                        day=item.day, stock=stock, deadline=deadline)
                    if len(page.items) != 1 or page.next_stock is not None:
                        raise ValueError("Participating stock lacks its unique published day")
                    value = page.items[0]
                    if not has_stock:
                        opening = value.opening_cost_cents
                        has_stock = True
                    investment += value.initial_cost_cents + value.buy_input_cents
                    profit += value.result.profit_cents
                    snapshot = replace(snapshot, fact=DailyReturnFact(item.day, value.result))
                evidence.append(ReturnDayEvidence(item, calendar.get(item.day), snapshot))
            covered = cover_return_days(scope, start=begin, end=finish, today=today, evidence=tuple(evidence),
                missing_state=unavailable_state or "Delayed", missing_reason=unavailable_reason or "目标日期收益尚未就绪")
            account = covered.coverage.accounts[0]
            page_missing = any(d.data_status not in ("Ready", "Empty") for d in covered.days)
            has_ready = has_ready or any(d.data_status == "Ready" for d in covered.days)
            if not missing and account.calculatedThroughDate is not None:
                through = account.calculatedThroughDate
            missing = missing or page_missing
            if page_missing and reason is None:
                reason = covered.coverage.reason
            error = error or any(d.data_status == "Error" for d in covered.days)
            if account.valuationAt is not None:
                valuation = account.valuationAt
            begin = finish + timedelta(days=1)
        # Only the first participating day's opening cost is carried. Subsequent
        # days add new investments, never their opening pools/daily denominators.
        result = (ProfitResult("Delayed", None, None, None, reason) if missing else
                  stock_period_return(opening, investment, profit, participates=has_stock))
        state = ("Partial" if has_ready else "Error" if error else unavailable_state or "Delayed") if missing else (
            "Ready" if has_ready else "Empty")
        account = AccountCoverage(accountId=str(account_id), initializedOn=scope.initialized_on.isoformat(),
            effectiveStartDate=first.isoformat(), targetThroughDate=last.isoformat(),
            calculatedThroughDate=through, valuationAt=valuation, dataStatus=state, reason=reason)
        return StockPeriodRead(result, Coverage(dataStatus=state, reason=reason, isFinal=not missing, accounts=[account]))
