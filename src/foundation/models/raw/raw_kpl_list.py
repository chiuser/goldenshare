from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawKplList(Base):
    __tablename__ = "kpl_list"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    tag: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    lu_time: Mapped[str | None] = mapped_column(String(32))
    ld_time: Mapped[str | None] = mapped_column(String(32))
    open_time: Mapped[str | None] = mapped_column(String(32))
    last_time: Mapped[str | None] = mapped_column(String(32))
    lu_desc: Mapped[str | None] = mapped_column(Text)
    theme: Mapped[str | None] = mapped_column(String(256))
    net_change: Mapped[float | None] = mapped_column(Numeric(20, 4))
    bid_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    status: Mapped[str | None] = mapped_column(String(64))
    bid_change: Mapped[float | None] = mapped_column(Numeric(20, 4))
    bid_turnover: Mapped[float | None] = mapped_column(Numeric(12, 4))
    lu_bid_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    pct_chg: Mapped[float | None] = mapped_column(Numeric(10, 4))
    bid_pct_chg: Mapped[float | None] = mapped_column(Numeric(10, 4))
    rt_pct_chg: Mapped[float | None] = mapped_column(Numeric(10, 4))
    limit_order: Mapped[float | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    turnover_rate: Mapped[float | None] = mapped_column(Numeric(12, 4))
    free_float: Mapped[float | None] = mapped_column(Numeric(20, 4))
    lu_limit_order: Mapped[float | None] = mapped_column(Numeric(20, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'kpl_list'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
