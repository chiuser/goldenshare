from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawDailyBasic(Base):
    __tablename__ = "daily_basic"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    turnover_rate: Mapped[float | None] = mapped_column(Numeric(12, 4))
    turnover_rate_f: Mapped[float | None] = mapped_column(Numeric(12, 4))
    volume_ratio: Mapped[float | None] = mapped_column(Numeric(12, 4))
    pe: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pe_ttm: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pb: Mapped[float | None] = mapped_column(Numeric(18, 4))
    ps: Mapped[float | None] = mapped_column(Numeric(18, 4))
    ps_ttm: Mapped[float | None] = mapped_column(Numeric(18, 4))
    dv_ratio: Mapped[float | None] = mapped_column(Numeric(12, 4))
    dv_ttm: Mapped[float | None] = mapped_column(Numeric(12, 4))
    total_share: Mapped[float | None] = mapped_column(Numeric(20, 4))
    float_share: Mapped[float | None] = mapped_column(Numeric(20, 4))
    free_share: Mapped[float | None] = mapped_column(Numeric(20, 4))
    total_mv: Mapped[float | None] = mapped_column(Numeric(20, 4))
    circ_mv: Mapped[float | None] = mapped_column(Numeric(20, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'daily_basic'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
