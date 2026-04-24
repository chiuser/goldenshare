from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawStkMins(Base):
    __tablename__ = "stk_mins"
    __table_args__ = (
        Index("idx_raw_tushare_stk_mins_trade_date_freq", "trade_date", "freq"),
        Index("idx_raw_tushare_stk_mins_ts_code_freq_trade_time", "ts_code", "freq", "trade_time"),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    freq: Mapped[str] = mapped_column(String(8), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True)
    session_tag: Mapped[str] = mapped_column(String(16), nullable=False)
    open: Mapped[float | None] = mapped_column(Float(53))
    close: Mapped[float | None] = mapped_column(Float(53))
    high: Mapped[float | None] = mapped_column(Float(53))
    low: Mapped[float | None] = mapped_column(Float(53))
    vol: Mapped[float | None] = mapped_column(Float(53))
    amount: Mapped[float | None] = mapped_column(Float(53))
    api_name: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'stk_mins'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
