"""Range totals from all effective facts, independent of record pagination."""
from datetime import date
from sqlalchemy import and_, func, select

from src.biz.schemas.wealth.market.trading_assistant.records import RecordsSummary
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from .calculation_status import CalculationStatusQuery
from .record_scope import read_record_scope
from .record_sources import record_facts, with_published_closed


class RecordSummaryQuery:
    def __init__(self, policy):
        self.policy = policy
        self.status = CalculationStatusQuery(policy)

    def read(self, session, *, owner_id, basis, query, deadline):
        scope, _ = read_record_scope(session, owner_id=owner_id, basis=basis, query=query, deadline=deadline, policy=self.policy)
        facts = with_published_closed(record_facts(owner_id=owner_id, basis=basis))
        traded = facts.c.kind == "TRADE"
        if query.tsCode is not None:
            traded = and_(traded, facts.c.ts_code == query.tsCode)
        buy, sell = and_(traded, facts.c.direction == "BUY"), and_(traded, facts.c.direction == "SELL")
        cash_in = and_(facts.c.kind == "CASH_FLOW", facts.c.direction == "IN")
        cash_out = and_(facts.c.kind == "CASH_FLOW", facts.c.direction == "OUT")
        count = lambda condition: func.count().filter(condition)
        apply_sql_budget(session, deadline, self.policy)
        row = session.execute(select(count(buy).label("buys"), count(sell).label("sells"),
            count(and_(sell, facts.c.closed_source_id.is_not(None))).label("closed_count"),
            func.sum(facts.c.closed_profit_amount).filter(sell).label("closed_profit"),
            func.sum(facts.c.cash_amount).filter(cash_in).label("cash_in"),
            func.sum(facts.c.cash_amount).filter(cash_out).label("cash_out"),
        ).where(facts.c.occurred_on >= date.fromisoformat(query.requestedStartDate),
                facts.c.occurred_on <= date.fromisoformat(query.requestedEndDate))).one()
        state, reason = ("Ready", None) if row.sells else ("Empty", None)
        complete = row.sells == row.closed_count
        if not complete:
            apply_sql_budget(session, deadline, self.policy)
            ids = session.scalars(select(facts.c.account_id).where(sell, facts.c.closed_source_id.is_(None),
                facts.c.occurred_on >= date.fromisoformat(query.requestedStartDate),
                facts.c.occurred_on <= date.fromisoformat(query.requestedEndDate)).distinct()).all()
            states = [self.status.read(session, owner_id=owner_id, account_id=account_id, deadline=deadline) for account_id in ids]
            state = ("Error" if any(item.stage == "FAILED" for item in states) else "Delayed"
                     if all(item.stage in ("WAITING_DATA", "PUBLISHED") for item in states) else "Recalculating")
            reason = next((item.reason for item in states if item.reason), "闭环结果尚未完整发布")
        money = lambda value: format_cents(numeric_cents(value)) if value is not None else "0.00"
        deadline.remaining_ms()
        return RecordsSummary(scope=scope, requestedStartDate=query.requestedStartDate,
            requestedEndDate=query.requestedEndDate, readContext=basis.context,
            tradeCount=row.buys + row.sells, buyCount=row.buys, sellCount=row.sells,
            cashInAmount=money(row.cash_in), cashOutAmount=money(row.cash_out),
            closedTradeCount=row.closed_count if complete else None,
            closedProfitAmount=money(row.closed_profit) if complete else None,
            closedDataStatus=state, reason=reason)
