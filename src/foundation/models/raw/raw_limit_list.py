from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawLimitList(Base):
    __tablename__ = "limit_list"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    limit: Mapped[str] = mapped_column(String(8), primary_key=True)
    industry: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(64))
    close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[float | None] = mapped_column(Numeric(10, 4))
    amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    limit_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    float_mv: Mapped[float | None] = mapped_column(Numeric(20, 4))
    total_mv: Mapped[float | None] = mapped_column(Numeric(20, 4))
    turnover_ratio: Mapped[float | None] = mapped_column(Numeric(12, 4))
    fd_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    first_time: Mapped[str | None] = mapped_column(String(16))
    last_time: Mapped[str | None] = mapped_column(String(16))
    open_times: Mapped[int | None] = mapped_column(Integer)
    up_stat: Mapped[str | None] = mapped_column(String(16))
    limit_times: Mapped[int | None] = mapped_column(Integer)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'limit_list_d'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
