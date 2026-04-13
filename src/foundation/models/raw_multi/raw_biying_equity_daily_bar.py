from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawBiyingEquityDailyBar(Base):
    __tablename__ = "equity_daily_bar"
    __table_args__ = (
        Index("idx_raw_biying_equity_daily_bar_trade_date", "trade_date"),
        Index("idx_raw_biying_equity_daily_bar_dm_trade_date", "dm", "trade_date"),
        {"schema": "raw_biying"},
    )

    dm: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adj_type: Mapped[str] = mapped_column(String(8), primary_key=True)
    mc: Mapped[str | None] = mapped_column(String(64))
    quote_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pre_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    suspend_flag: Mapped[int | None] = mapped_column(Integer)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'hsstock_history'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
