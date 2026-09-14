"""Record SQL facts: effective revisions first; only fixed sealed publications."""
from uuid import UUID

from sqlalchemy import and_, false, func, literal, select, union_all, Uuid

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, ClosedTrade, DayResult
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from .effective_ledger import effective_ledger


def record_facts(*, owner_id, basis):
    """Union account-local effective facts, not their paginated fragments."""
    statements = []
    for ref in basis.context.accounts:
        facts = effective_ledger(owner_id=owner_id, account_id=UUID(ref.accountId), fact_version=int(ref.factVersion))
        statements.append(select(facts,
            literal(UUID(ref.publishedGenerationId) if ref.publishedGenerationId else None, type_=Uuid).label("published_id"),
            literal(int(ref.factVersion)).label("basis_fact_version"),
            literal(int(ref.calculationTargetVersion)).label("basis_target_version")))
    if not statements:
        facts = effective_ledger(owner_id=owner_id, account_id=UUID(int=0), fact_version=1)
        statements.append(select(facts, literal(None, type_=Uuid).label("published_id"),
            literal(1).label("basis_fact_version"), literal(1).label("basis_target_version")).where(false()))
    return (union_all(*statements) if len(statements) > 1 else statements[0]).subquery("record_facts")


def with_published_closed(facts):
    """A stale generation, candidate or mismatched sell revision cannot join."""
    generation = CalculationGeneration
    day = PublicationDay
    closed = ClosedTrade
    return select(facts,
        closed.allocated_cost, closed.profit_amount.label("closed_profit_amount"),
        closed.return_pct.label("closed_return_pct"), closed.day_result_id,
        closed.round_id, closed.sell_ledger_id.label("closed_source_id"),
    ).select_from(facts).outerjoin(generation, and_(
        generation.account_id == facts.c.account_id, generation.generation_id == facts.c.published_id,
        generation.fact_version == facts.c.basis_fact_version,
        generation.target_version == facts.c.basis_target_version, generation.stage == "PUBLISHED",
    )).outerjoin(day, and_(day.account_id == generation.account_id,
        day.generation_id == generation.generation_id, day.trade_date == facts.c.occurred_on,
    )).outerjoin(DayResult, and_(DayResult.account_id == day.account_id,
        DayResult.day_result_id == day.day_result_id, DayResult.status == "SEALED",
    )).outerjoin(closed, and_(closed.account_id == DayResult.account_id,
        closed.day_result_id == DayResult.day_result_id, closed.sell_ledger_id == facts.c.ledger_id,
        closed.sell_revision == facts.c.revision, facts.c.kind == "TRADE", facts.c.direction == "SELL",
    )).subquery("records_with_closed")


def filtered_records(facts, *, kind, start, end, stock=None, direction=None):
    query = select(facts).where(facts.c.kind == kind, facts.c.occurred_on >= start, facts.c.occurred_on <= end)
    if stock is not None:
        if kind != "TRADE":
            raise ValueError("Cash records do not accept stock filters")
        query = query.where(facts.c.ts_code == stock)
    if direction is not None:
        query = query.where(facts.c.direction == direction)
    return query.subquery("filtered_records")


def trade_day_groups(facts):
    """Aggregate before applying the output cursor or page limit."""
    keys = [facts.c.account_id, facts.c.occurred_on, facts.c.ts_code, facts.c.direction]
    return select(*keys, func.sum(facts.c.quantity).label("quantity"),
        func.sum(facts.c.gross_amount).label("gross_amount"),
        func.sum(facts.c.commission_amount).label("commission_amount"),
        func.sum(facts.c.stamp_tax_amount).label("stamp_tax_amount"),
        func.sum(facts.c.net_cash_change).label("net_cash_change"),
        func.count().label("trade_count"), func.count(facts.c.closed_source_id).label("closed_count"),
        func.sum(facts.c.allocated_cost).label("allocated_cost"),
        func.sum(facts.c.closed_profit_amount).label("closed_profit_amount"),
    ).where(facts.c.kind == "TRADE").group_by(*keys).subquery("trade_day_groups")
