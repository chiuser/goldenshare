"""Bounded effective cash facts for a whole-account return window, not profit."""
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import and_, case, func, select

from src.biz.models.wealth.trading_assistant.accounts import InitialPosition, Initialization
from src.biz.services.wealth.market.trading_assistant.calculation.periods import DayCash
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from .effective_ledger import effective_ledger


@dataclass(frozen=True, slots=True)
class ReturnCashDay:
    day: date
    cash: DayCash | None
    initial_cash_cents: int
    initial_cost_cents: int


class ReturnCashQuery:
    def __init__(self, policy):
        self.policy = policy

    def opening(self, session, *, scope, start, deadline):
        if scope.stock is not None:
            raise ValueError("Whole-account cash cannot be filtered by stock")
        apply_sql_budget(session, deadline, self.policy)
        initial = session.scalar(select(Initialization.initial_cash).where(
            Initialization.account_id == UUID(scope.account.accountId),
            Initialization.initialization_id == scope.initialization_id))
        if initial is None:
            raise ValueError("Current initialization is missing")
        initial = numeric_cents(initial)
        if start < scope.initialized_on:
            return initial, None
        facts = effective_ledger(owner_id=scope.owner_id, account_id=UUID(scope.account.accountId), fact_version=scope.fact_version)
        apply_sql_budget(session, deadline, self.policy)
        net = session.scalar(select(func.sum(facts.c.net_cash_change)).where(facts.c.occurred_on < start))
        opening = initial + (numeric_cents(net) if net is not None else 0)
        if opening < 0:
            raise ValueError("Accepted opening cash is negative")
        return initial, opening

    def page(self, session, *, scope, start, end, opening_cash_cents, initial_cash_cents, deadline):
        if scope.stock is not None or type(start) is not date or type(end) is not date or not 0 <= (end-start).days < self.policy.page_rows:
            raise ValueError("Cash dates must fit one whole-account page")
        facts = effective_ledger(owner_id=scope.owner_id, account_id=UUID(scope.account.accountId), fact_version=scope.fact_version)
        def amount(kind, direction, sign=1):
            return func.sum(case((and_(facts.c.kind == kind, facts.c.direction == direction),
                                  sign * facts.c.net_cash_change), else_=0))
        apply_sql_budget(session, deadline, self.policy)
        rows = session.execute(select(facts.c.occurred_on, func.count(), amount("CASH_FLOW", "IN"),
            amount("CASH_FLOW", "OUT", -1), amount("TRADE", "BUY", -1), amount("TRADE", "SELL"))
            .where(facts.c.occurred_on >= start, facts.c.occurred_on <= end)
            .group_by(facts.c.occurred_on).order_by(facts.c.occurred_on).limit(self.policy.page_rows)).all()
        changes = {day: (count, *(numeric_cents(n) for n in values)) for day, count, *values in rows}
        apply_sql_budget(session, deadline, self.policy)
        injected = dict(session.execute(select(InitialPosition.opened_on,
            func.sum(InitialPosition.quantity * InitialPosition.cost_price)).where(
            InitialPosition.account_id == UUID(scope.account.accountId), InitialPosition.initialization_id == scope.initialization_id,
            InitialPosition.opened_on >= start, InitialPosition.opened_on <= end)
            .group_by(InitialPosition.opened_on).limit(self.policy.page_rows)).all())
        cash, result = opening_cash_cents, []
        for offset in range((end-start).days + 1):
            day = start + timedelta(days=offset)
            count, incoming, outgoing, buy, sell = changes.get(day, (0, 0, 0, 0, 0))
            entered = 0
            if day == scope.initialized_on and cash is None:
                entered = cash = initial_cash_cents
            if day < scope.initialized_on:
                if cash is not None or count:
                    raise ValueError("Cannot invent cash or trades before initialization")
                flow = None
            else:
                if cash is None:
                    raise ValueError("Registered cash cannot be unknown")
                cash += incoming + sell - buy - outgoing
                flow = DayCash(scope.account.accountId, day, incoming, outgoing, buy, sell, cash)
            result.append(ReturnCashDay(day, flow, entered, numeric_cents(injected[day]) if day in injected else 0))
        deadline.remaining_ms()
        return tuple(result)
