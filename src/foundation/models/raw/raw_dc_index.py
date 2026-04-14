from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawDcIndex(Base):
    __tablename__ = "dc_index"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    leading: Mapped[str | None] = mapped_column(String(128))
    leading_code: Mapped[str | None] = mapped_column(String(16))
    pct_change: Mapped[float | None] = mapped_column(Numeric(10, 4))
    leading_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))
    total_mv: Mapped[float | None] = mapped_column(Numeric(20, 4))
    turnover_rate: Mapped[float | None] = mapped_column(Numeric(12, 4))
    up_num: Mapped[int | None] = mapped_column(Integer)
    down_num: Mapped[int | None] = mapped_column(Integer)
    idx_type: Mapped[str | None] = mapped_column(String(32))
    level: Mapped[str | None] = mapped_column(String(32))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'dc_index'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
