from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawStkPeriodBarAdj(Base):
    __tablename__ = "stk_period_bar_adj"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    freq: Mapped[str] = mapped_column(String(8), primary_key=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    open: Mapped[float | None] = mapped_column(Numeric(18, 4))
    high: Mapped[float | None] = mapped_column(Numeric(18, 4))
    low: Mapped[float | None] = mapped_column(Numeric(18, 4))
    close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pre_close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    open_qfq: Mapped[float | None] = mapped_column(Numeric(18, 4))
    high_qfq: Mapped[float | None] = mapped_column(Numeric(18, 4))
    low_qfq: Mapped[float | None] = mapped_column(Numeric(18, 4))
    close_qfq: Mapped[float | None] = mapped_column(Numeric(18, 4))
    open_hfq: Mapped[float | None] = mapped_column(Numeric(18, 4))
    high_hfq: Mapped[float | None] = mapped_column(Numeric(18, 4))
    low_hfq: Mapped[float | None] = mapped_column(Numeric(18, 4))
    close_hfq: Mapped[float | None] = mapped_column(Numeric(18, 4))
    vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    change: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[float | None] = mapped_column(Numeric(10, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'stk_week_month_adj'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
