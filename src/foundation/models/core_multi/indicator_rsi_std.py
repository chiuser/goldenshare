from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class IndicatorRsiStd(TimestampMixin, Base):
    __tablename__ = "indicator_rsi_std"
    __table_args__ = (
        Index("idx_indicator_rsi_std_trade_date", "trade_date"),
        Index("idx_indicator_rsi_std_source_trade_date", "source_key", "trade_date"),
        {"schema": "core_multi"},
    )

    source_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adjustment: Mapped[str] = mapped_column(String(16), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    rsi_6: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    rsi_12: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    rsi_24: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
