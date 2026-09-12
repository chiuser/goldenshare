"""The complete stock scope is formed before keyset pagination."""
from sqlalchemy import select, union

from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import PositionState
from .effective_ledger import effective_ledger


def stock_day_page(*, owner_id, account_id, initialization_id, fact_version, trade_date,
                   previous_day_result_id, limit, policy, after=None):
    if type(limit) is not int or not 1 <= limit <= policy.page_rows:
        raise ValueError("Invalid stock page size")
    facts = effective_ledger(owner_id=owner_id, account_id=account_id, fact_version=fact_version)
    initial = select(InitialPosition.ts_code).where(InitialPosition.account_id == account_id,
        InitialPosition.initialization_id == initialization_id, InitialPosition.opened_on == trade_date)
    previous = select(PositionState.ts_code).where(PositionState.account_id == account_id,
        PositionState.day_result_id == previous_day_result_id, PositionState.quantity > 0)
    traded = select(facts.c.ts_code).where(facts.c.kind == "TRADE", facts.c.occurred_on == trade_date)
    scope = union(initial, previous, traded).subquery("stock_scope")
    query = select(scope.c.ts_code).where(select(Account.account_id).where(
        Account.account_id == account_id, Account.owner_id == owner_id).exists())
    if after is not None:
        query = query.where(scope.c.ts_code > after)
    return query.order_by(scope.c.ts_code).limit(limit)
