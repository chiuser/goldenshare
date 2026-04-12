from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class IndexWeeklyServing(TimestampMixin, Base):
    __tablename__ = "index_weekly_serving"
    __table_args__ = (
        Index("idx_index_weekly_serving_trade_date", "trade_date"),
        Index("idx_index_weekly_serving_period_start", "period_start_date"),
        Index("uq_index_weekly_serving_ts_period", "ts_code", "period_start_date", unique=True),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    period_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pre_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    change_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'api'"))
