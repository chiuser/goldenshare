from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class LimitListThs(TimestampMixin, Base):
    __tablename__ = "limit_list_ths"
    __table_args__ = (
        Index("idx_limit_list_ths_trade_date", "trade_date"),
        Index("idx_limit_list_ths_query_trade_date", "query_limit_type", "trade_date"),
        Index("idx_limit_list_ths_market_trade_date", "query_market", "trade_date"),
        Index("idx_limit_list_ths_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "core"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    query_limit_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    query_market: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    open_num: Mapped[int | None] = mapped_column(Integer)
    lu_desc: Mapped[str | None] = mapped_column(Text)
    limit_type: Mapped[str | None] = mapped_column(String(32))
    tag: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(64))
    first_lu_time: Mapped[str | None] = mapped_column(String(32))
    last_lu_time: Mapped[str | None] = mapped_column(String(32))
    first_ld_time: Mapped[str | None] = mapped_column(String(32))
    last_ld_time: Mapped[str | None] = mapped_column(String(32))
    limit_order: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    limit_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    free_float: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    lu_limit_order: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    limit_up_suc_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rise_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    sum_float: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    market_type: Mapped[str | None] = mapped_column(String(16))
    raw_payload: Mapped[str | None] = mapped_column(Text)
