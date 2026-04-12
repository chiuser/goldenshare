from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class IndicatorMacd(TimestampMixin, Base):
    __tablename__ = "ind_macd"
    __table_args__ = (
        Index("idx_ind_macd_trade_date", "trade_date"),
        Index("idx_ind_macd_adj_trade_date", "adjustment", "trade_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adjustment: Mapped[str] = mapped_column(String(16), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    dif: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    dea: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    macd_bar: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
