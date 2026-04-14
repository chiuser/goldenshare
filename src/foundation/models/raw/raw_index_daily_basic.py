from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawIndexDailyBasic(Base):
    __tablename__ = "index_daily_basic"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_mv: Mapped[float | None] = mapped_column(Numeric(20, 4))
    float_mv: Mapped[float | None] = mapped_column(Numeric(20, 4))
    total_share: Mapped[float | None] = mapped_column(Numeric(20, 4))
    float_share: Mapped[float | None] = mapped_column(Numeric(20, 4))
    free_share: Mapped[float | None] = mapped_column(Numeric(20, 4))
    turnover_rate: Mapped[float | None] = mapped_column(Numeric(12, 4))
    turnover_rate_f: Mapped[float | None] = mapped_column(Numeric(12, 4))
    pe: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pe_ttm: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pb: Mapped[float | None] = mapped_column(Numeric(18, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'index_dailybasic'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
