from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class StkPeriodBarAdj(TimestampMixin, Base):
    __tablename__ = "stk_period_bar_adj"
    __table_args__ = (
        Index("idx_stk_period_bar_adj_freq_trade_date", "freq", "trade_date"),
        Index("idx_stk_period_bar_adj_trade_date", "trade_date"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    freq: Mapped[str] = mapped_column(String(8), primary_key=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pre_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    open_qfq: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high_qfq: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low_qfq: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close_qfq: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    open_hfq: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high_hfq: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low_hfq: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close_hfq: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    change_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
