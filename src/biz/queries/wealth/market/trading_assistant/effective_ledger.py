"""Select revisions before filtering; never resurrect moved or void facts."""
from uuid import UUID

from dataclasses import dataclass
from datetime import date

from sqlalchemy import BigInteger, Date, Numeric, Text, Uuid, func, literal, select, tuple_, union_all

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.persistence_values import money_numeric


@dataclass(frozen=True, slots=True)
class ReplacementFact:
    """Already normalized prospective fact; never a persisted extra cash entry."""
    ledger_id: UUID
    occurred_on: date
    kind: str
    direction: str
    quantity: int | None
    ts_code: str | None
    net_cash_cents: int

    def __post_init__(self):
        if not isinstance(self.ledger_id, UUID) or type(self.occurred_on) is not date or type(self.net_cash_cents) is not int:
            raise ValueError("Invalid prospective identity/date/money")
        if self.kind == "TRADE":
            if self.direction not in ("BUY", "SELL") or type(self.quantity) is not int or not 1 <= self.quantity <= 9007199254740991 or not self.ts_code:
                raise ValueError("Invalid prospective trade")
        elif self.kind == "CASH_FLOW":
            if self.direction not in ("IN", "OUT") or self.quantity is not None or self.ts_code is not None:
                raise ValueError("Invalid prospective cash flow")
            if (self.direction == "IN" and self.net_cash_cents <= 0) or (self.direction == "OUT" and self.net_cash_cents >= 0):
                raise ValueError("Invalid prospective cash sign")
        else:
            raise ValueError("Invalid prospective kind")


def effective_ledger(*, owner_id: int, account_id: UUID, fact_version: int):
    if type(owner_id) is not int or type(fact_version) is not int or fact_version < 1:
        raise ValueError("Invalid trusted fact scope")
    ranked = (
        select(*LedgerRevision.__table__.columns, Ledger.created_at.label("recorded_at"),
               func.row_number().over(partition_by=LedgerRevision.ledger_id,
                   order_by=LedgerRevision.revision.desc()).label("revision_rank"))
        .join(Account, Account.account_id == LedgerRevision.account_id)
        .join(Ledger, Ledger.ledger_id == LedgerRevision.ledger_id)
        .where(Account.owner_id == owner_id, Account.account_id == account_id,
               LedgerRevision.accepted_fact_version <= fact_version)
        .subquery("ranked_revisions")
    )
    return select(*[c for c in ranked.c if c.key != "revision_rank"]).where(
        ranked.c.revision_rank == 1, ranked.c.status == "ACTIVE").subquery("effective_ledger")


def validation_page(*, owner_id: int, account_id: UUID, fact_version: int,
                    limit: int, policy: TradingAssistantExecutionPolicyV1,
                    stock: str | None = None, after: tuple | None = None,
                    replaced_ledger_id: UUID | None = None,
                    replacement: ReplacementFact | None = None):
    """Only bounded projection, not prices/notes/all revision histories."""
    if type(limit) is not int or not 1 <= limit <= policy.page_rows:
        raise ValueError("Invalid validation page size")
    facts = effective_ledger(owner_id=owner_id, account_id=account_id, fact_version=fact_version)
    if replacement is not None and replaced_ledger_id is not None and replacement.ledger_id != replaced_ledger_id:
        raise ValueError("A correction must keep its ledger identity")
    columns = ("ledger_id", "occurred_on", "kind", "direction", "quantity", "net_cash_change", "ts_code")
    selected = select(*[facts.c[name] for name in columns])
    if replaced_ledger_id is not None:
        selected = selected.where(facts.c.ledger_id != replaced_ledger_id)
    if replacement is not None:
        candidate = select(
            literal(replacement.ledger_id, type_=Uuid).label("ledger_id"),
            literal(replacement.occurred_on, type_=Date).label("occurred_on"),
            literal(replacement.kind, type_=Text).label("kind"),
            literal(replacement.direction, type_=Text).label("direction"),
            literal(replacement.quantity, type_=BigInteger).label("quantity"),
            literal(money_numeric(replacement.net_cash_cents), type_=Numeric).label("net_cash_change"),
            literal(replacement.ts_code, type_=Text).label("ts_code")).where(
                select(Account.account_id).where(Account.account_id == account_id,
                                                Account.owner_id == owner_id).exists())
        facts = union_all(selected, candidate).subquery("prospective_facts")
    else:
        facts = selected.subquery("prospective_facts")
    statement = select(*[facts.c[name] for name in columns])
    if stock is not None:
        statement = statement.where(facts.c.kind == "TRADE", facts.c.ts_code == stock)
    if after is not None:
        statement = statement.where(tuple_(facts.c.occurred_on, facts.c.ledger_id) > tuple_(*after))
    return statement.order_by(facts.c.occurred_on, facts.c.ledger_id).limit(limit)
