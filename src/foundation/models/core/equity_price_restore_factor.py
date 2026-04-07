from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityPriceRestoreFactor(TimestampMixin, Base):
    __tablename__ = "equity_price_restore_factor"
    __table_args__ = (
        Index("idx_equity_price_restore_factor_trade_date", "trade_date"),
        Index("idx_equity_price_restore_factor_updated_at", "updated_at"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    cum_factor: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    single_factor: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    event_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    event_ex_date: Mapped[date | None] = mapped_column(Date)
