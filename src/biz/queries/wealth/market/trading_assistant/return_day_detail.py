"""One day's account returns, original fees and closed summary, design §4.12.4."""
from uuid import UUID

from sqlalchemy import func, select

from src.biz.schemas.wealth.market.trading_assistant.common import Coverage
from src.biz.schemas.wealth.market.trading_assistant.returns import DayDetail
from src.biz.schemas.wealth.market.trading_assistant.scopes import DayScope, RangeQuery, RangeRecordsScope
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.calculation.returns import aggregate_returns, profit_result
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader, MarketFactsUnavailable, apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from .calculation_status import CalculationStatusQuery
from .record_sources import record_facts
from .record_summary import RecordSummaryQuery
from .return_coverage import ReturnDayEvidence, cover_return_days
from .return_days import PublishedReturnDaysQuery, PublishedReturnsUnavailable
from .return_scope import ReturnScopeQuery


class ReturnDayDetailQuery:
    def __init__(self, policy):
        self.policy = policy
        self.scopes = ReturnScopeQuery(policy)
        self.published = PublishedReturnDaysQuery(policy)
        self.market = MarketFactsReader(policy)
        self.status = CalculationStatusQuery(policy)
        self.summary = RecordSummaryQuery(policy)

    def read(self, session, *, owner_id, account_mode, basis, cutoff, deadline, day):
        covers, results = [], []
        calendar_read, is_open = False, None
        for reference in basis.context.accounts:
            account_id = UUID(reference.accountId)
            scope = self.scopes.read(session, owner_id=owner_id, basis=basis,
                                     account_id=account_id, deadline=deadline)
            evidence, state, reason = (), "Delayed", "目标日期收益尚未就绪"
            if scope.history_start is not None and scope.history_start <= day <= cutoff.today:
                participation = self.scopes.participation(session, scope=scope, start=day, end=day, deadline=deadline)[0]
                if not calendar_read:
                    try:
                        is_open = self.market.read_calendar(session, "SSE", day, day, deadline).days[0].is_open
                    except MarketFactsUnavailable:
                        is_open = None
                    calendar_read = True
                published = None
                if participation.participates and is_open:
                    try:
                        rows = self.published.page(session, basis=basis, account_id=account_id,
                                                   start=day, end=day, deadline=deadline).items
                        published = rows[0] if rows else None
                    except PublishedReturnsUnavailable:
                        pass  # Absence is classified below; other query failures must propagate.
                    if published is None:
                        progress = self.status.read(session, owner_id=owner_id, account_id=account_id, deadline=deadline)
                        state = "Error" if progress.stage == "FAILED" else (
                            "Delayed" if progress.stage in ("WAITING_DATA", "PUBLISHED") else "Recalculating")
                        reason = progress.reason or reason
                evidence = (ReturnDayEvidence(participation, is_open, published),)
            covered = cover_return_days(scope, start=day, end=day, today=cutoff.today,
                evidence=evidence, missing_state=state, missing_reason=reason)
            covers.extend(covered.coverage.accounts)
            results.append(covered.days[0].result if covered.days else profit_result(0, 0, participates=False))
        issues = [cover for cover in covers if cover.dataStatus not in ("Ready", "Empty")]
        has_ready = any(cover.dataStatus == "Ready" for cover in covers)
        state = ("Partial" if has_ready else "Error" if any(c.dataStatus == "Error" for c in issues) else
                 "Recalculating" if any(c.dataStatus == "Recalculating" for c in issues) else "Delayed") if issues else (
                 "Ready" if has_ready else "Empty")
        coverage = Coverage(dataStatus=state, reason=issues[0].reason if issues else (
            None if has_ready else "当前范围无有效收益日"), isFinal=not issues, accounts=covers)
        result = aggregate_returns(tuple(results))
        params = dict(accountMode=account_mode, stockMode="ALL", requestedStartDate=day.isoformat(),
                      requestedEndDate=day.isoformat())
        if account_mode == "SINGLE":
            params["accountId"] = basis.context.accounts[0].accountId
        summary = self.summary.read(session, owner_id=owner_id, basis=basis, query=RangeQuery(**params), deadline=deadline)
        facts = record_facts(owner_id=owner_id, basis=basis)
        apply_sql_budget(session, deadline, self.policy)
        fees = session.execute(select(func.count(), func.sum(facts.c.commission_amount), func.sum(facts.c.stamp_tax_amount))
            .where(facts.c.kind == "TRADE", facts.c.occurred_on == day)).one()
        money = lambda value: format_cents(numeric_cents(value)) if value is not None else "0.00"
        deadline.remaining_ms()
        return DayDetail(scope=summary.scope, date=day.isoformat(), readContext=basis.context, coverage=coverage,
            profitAmount=format_cents(result.profit_cents) if result.status == "Ready" else None,
            capitalAmount=format_cents(result.capital_cents) if result.status == "Ready" else None,
            returnPct=result.return_pct, closedTradeCount=summary.closedTradeCount,
            closedProfitAmount=summary.closedProfitAmount, closedDataStatus=summary.closedDataStatus,
            commissionAmount=money(fees[1]), stampTaxAmount=money(fees[2]), feeDataStatus="Ready" if fees[0] else "Empty",
            contributionsScope=DayScope(scope=summary.scope, date=day.isoformat()),
            recordsScope=RangeRecordsScope(scope=summary.scope, requestedStartDate=day.isoformat(), requestedEndDate=day.isoformat()))
