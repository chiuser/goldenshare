from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class FundBasicCurrent(TimestampMixin, Base):
    __tablename__ = "fund_basic_current"
    __table_args__ = (Index("idx_fund_basic_current_source_entity_key", "source_entity_key"), {"schema": "core_serving"})

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    management: Mapped[str | None] = mapped_column(Text)
    custodian: Mapped[str | None] = mapped_column(Text)
    fund_type: Mapped[str | None] = mapped_column(Text)
    found_date: Mapped[str | None] = mapped_column(String(8))
    due_date: Mapped[str | None] = mapped_column(String(8))
    list_date: Mapped[str | None] = mapped_column(String(8))
    issue_date: Mapped[str | None] = mapped_column(String(8))
    delist_date: Mapped[str | None] = mapped_column(String(8))
    issue_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    m_fee: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    c_fee: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    duration_year: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    p_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    exp_return: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    benchmark: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    invest_type: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    trustee: Mapped[str | None] = mapped_column(Text)
    purc_startdate: Mapped[str | None] = mapped_column(String(8))
    redm_startdate: Mapped[str | None] = mapped_column(String(8))
    market: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
