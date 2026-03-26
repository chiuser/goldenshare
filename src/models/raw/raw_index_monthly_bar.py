from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawIndexMonthlyBar(Base):
    __tablename__ = "index_monthly_bar"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    open: Mapped[float | None] = mapped_column(Numeric(18, 4))
    high: Mapped[float | None] = mapped_column(Numeric(18, 4))
    low: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pre_close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    change: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[float | None] = mapped_column(Numeric(10, 4))
    vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'index_monthly'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
