"""M2 storage foundations for M3 generation execution, design §4.24.

Declaring these models never schedules calculation or publishes a result.
"""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, LargeBinary, Numeric,
                        Text, UniqueConstraint, Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from .accounts import exact_numeric, finite_numeric


class Recalculation(Base):
    __tablename__ = "wealth_ta_recalculation"
    __table_args__ = (
        CheckConstraint("target_version >= 1 AND fence >= 0 AND transient_failure_count >= 0", name="counters"),
        Index("idx_ta_recalculation_due", "next_attempt_at", "last_claimed_at", "account_id"),
        {"schema": "app"},
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app.wealth_ta_account.account_id", ondelete="RESTRICT"), primary_key=True)
    target_version: Mapped[int] = mapped_column(BigInteger)
    affected_from_date: Mapped[date] = mapped_column(Date)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executor_id: Mapped[str | None] = mapped_column(Text)
    fence: Mapped[int] = mapped_column(BigInteger)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transient_failure_count: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CalculationGeneration(Base):
    __tablename__ = "wealth_ta_calculation_generation"
    __table_args__ = (
        UniqueConstraint("account_id", "target_version", name="uq_ta_generation_target"),
        UniqueConstraint("account_id", "generation_id", name="uq_ta_generation_identity"),
        ForeignKeyConstraint(["account_id", "initialization_id"],
            ["app.wealth_ta_initialization.account_id", "app.wealth_ta_initialization.initialization_id"], ondelete="RESTRICT"),
        CheckConstraint("target_version >= 1 AND fact_version >= 1 AND rule_version >= 1", name="versions"),
        CheckConstraint("from_date <= through_date AND completed_trade_date_count >= 0 AND "
                        "(total_trade_date_count IS NULL OR total_trade_date_count >= completed_trade_date_count)", name="progress"),
        {"schema": "app"},
    )
    generation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app.wealth_ta_account.account_id", ondelete="RESTRICT"))
    target_version: Mapped[int] = mapped_column(BigInteger)
    fact_version: Mapped[int] = mapped_column(BigInteger)
    initialization_id: Mapped[UUID] = mapped_column(Uuid)
    rule_version: Mapped[int] = mapped_column(BigInteger)
    from_date: Mapped[date] = mapped_column(Date)
    through_date: Mapped[date] = mapped_column(Date)
    stage: Mapped[str] = mapped_column(Text)
    resume_stage: Mapped[str | None] = mapped_column(Text)
    completed_trade_date_count: Mapped[int] = mapped_column(BigInteger)
    total_trade_date_count: Mapped[int | None] = mapped_column(BigInteger)
    last_completed_trade_date: Mapped[date | None] = mapped_column(Date)
    last_business_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class DayResult(Base):
    __tablename__ = "wealth_ta_day_result"
    __table_args__ = (
        UniqueConstraint("account_id", "origin_generation_id", "trade_date", name="uq_ta_day_origin"),
        UniqueConstraint("account_id", "day_result_id", name="uq_ta_day_identity"),
        UniqueConstraint("account_id", "trade_date", "day_result_id", name="uq_ta_day_date_identity"),
        ForeignKeyConstraint(["account_id", "origin_generation_id"],
            ["app.wealth_ta_calculation_generation.account_id", "app.wealth_ta_calculation_generation.generation_id"], ondelete="RESTRICT"),
        CheckConstraint("octet_length(input_digest) = 32", name="digest"),
        CheckConstraint("(status = 'SEALED' AND sealed_at IS NOT NULL) OR (status = 'BUILDING' AND sealed_at IS NULL)", name="seal"),
        {"schema": "app"},
    )
    day_result_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid)
    origin_generation_id: Mapped[UUID] = mapped_column(Uuid)
    trade_date: Mapped[date] = mapped_column(Date)
    input_digest: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(Text)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PositionState(Base):
    __tablename__ = "wealth_ta_position_state"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "day_result_id"],
            ["app.wealth_ta_day_result.account_id", "app.wealth_ta_day_result.day_result_id"], ondelete="RESTRICT"),
        CheckConstraint(exact_numeric("quantity", scale=0), name="quantity"),
        CheckConstraint(exact_numeric("remaining_buy_cost"), name="remaining_cost"),
        CheckConstraint(exact_numeric("cumulative_buy_input"), name="buy_input"),
        CheckConstraint(finite_numeric("cumulative_sell_net"), name="sell_net"),
        CheckConstraint("remaining_buy_cost <= cumulative_buy_input", name="cost_pool"),
        {"schema": "app"},
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    day_result_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    ts_code: Mapped[str] = mapped_column(Text, primary_key=True)
    round_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opened_on: Mapped[date] = mapped_column(Date)
    closed_on: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric)
    remaining_buy_cost: Mapped[Decimal] = mapped_column(Numeric)
    cumulative_buy_input: Mapped[Decimal] = mapped_column(Numeric)
    cumulative_sell_net: Mapped[Decimal] = mapped_column(Numeric)


class ClosedTrade(Base):
    __tablename__ = "wealth_ta_closed_trade"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "day_result_id"],
            ["app.wealth_ta_day_result.account_id", "app.wealth_ta_day_result.day_result_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["account_id", "sell_ledger_id", "sell_revision"],
            ["app.wealth_ta_ledger_revision.account_id", "app.wealth_ta_ledger_revision.ledger_id", "app.wealth_ta_ledger_revision.revision"], ondelete="RESTRICT"),
        CheckConstraint("quantity BETWEEN 1 AND 9007199254740991", name="quantity"),
        CheckConstraint(exact_numeric("allocated_cost"), name="cost"),
        CheckConstraint(finite_numeric("net_proceeds"), name="net"),
        CheckConstraint(finite_numeric("profit_amount"), name="profit_precision"),
        CheckConstraint(finite_numeric("return_pct"), name="return_precision"),
        CheckConstraint("profit_amount = net_proceeds - allocated_cost", name="profit"),
        {"schema": "app"},
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    day_result_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sell_ledger_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sell_revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    round_id: Mapped[UUID] = mapped_column(Uuid)
    quantity: Mapped[int] = mapped_column(BigInteger)
    allocated_cost: Mapped[Decimal] = mapped_column(Numeric)
    net_proceeds: Mapped[Decimal] = mapped_column(Numeric)
    profit_amount: Mapped[Decimal] = mapped_column(Numeric)
    return_pct: Mapped[Decimal] = mapped_column(Numeric)
