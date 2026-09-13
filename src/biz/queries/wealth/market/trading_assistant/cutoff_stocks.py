"""Account stock scope before a generation exists; quantities only, paged SQL."""
from sqlalchemy import case, func, select, union, union_all

from src.biz.models.wealth.trading_assistant.accounts import InitialPosition
from .effective_ledger import effective_ledger


def cutoff_stock_page(*, account, business_date, after, policy):
    facts = effective_ledger(owner_id=account.owner_id, account_id=account.account_id,
        fact_version=account.fact_version)
    initial = select(InitialPosition.ts_code, InitialPosition.quantity).where(
        InitialPosition.account_id == account.account_id,
        InitialPosition.initialization_id == account.current_initialization_id,
        InitialPosition.opened_on < business_date)
    trades = select(facts.c.ts_code, case((facts.c.direction == "BUY", facts.c.quantity),
        else_=-facts.c.quantity).label("quantity")).where(
            facts.c.kind == "TRADE", facts.c.occurred_on < business_date)
    changes = union_all(initial, trades).subquery("opening_quantity_changes")
    held = select(changes.c.ts_code).group_by(changes.c.ts_code).having(func.sum(changes.c.quantity) > 0)
    initialized = select(InitialPosition.ts_code).where(InitialPosition.account_id == account.account_id,
        InitialPosition.initialization_id == account.current_initialization_id,
        InitialPosition.opened_on == business_date)
    traded = select(facts.c.ts_code).where(facts.c.kind == "TRADE", facts.c.occurred_on == business_date)
    scope = union(held, initialized, traded).subquery("cutoff_stock_scope")
    query = select(scope.c.ts_code)
    if after is not None:
        query = query.where(scope.c.ts_code > after)
    return query.order_by(scope.c.ts_code).limit(policy.page_rows)
