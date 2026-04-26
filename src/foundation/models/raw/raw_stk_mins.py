from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawStkMins(Base):
    __tablename__ = "stk_mins"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    freq: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True)
    open: Mapped[float | None] = mapped_column(Float(24))
    close: Mapped[float | None] = mapped_column(Float(24))
    high: Mapped[float | None] = mapped_column(Float(24))
    low: Mapped[float | None] = mapped_column(Float(24))
    vol: Mapped[int | None] = mapped_column(Integer)
    amount: Mapped[float | None] = mapped_column(Float(24))
