from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawIndexMins(Base):
    __tablename__ = "index_mins"
    __table_args__ = (
        Index("ix_raw_tushare_index_mins_trade_time", "trade_time"),
        Index("ix_raw_tushare_index_mins_ts_code_trade_time", "ts_code", "trade_time"),
        Index("ix_raw_tushare_index_mins_freq_trade_time", "freq", "trade_time"),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    freq: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True)
    close: Mapped[float | None] = mapped_column(Float(53))
    open: Mapped[float | None] = mapped_column(Float(53))
    high: Mapped[float | None] = mapped_column(Float(53))
    low: Mapped[float | None] = mapped_column(Float(53))
    vol: Mapped[float | None] = mapped_column(Float(53))
    amount: Mapped[float | None] = mapped_column(Float(53))
    exchange: Mapped[str | None] = mapped_column(String(16))
    vwap: Mapped[float | None] = mapped_column(Float(53))
