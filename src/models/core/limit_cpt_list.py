from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class LimitCptList(TimestampMixin, Base):
    __tablename__ = "limit_cpt_list"
    __table_args__ = (
        Index("idx_limit_cpt_list_trade_date", "trade_date"),
        Index("idx_limit_cpt_list_rank_trade_date", "rank", "trade_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    days: Mapped[int | None] = mapped_column(Integer)
    up_stat: Mapped[str | None] = mapped_column(String(64))
    cons_nums: Mapped[int | None] = mapped_column(Integer)
    up_nums: Mapped[int | None] = mapped_column(Integer)
    pct_chg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    rank: Mapped[str | None] = mapped_column(String(32))
    raw_payload: Mapped[str | None] = mapped_column(Text)
