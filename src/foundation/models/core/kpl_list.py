from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class KplList(TimestampMixin, Base):
    __tablename__ = "kpl_list"
    __table_args__ = (
        Index("idx_kpl_list_trade_date", "trade_date"),
        Index("idx_kpl_list_tag_trade_date", "tag", "trade_date"),
        Index("idx_kpl_list_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "core_serving"},
    )

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
    net_change: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    bid_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    status: Mapped[str | None] = mapped_column(String(64))
    bid_change: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    bid_turnover: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    lu_bid_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    pct_chg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    bid_pct_chg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    rt_pct_chg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    limit_order: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    free_float: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    lu_limit_order: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    raw_payload: Mapped[str | None] = mapped_column(Text)
