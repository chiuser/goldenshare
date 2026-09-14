"""Current quantities and cash from effective revisions, independently of M3 readiness."""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import case, func, literal, select, union_all

from src.biz.models.wealth.trading_assistant.accounts import Account, Initialization, InitialPosition
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .effective_ledger import effective_ledger


@dataclass(frozen=True, slots=True)
class HoldingFact:
    ts_code: str
    quantity: int
    available_quantity: int | None


@dataclass(frozen=True, slots=True)
class AccountHoldingFacts:
    account: Account
    cash_cents: int
    holdings: tuple[HoldingFact, ...]


class PositionsFactsQuery:
    def __init__(self, policy):
        self.policy = policy

    def read(self, session, *, owner_id, reference, cutoff, deadline):
        account_id = UUID(reference.accountId)
        apply_sql_budget(session, deadline, self.policy)
        pair = session.execute(select(Account, Initialization.initial_cash).join(Initialization,
            Initialization.initialization_id == Account.current_initialization_id).where(
                Account.account_id == account_id, Account.owner_id == owner_id,
                Account.fact_version == int(reference.factVersion))).one_or_none()
        if pair is None:
            raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED")
        account, initial_cash = pair
        ledger = effective_ledger(owner_id=owner_id, account_id=account_id, fact_version=account.fact_version)
        apply_sql_budget(session, deadline, self.policy)
        cash_delta = session.scalar(select(func.sum(ledger.c.net_cash_change)))
        cash = numeric_cents(initial_cash) + (numeric_cents(cash_delta) if cash_delta is not None else 0)
        initial = select(InitialPosition.ts_code,
            InitialPosition.quantity.label("quantity"),
            InitialPosition.quantity.label("opening"),
            (InitialPosition.quantity - InitialPosition.available_quantity).label("initial_locked"),
            literal(0).label("sold_today")).where(InitialPosition.initialization_id == account.current_initialization_id)
        signed = case((ledger.c.direction == "BUY", ledger.c.quantity), else_=-ledger.c.quantity)
        trades = select(ledger.c.ts_code, signed.label("quantity"),
            case((ledger.c.occurred_on < cutoff.today, signed), else_=0).label("opening"),
            literal(0).label("initial_locked"),
            case(((ledger.c.occurred_on == cutoff.today) & (ledger.c.direction == "SELL"),
                  ledger.c.quantity), else_=0).label("sold_today")).where(ledger.c.kind == "TRADE")
        values = union_all(initial, trades).subquery()
        grouped = select(values.c.ts_code, func.sum(values.c.quantity).label("quantity"),
            func.sum(values.c.opening).label("opening"), func.sum(values.c.initial_locked).label("initial_locked"),
            func.sum(values.c.sold_today).label("sold_today")).group_by(values.c.ts_code).subquery()
        last_open = cutoff.today if cutoff.is_open else cutoff.valuation_date
        initial_unlocked = last_open is not None and last_open > account.initialized_on
        holdings, after = [], None
        while True:
            apply_sql_budget(session, deadline, self.policy)
            query = select(grouped).where(grouped.c.quantity > 0)
            if after is not None:
                query = query.where(grouped.c.ts_code > after)
            rows = session.execute(query.order_by(grouped.c.ts_code).limit(self.policy.page_rows)).all()
            for row in rows:
                quantity = int(row.quantity)
                available = (None if cutoff.reason else int(row.opening - row.sold_today)
                             - (0 if initial_unlocked else int(row.initial_locked)))
                if available is not None and not 0 <= available <= quantity:
                    raise ValueError("Effective holdings violate accepted sellable quantity")
                holdings.append(HoldingFact(row.ts_code, quantity, available))
            if len(rows) < self.policy.page_rows:
                return AccountHoldingFacts(account, cash, tuple(holdings))
            after = rows[-1].ts_code
