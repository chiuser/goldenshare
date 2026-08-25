from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawEtfMinuteBar(Base):
    __tablename__ = "etf_minute_bar"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    freq: Mapped[str] = mapped_column(String(8), primary_key=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True)
    open: Mapped[float | None] = mapped_column(Float(53))
    close: Mapped[float | None] = mapped_column(Float(53))
    high: Mapped[float | None] = mapped_column(Float(53))
    low: Mapped[float | None] = mapped_column(Float(53))
    vol: Mapped[int | None] = mapped_column(BigInteger)
    amount: Mapped[float | None] = mapped_column(Float(53))
    vwap: Mapped[float | None] = mapped_column(Float(53))
    exchange: Mapped[str | None] = mapped_column(String(16))
