"""Account and immutable initialization/fee versions, design §§4.20–4.21."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, Numeric, Text,
                        UniqueConstraint, Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


def finite_numeric(column: str, *, scale: int | None = 2) -> str:
    """Finite exact result; signed amounts and source prices use this helper."""
    parts = [f"{column} NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)"]
    if scale is not None:
        parts.append(f"{column} = trunc({column}, {scale})")
    return " AND ".join(parts)


def exact_numeric(column: str, *, scale: int = 2, positive: bool = False,
                  maximum: str | None = None) -> str:
    """Named columns only; DDL helper, never takes runtime/user input."""
    parts = [finite_numeric(column, scale=scale),
             f"{column} {'>' if positive else '>='} 0"]
    if maximum is not None:
        parts.append(f"{column} <= {maximum}")
    return " AND ".join(parts)


class Account(Base):
    __tablename__ = "wealth_ta_account"
    __table_args__ = (
        UniqueConstraint("owner_id", "account_id"),
        ForeignKeyConstraint(["account_id", "current_initialization_id"],
            ["app.wealth_ta_initialization.account_id", "app.wealth_ta_initialization.initialization_id"],
            name="fk_ta_account_initialization", deferrable=True, initially="DEFERRED", ondelete="RESTRICT", use_alter=True),
        ForeignKeyConstraint(["account_id", "current_fee_version_id"],
            ["app.wealth_ta_fee_version.account_id", "app.wealth_ta_fee_version.fee_version_id"],
            name="fk_ta_account_fee", deferrable=True, initially="DEFERRED", ondelete="RESTRICT", use_alter=True),
        ForeignKeyConstraint(["account_id", "published_generation_id"],
            ["app.wealth_ta_calculation_generation.account_id", "app.wealth_ta_calculation_generation.generation_id"],
            name="fk_ta_account_publication", deferrable=True, initially="DEFERRED", ondelete="RESTRICT", use_alter=True),
        CheckConstraint("length(btrim(name)) > 0 AND length(btrim(broker_name)) > 0", name="names"),
        CheckConstraint("fact_version >= 1 AND calculation_target_version >= 1", name="versions"),
        Index("idx_ta_account_owner_order", "owner_id", "created_at", "account_id"),
        {"schema": "app"},
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("app.app_user.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    broker_name: Mapped[str] = mapped_column(Text)
    initialized_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_initialization_id: Mapped[UUID] = mapped_column(Uuid)
    current_fee_version_id: Mapped[UUID] = mapped_column(Uuid)
    fact_version: Mapped[int] = mapped_column(BigInteger)
    calculation_target_version: Mapped[int] = mapped_column(BigInteger)
    published_generation_id: Mapped[UUID | None] = mapped_column(Uuid)


class FeeVersion(Base):
    __tablename__ = "wealth_ta_fee_version"
    __table_args__ = (
        UniqueConstraint("account_id", "fee_version_id"),
        CheckConstraint(exact_numeric("commission_rate", scale=6), name="commission"),
        CheckConstraint(exact_numeric("minimum_commission"), name="minimum"),
        CheckConstraint(exact_numeric("stamp_tax_rate", scale=4, maximum="1"), name="tax"),
        {"schema": "app"},
    )
    fee_version_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app.wealth_ta_account.account_id", ondelete="RESTRICT"))
    commission_rate: Mapped[Decimal] = mapped_column(Numeric)
    minimum_commission: Mapped[Decimal] = mapped_column(Numeric)
    stamp_tax_rate: Mapped[Decimal] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Initialization(Base):
    __tablename__ = "wealth_ta_initialization"
    __table_args__ = (
        UniqueConstraint("account_id", "initialization_id", name="uq_ta_initialization_identity"),
        UniqueConstraint("account_id", "revision", name="uq_ta_initialization_revision"),
        CheckConstraint("revision >= 1 AND accepted_fact_version >= 1", name="versions"),
        CheckConstraint("(revision = 1 AND source_initialization_id IS NULL) OR "
                        "(revision > 1 AND source_initialization_id IS NOT NULL AND source_initialization_id <> initialization_id)", name="source"),
        CheckConstraint(exact_numeric("initial_cash"), name="cash"),
        ForeignKeyConstraint(["account_id", "source_initialization_id"],
            ["app.wealth_ta_initialization.account_id", "app.wealth_ta_initialization.initialization_id"], ondelete="RESTRICT"),
        {"schema": "app"},
    )
    initialization_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app.wealth_ta_account.account_id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(BigInteger)
    accepted_fact_version: Mapped[int] = mapped_column(BigInteger)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_initialization_id: Mapped[UUID | None] = mapped_column(Uuid)


class InitialPosition(Base):
    __tablename__ = "wealth_ta_initial_position"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "initialization_id"],
            ["app.wealth_ta_initialization.account_id", "app.wealth_ta_initialization.initialization_id"], ondelete="RESTRICT"),
        UniqueConstraint("initialization_id", "client_row_id"),
        CheckConstraint("quantity BETWEEN 1 AND 9007199254740991 AND available_quantity BETWEEN 0 AND quantity", name="quantity"),
        CheckConstraint("length(client_row_id) > 0 AND length(ts_code) > 0", name="identity"),
        CheckConstraint(exact_numeric("cost_price", positive=True), name="cost"),
        {"schema": "app"},
    )
    initialization_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    ts_code: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid)
    client_row_id: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(BigInteger)
    available_quantity: Mapped[int] = mapped_column(BigInteger)
    cost_price: Mapped[Decimal] = mapped_column(Numeric)
