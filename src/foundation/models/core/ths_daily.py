from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class ThsDaily(TimestampMixin, Base):
    __tablename__ = "ths_daily"
    __table_args__ = (
        Index("idx_ths_daily_trade_date", "trade_date"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    open: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    high: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    low: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    pre_close: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    change: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    pct_change: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    vol: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    total_mv: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    float_mv: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
