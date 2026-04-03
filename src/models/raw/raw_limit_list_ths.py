from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawLimitListThs(Base):
    __tablename__ = "limit_list_ths"
    __table_args__ = {"schema": "raw"}

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    query_limit_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    query_market: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[float | None] = mapped_column(Numeric(10, 4))
    open_num: Mapped[int | None] = mapped_column(Integer)
    lu_desc: Mapped[str | None] = mapped_column(Text)
    limit_type: Mapped[str | None] = mapped_column(String(32))
    tag: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(64))
    first_lu_time: Mapped[str | None] = mapped_column(String(32))
    last_lu_time: Mapped[str | None] = mapped_column(String(32))
    first_ld_time: Mapped[str | None] = mapped_column(String(32))
    last_ld_time: Mapped[str | None] = mapped_column(String(32))
    limit_order: Mapped[float | None] = mapped_column(Numeric(20, 4))
    limit_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    turnover_rate: Mapped[float | None] = mapped_column(Numeric(12, 4))
    free_float: Mapped[float | None] = mapped_column(Numeric(20, 4))
    lu_limit_order: Mapped[float | None] = mapped_column(Numeric(20, 4))
    limit_up_suc_rate: Mapped[float | None] = mapped_column(Numeric(10, 4))
    turnover: Mapped[float | None] = mapped_column(Numeric(20, 4))
    rise_rate: Mapped[float | None] = mapped_column(Numeric(10, 4))
    sum_float: Mapped[float | None] = mapped_column(Numeric(20, 4))
    market_type: Mapped[str | None] = mapped_column(String(16))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'limit_list_ths'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
