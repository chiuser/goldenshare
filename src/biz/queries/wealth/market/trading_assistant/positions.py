"""Compose owned facts, fixed publication and exact chart/detail contracts."""
from collections import defaultdict

from sqlalchemy import select

from src.foundation.models.core_serving.security_serving import Security
from src.biz.schemas.wealth.market.trading_assistant.common import AccountCoverage, AccountRef, Coverage, Scope, StockRef
from src.biz.schemas.wealth.market.trading_assistant.positions import PositionDetail, PositionsResponse
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .calculation_status import CalculationStatusQuery
from .current_positions import PublishedPositionsUnavailable
from .positions_facts import PositionsFactsQuery
from .positions_industry import PositionsIndustryQuery
from .positions_projection import HoldingPart, account_round, combined_status, holding_row, summarize
from .positions_published import PositionsPublishedQuery


class PositionsQuery:
    def __init__(self, policy):
        self.policy = policy
        self.facts = PositionsFactsQuery(policy)
        self.published = PositionsPublishedQuery(policy)
        self.industry = PositionsIndustryQuery(policy)
        self.status = CalculationStatusQuery(policy)

    def read(self, session, *, owner_id, account_mode, basis, cutoff, deadline, stock_code=None):
        grouped, account_refs, covers, snapshots = defaultdict(list), [], [], []
        cash = 0
        for reference in basis.context.accounts:
            facts = self.facts.read(session, owner_id=owner_id, reference=reference, cutoff=cutoff, deadline=deadline)
            account = facts.account
            ref = AccountRef(accountId=str(account.account_id), name=account.name, brokerName=account.broker_name)
            account_refs.append(ref)
            cash += facts.cash_cents
            published, snapshot, state, reason = {}, None, "Ready", cutoff.reason
            try:
                published, snapshot = self.published.read(session, basis=basis, account=account,
                                                         cutoff=cutoff, deadline=deadline)
            except PublishedPositionsUnavailable as error:
                progress = self.status.read(session, owner_id=owner_id, account_id=account.account_id, deadline=deadline)
                state = ("Error" if progress.stage == "FAILED" else "Delayed"
                         if progress.stage in ("WAITING_DATA", "PUBLISHED") else "Recalculating")
                reason = progress.reason or str(error)
            if cutoff.reason:
                state, reason = "Error", cutoff.reason
            elif cutoff.is_open and cutoff.valuation_date != cutoff.today and facts.holdings:
                if state == "Ready":
                    state, reason = "Delayed", "当日收盘结果尚未就绪，持仓估值时间见各行"
            # A publication matching the full accepted fact version must also
            # agree on current quantities. Do not quietly combine contradictory facts.
            for fact in facts.holdings:
                value = published.get(fact.ts_code)
                if value is not None and value.value.quantity != fact.quantity:
                    raise ValueError("Published holdings disagree with the accepted fact version")
                if published and value is None:
                    raise ValueError("Published current holding is missing an accepted stock")
                grouped[fact.ts_code].append(HoldingPart(ref, fact, value, state, reason))
            if set(published) - {fact.ts_code for fact in facts.holdings}:
                raise ValueError("Published holdings contain stocks absent from current facts")
            snapshots.append(snapshot)
            through = cutoff.valuation_date
            start = min([account.initialized_on] + [item.value.opened_on for item in published.values()])
            has_range = through is not None and start <= through
            covers.append(AccountCoverage(accountId=ref.accountId, initializedOn=account.initialized_on.isoformat(),
                effectiveStartDate=start.isoformat() if has_range else None,
                targetThroughDate=through.isoformat() if has_range else None,
                calculatedThroughDate=through.isoformat() if published or snapshot is not None else None,
                valuationAt=min((item.value.quote_at.isoformat() for item in published.values()), default=None),
                dataStatus=state, reason=reason))
        codes = sorted(grouped)
        names = self._names(session, codes, deadline)
        scope = Scope(accountMode=account_mode, accounts=account_refs, stockMode="ALL", stockRef=None)
        coverage_state = combined_status([cover.dataStatus for cover in covers])
        coverage = Coverage(dataStatus=coverage_state,
            reason=next((cover.reason for cover in covers if cover.reason), None),
            isFinal=coverage_state in ("Ready", "Empty"), accounts=covers)
        if stock_code is not None:
            if stock_code not in grouped:
                raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
            stock = StockRef(tsCode=stock_code, name=names[stock_code])
            return PositionDetail(scope=scope.model_copy(update={"stockMode":"SINGLE", "stockRef":stock}),
                readContext=basis.context, coverage=coverage, stockRef=stock,
                accountRounds=[account_round(part) for part in grouped[stock_code] if part.published is not None])
        industry = self.industry.read(session, codes=codes, trade_date=cutoff.valuation_date, deadline=deadline)
        rows = [holding_row(StockRef(tsCode=code, name=names[code]), grouped[code], industry[code]) for code in codes]
        rows, summary, allocation = summarize(rows, cash=cash,
            parts=[part for parts in grouped.values() for part in parts], day_snapshots=snapshots,
            is_today=cutoff.valuation_date == cutoff.today)
        if any(item.reason for item in industry.values()):
            coverage = coverage.model_copy(update={"dataStatus":"Partial", "isFinal":False,
                "reason":"部分股票行业分类存在冲突，持仓金额仍按核算结果展示"})
        return PositionsResponse(scope=scope, readContext=basis.context, coverage=coverage,
                                 items=rows, summary=summary, allocation=allocation)

    def _names(self, session, codes, deadline):
        result = {}
        for offset in range(0, len(codes), self.policy.page_rows):
            apply_sql_budget(session, deadline, self.policy)
            result.update(session.execute(select(Security.ts_code, Security.name).where(
                Security.ts_code.in_(codes[offset:offset + self.policy.page_rows]))).all())
        if set(result) != set(codes) or any(not name for name in result.values()):
            raise ValueError("Accepted stocks have incomplete security identities")
        return result
