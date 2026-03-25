from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class EquityLimitList(TimestampMixin, Base):
    __tablename__ = "equity_limit_list"
    __table_args__ = (
        Index("idx_equity_limit_list_trade_date", "trade_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    limit_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    industry: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(64))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    limit_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    float_mv: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    total_mv: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    turnover_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fd_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    first_time: Mapped[str | None] = mapped_column(String(16))
    last_time: Mapped[str | None] = mapped_column(String(16))
    open_times: Mapped[int | None] = mapped_column(Integer)
    up_stat: Mapped[str | None] = mapped_column(String(16))
    limit_times: Mapped[int | None] = mapped_column(Integer)
