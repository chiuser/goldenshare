"""Return history and participation from owned effective facts, never today's holdings."""
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import case, func, literal, select, union_all

from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.schemas.wealth.market.trading_assistant.common import AccountRef
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .effective_ledger import effective_ledger


@dataclass(frozen=True, slots=True)
class ReturnFactScope:
    account: AccountRef
    owner_id: int
    fact_version: int
    initialization_id: UUID
    initialized_on: date
    history_start: date | None
    stock: str | None


@dataclass(frozen=True, slots=True)
class ParticipationDay:
    day: date
    opening_quantity: int
    closing_quantity: int
    trade_count: int

    def __post_init__(self):
        if type(self.day) is not date or any(type(n) is not int or n < 0 for n in (
                self.opening_quantity, self.closing_quantity, self.trade_count)):
            raise ValueError("Invalid long-only participation fact")

    @property
    def participates(self):
        return self.opening_quantity > 0 or self.closing_quantity > 0 or self.trade_count > 0


def _events(scope):
    initial = select(InitialPosition.opened_on.label("day"), InitialPosition.quantity.label("delta"),
        literal(0).label("trade_count")).where(
        InitialPosition.account_id == UUID(scope.account.accountId),
        InitialPosition.initialization_id == scope.initialization_id)
    ledger = effective_ledger(owner_id=scope.owner_id, account_id=UUID(scope.account.accountId),
                              fact_version=scope.fact_version)
    trades = select(ledger.c.occurred_on.label("day"),
        case((ledger.c.direction == "BUY", ledger.c.quantity), else_=-ledger.c.quantity).label("delta"),
        literal(1).label("trade_count")).where(ledger.c.kind == "TRADE")
    if scope.stock is not None:
        initial = initial.where(InitialPosition.ts_code == scope.stock)
        trades = trades.where(ledger.c.ts_code == scope.stock)
    return union_all(initial, trades).subquery("participation_events")


class ReturnScopeQuery:
    def __init__(self, policy):
        self.policy = policy

    def read(self, session, *, owner_id, basis, account_id, deadline, stock=None):
        reference = next((ref for ref in basis.context.accounts if ref.accountId == str(account_id)), None)
        if reference is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        apply_sql_budget(session, deadline, self.policy)
        account = session.scalar(select(Account).where(Account.owner_id == owner_id,
            Account.account_id == account_id, Account.fact_version == int(reference.factVersion),
            Account.calculation_target_version == int(reference.calculationTargetVersion)))
        if account is None:
            raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED")
        scope = ReturnFactScope(AccountRef(accountId=str(account_id), name=account.name, brokerName=account.broker_name),
            owner_id, account.fact_version, account.current_initialization_id, account.initialized_on, None, stock)
        events = _events(scope)
        apply_sql_budget(session, deadline, self.policy)
        first = session.scalar(select(func.min(events.c.day)))
        # A stock with no history has no invented initialization. For ALL stocks,
        # the account's cash-only lifetime still has a known (empty) return scope.
        if stock is None:
            first = min(account.initialized_on, first) if first else account.initialized_on
        return ReturnFactScope(scope.account, owner_id, scope.fact_version, scope.initialization_id,
                               scope.initialized_on, first, stock)

    def participation(self, session, *, scope: ReturnFactScope, start: date, end: date, deadline):
        """One bounded civil-date page; group facts in SQL rather than one query per stock/day."""
        if (type(start) is not date or type(end) is not date or start > end
                or (end - start).days + 1 > self.policy.page_rows):
            raise ValueError("Participation dates must fit one bounded page")
        events = _events(scope)
        apply_sql_budget(session, deadline, self.policy)
        opening = session.scalar(select(func.sum(events.c.delta)).where(events.c.day < start))
        quantity = int(opening) if opening is not None else 0
        apply_sql_budget(session, deadline, self.policy)
        rows = session.execute(select(events.c.day, func.sum(events.c.delta), func.sum(events.c.trade_count))
            .where(events.c.day >= start, events.c.day <= end).group_by(events.c.day)
            .order_by(events.c.day).limit(self.policy.page_rows)).all()
        changes = {day: (int(delta), int(count)) for day, delta, count in rows}
        result = []
        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            delta, trades = changes.get(day, (0, 0))
            closing = quantity + delta
            if quantity < 0 or closing < 0:
                raise ValueError("Accepted long-only quantity is negative")
            result.append(ParticipationDay(day, quantity, closing, trades))
            quantity = closing
        deadline.remaining_ms()
        return tuple(result)
