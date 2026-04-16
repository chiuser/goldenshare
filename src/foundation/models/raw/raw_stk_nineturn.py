from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawStkNineTurn(Base):
    __tablename__ = "stk_nineturn"
    __table_args__ = (
        Index("idx_raw_tushare_stk_nineturn_trade_date", "trade_date"),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    freq: Mapped[str | None] = mapped_column(String(16))
    open: Mapped[float | None] = mapped_column(Numeric(18, 4))
    high: Mapped[float | None] = mapped_column(Numeric(18, 4))
    low: Mapped[float | None] = mapped_column(Numeric(18, 4))
    close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    up_count: Mapped[float | None] = mapped_column(Numeric(10, 4))
    down_count: Mapped[float | None] = mapped_column(Numeric(10, 4))
    nine_up_turn: Mapped[str | None] = mapped_column(String(16))
    nine_down_turn: Mapped[str | None] = mapped_column(String(16))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'stk_nineturn'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
