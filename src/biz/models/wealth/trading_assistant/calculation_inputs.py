"""Frozen valuation inputs and committed batches, design §4.24."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKeyConstraint,
                        LargeBinary, Numeric, Text, UniqueConstraint, Uuid)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from .accounts import finite_numeric


class ValuationBasis(Base):
    __tablename__ = "wealth_ta_valuation_basis"
    __table_args__ = (
        UniqueConstraint("account_id", "generation_id", "trade_date", "ts_code", name="uq_ta_valuation_stock_day"),
        ForeignKeyConstraint(["account_id", "generation_id"],
            ["app.wealth_ta_calculation_generation.account_id", "app.wealth_ta_calculation_generation.generation_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["account_id", "fee_version_id"],
            ["app.wealth_ta_fee_version.account_id", "app.wealth_ta_fee_version.fee_version_id"], ondelete="RESTRICT"),
        CheckConstraint("price IS NULL OR (price > 0 AND " + finite_numeric("price", scale=None) + ")", name="price"),
        CheckConstraint("(quality = 'READY' AND price IS NOT NULL AND price_date IS NOT NULL AND valuation_method IS NOT NULL AND "
            "((valuation_method = 'SAME_DAY_CLOSE' AND price_date = trade_date AND suspension_evidence_ref IS NULL) OR "
            "(valuation_method = 'CONFIRMED_SUSPENSION_CARRY' AND price_date < trade_date AND suspension_evidence_ref IS NOT NULL))) OR "
            "(quality = 'UNAVAILABLE' AND price IS NULL AND price_date IS NULL AND valuation_method IS NULL AND suspension_evidence_ref IS NULL)", name="availability"),
        {"schema": "app"},
    )
    basis_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(Uuid)
    generation_id: Mapped[UUID] = mapped_column(Uuid)
    ts_code: Mapped[str] = mapped_column(Text)
    trade_date: Mapped[date] = mapped_column(Date)
    valuation_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal | None] = mapped_column(Numeric)
    source_ref: Mapped[str] = mapped_column(Text)
    source_version: Mapped[str] = mapped_column(Text)
    quality: Mapped[str] = mapped_column(Text)
    fee_version_id: Mapped[UUID] = mapped_column(Uuid)
    valuation_method: Mapped[str | None] = mapped_column(Text)
    price_date: Mapped[date | None] = mapped_column(Date)
    suspension_evidence_ref: Mapped[str | None] = mapped_column(Text)


class CalculationBatch(Base):
    __tablename__ = "wealth_ta_calculation_batch"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "generation_id"],
            ["app.wealth_ta_calculation_generation.account_id", "app.wealth_ta_calculation_generation.generation_id"], ondelete="RESTRICT"),
        CheckConstraint("row_count >= 0 AND octet_length(input_digest) = 32", name="batch_values"),
        CheckConstraint("length(stage) > 0 AND length(page_key) > 0", name="batch_identity"),
        {"schema": "app"},
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    generation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    stage: Mapped[str] = mapped_column(Text, primary_key=True)
    stock_key: Mapped[str] = mapped_column(Text, primary_key=True)
    page_key: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor: Mapped[dict] = mapped_column(JSONB)
    accumulator: Mapped[dict] = mapped_column(JSONB)
    input_digest: Mapped[bytes] = mapped_column(LargeBinary)
    row_count: Mapped[int] = mapped_column(BigInteger)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
