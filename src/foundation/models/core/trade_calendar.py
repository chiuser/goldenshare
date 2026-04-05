from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class TradeCalendar(Base):
    __tablename__ = "trade_calendar"
    __table_args__ = (
        Index("idx_trade_calendar_trade_date", "trade_date"),
        {"schema": "core"},
    )

    exchange: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pretrade_date: Mapped[date | None] = mapped_column(Date)
