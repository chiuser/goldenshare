from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawTopList(Base):
    __tablename__ = "top_list"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pct_change: Mapped[float | None] = mapped_column(Numeric(10, 4))
    turnover_rate: Mapped[float | None] = mapped_column(Numeric(12, 4))
    amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    l_sell: Mapped[float | None] = mapped_column(Numeric(20, 4))
    l_buy: Mapped[float | None] = mapped_column(Numeric(20, 4))
    l_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    net_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    net_rate: Mapped[float | None] = mapped_column(Numeric(12, 4))
    amount_rate: Mapped[float | None] = mapped_column(Numeric(12, 4))
    float_values: Mapped[float | None] = mapped_column(Numeric(20, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'top_list'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
