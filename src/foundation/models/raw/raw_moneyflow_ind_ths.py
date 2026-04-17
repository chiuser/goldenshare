from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawMoneyflowIndThs(Base):
    __tablename__ = "moneyflow_ind_ths"
    __table_args__ = {"schema": "raw_tushare"}

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    industry: Mapped[str | None] = mapped_column(String(128))
    lead_stock: Mapped[str | None] = mapped_column(String(128))
    close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pct_change: Mapped[float | None] = mapped_column(Numeric(10, 4))
    company_num: Mapped[int | None] = mapped_column(Integer)
    pct_change_stock: Mapped[float | None] = mapped_column(Numeric(10, 4))
    close_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    net_buy_amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    net_sell_amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    net_amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'moneyflow_ind_ths'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
