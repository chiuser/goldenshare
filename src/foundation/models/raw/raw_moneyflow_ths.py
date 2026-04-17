from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawMoneyflowThs(Base):
    __tablename__ = "moneyflow_ths"
    __table_args__ = {"schema": "raw_tushare"}

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    pct_change: Mapped[float | None] = mapped_column(Numeric(10, 4))
    latest: Mapped[float | None] = mapped_column(Numeric(18, 4))
    net_amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    net_d5_amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    buy_lg_amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    buy_lg_amount_rate: Mapped[float | None] = mapped_column(Numeric(10, 4))
    buy_md_amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    buy_md_amount_rate: Mapped[float | None] = mapped_column(Numeric(10, 4))
    buy_sm_amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    buy_sm_amount_rate: Mapped[float | None] = mapped_column(Numeric(10, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'moneyflow_ths'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
