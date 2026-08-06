from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, desc
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class FundShareObservation(TimestampMixin, Base):
    __tablename__ = "fund_share_observation"
    __table_args__ = (
        Index(
            "idx_fund_share_observation_entity_last_observed",
            "source_entity_key",
            desc("last_observed_at"),
        ),
        Index(
            "idx_fund_share_observation_date_market_code",
            desc("trade_date"),
            "market",
            "ts_code",
        ),
        Index(
            "idx_fund_share_observation_code_date_last_observed",
            "ts_code",
            desc("trade_date"),
            desc("last_observed_at"),
        ),
        {"schema": "core_serving"},
    )

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_basis: Mapped[str] = mapped_column(Text, nullable=False)
    ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    fd_share: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    total_share: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    fund_type: Mapped[str | None] = mapped_column(Text)
    market: Mapped[str] = mapped_column(Text, nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
