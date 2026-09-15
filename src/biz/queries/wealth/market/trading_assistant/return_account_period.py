"""Whole-account range returns using §6.4 cash reuse, never summed day capital."""
from dataclasses import dataclass, replace
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult, PositionState
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from src.biz.schemas.wealth.market.trading_assistant.common import AccountCoverage, Coverage
from src.biz.services.wealth.market.trading_assistant.calculation.periods import advance_return_period, start_return_period, finish_return_period
from src.biz.services.wealth.market.trading_assistant.calculation.returns import ProfitResult, profit_result
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader, MarketFactsUnavailable, apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents, numeric_integer
from .calculation_status import CalculationStatusQuery
from .return_cash import ReturnCashQuery
from .return_coverage import ReturnDayEvidence, cover_return_days
from .return_days import PublishedReturnDaysQuery, PublishedReturnsUnavailable
from .return_scope import ReturnScopeQuery


@dataclass(frozen=True, slots=True)
class AccountPeriodRead:
    result: ProfitResult
    coverage: Coverage
    closing_cash_cents: int | None


class AccountPeriodReturnsQuery:
    def __init__(self, policy):
        self.policy = policy
        self.scopes, self.cash = ReturnScopeQuery(policy), ReturnCashQuery(policy)
        self.days, self.market = PublishedReturnDaysQuery(policy), MarketFactsReader(policy)
        self.status = CalculationStatusQuery(policy)

    def _opening_cost(self, session, *, basis, account_id, start, quantity, deadline):
        if quantity == 0:
            return 0
        ref = next(ref for ref in basis.context.accounts if ref.accountId == str(account_id))
        if ref.publishedGenerationId is None:
            return None
        generation = UUID(ref.publishedGenerationId)
        apply_sql_budget(session, deadline, self.policy)
        compatible = session.scalar(select(CalculationGeneration.generation_id).where(
            CalculationGeneration.account_id == account_id, CalculationGeneration.generation_id == generation,
            CalculationGeneration.fact_version == int(ref.factVersion),
            CalculationGeneration.target_version == int(ref.calculationTargetVersion), CalculationGeneration.stage == "PUBLISHED"))
        if compatible is None:
            return None
        previous = select(func.max(PublicationDay.trade_date)).where(PublicationDay.account_id == account_id,
            PublicationDay.generation_id == generation, PublicationDay.trade_date < start).scalar_subquery()
        apply_sql_budget(session, deadline, self.policy)
        total_quantity, cost = session.execute(select(func.sum(PositionState.quantity), func.sum(PositionState.remaining_buy_cost))
            .join(PublicationDay, and_(PublicationDay.account_id == PositionState.account_id,
                PublicationDay.day_result_id == PositionState.day_result_id))
            .join(DayResult, and_(DayResult.account_id == PublicationDay.account_id,
                DayResult.day_result_id == PublicationDay.day_result_id, DayResult.trade_date == PublicationDay.trade_date))
            .where(PublicationDay.account_id == account_id, PublicationDay.generation_id == generation,
                PublicationDay.trade_date == previous, DayResult.status == "SEALED")).one()
        if total_quantity is None or numeric_integer(total_quantity) != quantity or cost is None:
            raise ValueError("Published opening cost does not match effective opening holdings")
        return numeric_cents(cost)

    def read(self, session, *, owner_id, basis, account_id, start, end, today, deadline):
        if any(type(d) is not date for d in (start, end, today)) or start > end:
            raise ValueError("Invalid whole-account return range")
        scope = self.scopes.read(session, owner_id=owner_id, basis=basis, account_id=account_id, deadline=deadline)
        first, last = max(start, scope.history_start), min(end, today)
        if first > last:
            covered = cover_return_days(scope, start=start, end=end, today=today, evidence=())
            return AccountPeriodRead(profit_result(0, 0, participates=False), covered.coverage, None)
        initial_cash, cash = self.cash.opening(session, scope=scope, start=first, deadline=deadline)
        state = None
        has_ready = missing = error = False
        reason = through = valuation = unavailable_state = unavailable_reason = None
        begin = first
        while begin <= last:
            deadline.remaining_ms()
            finish = min(last, begin + timedelta(days=self.policy.page_rows - 1))
            participation = self.scopes.participation(session, scope=scope, start=begin, end=finish, deadline=deadline)
            if begin == first:
                cost = self._opening_cost(session, basis=basis, account_id=account_id, start=first,
                    quantity=participation[0].opening_quantity, deadline=deadline)
                if cost is not None:
                    state = start_return_period(str(account_id), cash if cash is not None else 0, cost)
            cash_days = self.cash.page(session, scope=scope, start=begin, end=finish,
                opening_cash_cents=cash, initial_cash_cents=initial_cash, deadline=deadline)
            try:
                calendar = {d.trade_date: d.is_open for d in self.market.read_calendar(session, "SSE", begin, finish, deadline).days}
            except MarketFactsUnavailable:
                calendar = {}
            try:
                published = {d.fact.day: d for d in self.days.page(session, basis=basis,
                    account_id=account_id, start=begin, end=finish, deadline=deadline).items}
            except PublishedReturnsUnavailable:
                published = {}
            if unavailable_state is None and any(p.participates and calendar.get(p.day) and p.day not in published for p in participation):
                progress = self.status.read(session, owner_id=owner_id, account_id=account_id, deadline=deadline)
                unavailable_state = "Error" if progress.stage == "FAILED" else (
                    "Delayed" if progress.stage in ("WAITING_DATA", "PUBLISHED") else "Recalculating")
                unavailable_reason = progress.reason or "目标日期收益尚未就绪"
            evidence = tuple(ReturnDayEvidence(p, calendar.get(p.day),
                published.get(p.day) if calendar.get(p.day) else None) for p in participation)
            covered = cover_return_days(scope, start=begin, end=finish, today=today, evidence=evidence,
                missing_state=unavailable_state or "Delayed", missing_reason=unavailable_reason or "目标日期收益尚未就绪")
            for fact, day in zip(cash_days, covered.days, strict=True):
                cash = fact.cash.closing_cash_cents if fact.cash else None
                snapshot = published.get(fact.day)
                if snapshot is not None and snapshot.cash_cents != cash:
                    raise ValueError("Published cash differs from current effective cash facts")
                if state is None:
                    continue
                state = replace(state, capital=replace(state.capital,
                    idle_cash_cents=state.capital.idle_cash_cents + fact.initial_cash_cents,
                    principal_cents=state.capital.principal_cents + fact.initial_cost_cents))
                if fact.cash is not None:
                    state = advance_return_period(state, fact.cash, day.result)
                else:
                    # Cash stays unknown before registration. Only known stock
                    # capital and profit are accumulated; no fake zero balance.
                    profit = None if state.profit_cents is None or day.result.status == "Delayed" else (
                        state.profit_cents + (day.result.profit_cents or 0))
                    state = replace(state, profit_cents=profit)
            account = covered.coverage.accounts[0]
            page_missing = any(d.data_status not in ("Ready", "Empty") for d in covered.days)
            has_ready = has_ready or any(d.data_status == "Ready" for d in covered.days)
            if not missing and account.calculatedThroughDate is not None:
                through = account.calculatedThroughDate
            missing = missing or page_missing
            if page_missing and reason is None:
                reason = covered.coverage.reason
            error = error or any(d.data_status == "Error" for d in covered.days)
            valuation = account.valuationAt or valuation
            begin = finish + timedelta(days=1)
        if not missing and has_ready and state is None:
            raise ValueError("Ready return has no opening capital")
        result = (ProfitResult("Delayed", None, None, None, reason) if missing else
            finish_return_period(state) if has_ready else profit_result(0, 0, participates=False))
        status = ("Partial" if has_ready else "Error" if error else unavailable_state or "Delayed") if missing else (
            "Ready" if has_ready else "Empty")
        account = AccountCoverage(accountId=str(account_id), initializedOn=scope.initialized_on.isoformat(),
            effectiveStartDate=first.isoformat(), targetThroughDate=last.isoformat(), calculatedThroughDate=through,
            valuationAt=valuation, dataStatus=status, reason=reason)
        return AccountPeriodRead(result, Coverage(dataStatus=status, reason=reason, isFinal=not missing, accounts=[account]), cash)
