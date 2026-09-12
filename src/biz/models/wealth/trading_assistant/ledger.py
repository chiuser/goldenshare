"""Immutable source ledger and revisions, design §4.22."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey,
                        ForeignKeyConstraint, Index, Numeric, Text, UniqueConstraint, Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from .accounts import exact_numeric


class Ledger(Base):
    __tablename__ = "wealth_ta_ledger"
    __table_args__ = (
        UniqueConstraint("account_id", "ledger_id", "kind"),
        CheckConstraint("kind IN ('TRADE', 'CASH_FLOW')", name="kind"),
        {"schema": "app"},
    )
    ledger_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app.wealth_ta_account.account_id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


TRADE_FIELDS = ("ts_code", "price", "quantity", "gross_amount", "fee_version_id",
                "commission_rate", "minimum_commission", "stamp_tax_rate",
                "commission_amount", "stamp_tax_amount")
BRANCH_CHECK = (
    "(kind = 'TRADE' AND direction IN ('BUY', 'SELL') AND cash_amount IS NULL AND "
    + " AND ".join(f"{name} IS NOT NULL" for name in TRADE_FIELDS)
    + ") OR (kind = 'CASH_FLOW' AND direction IN ('IN', 'OUT') AND cash_amount IS NOT NULL AND "
    + " AND ".join(f"{name} IS NULL" for name in TRADE_FIELDS) + ")"
)


class LedgerRevision(Base):
    __tablename__ = "wealth_ta_ledger_revision"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "ledger_id", "kind"],
            ["app.wealth_ta_ledger.account_id", "app.wealth_ta_ledger.ledger_id", "app.wealth_ta_ledger.kind"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["ledger_id", "source_revision"],
            ["app.wealth_ta_ledger_revision.ledger_id", "app.wealth_ta_ledger_revision.revision"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["account_id", "fee_version_id"],
            ["app.wealth_ta_fee_version.account_id", "app.wealth_ta_fee_version.fee_version_id"], ondelete="RESTRICT"),
        UniqueConstraint("account_id", "accepted_fact_version", name="uq_ta_ledger_fact_version"),
        UniqueConstraint("account_id", "ledger_id", "revision", name="uq_ta_ledger_revision_identity"),
        Index("idx_ta_revision_effective", "account_id", "ledger_id", "accepted_fact_version"),
        CheckConstraint("revision >= 1 AND accepted_fact_version >= 1", name="versions"),
        CheckConstraint("(revision = 1 AND source_revision IS NULL) OR (revision > 1 AND source_revision IS NOT NULL AND source_revision = revision - 1)", name="source"),
        CheckConstraint("status IN ('ACTIVE', 'VOID')", name="status"),
        CheckConstraint(BRANCH_CHECK, name="branch"),
        CheckConstraint("kind <> 'TRADE' OR (quantity BETWEEN 1 AND 9007199254740991 AND length(ts_code) > 0)", name="quantity"),
        CheckConstraint("kind <> 'TRADE' OR (" + " AND ".join((
            exact_numeric("price", positive=True), exact_numeric("gross_amount", positive=True),
            exact_numeric("commission_rate", scale=6), exact_numeric("minimum_commission"),
            exact_numeric("stamp_tax_rate", scale=4, maximum="1"),
            exact_numeric("commission_amount"), exact_numeric("stamp_tax_amount"))) + ")", name="trade_numbers"),
        CheckConstraint("kind <> 'CASH_FLOW' OR (" + exact_numeric("cash_amount", positive=True) + ")", name="cash_amount"),
        CheckConstraint("(kind = 'TRADE' AND gross_amount = price * quantity AND "
                        "((direction = 'BUY' AND stamp_tax_amount = 0 AND net_cash_change = -(gross_amount + commission_amount)) OR "
                        "(direction = 'SELL' AND net_cash_change = gross_amount - commission_amount - stamp_tax_amount))) OR "
                        "(kind = 'CASH_FLOW' AND ((direction = 'IN' AND net_cash_change = cash_amount) OR "
                        "(direction = 'OUT' AND net_cash_change = -cash_amount)))", name="cash_conservation"),
        {"schema": "app"},
    )
    ledger_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    accepted_fact_version: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_revision: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    net_cash_change: Mapped[Decimal] = mapped_column(Numeric)
    ts_code: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric)
    quantity: Mapped[int | None] = mapped_column(BigInteger)
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric)
    minimum_commission: Mapped[Decimal | None] = mapped_column(Numeric)
    stamp_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric)
    commission_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    stamp_tax_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric)
