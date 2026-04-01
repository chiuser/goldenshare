from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class DcDaily(TimestampMixin, Base):
    __tablename__ = "dc_daily"
    __table_args__ = (
        Index("idx_dc_daily_trade_date", "trade_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    change: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pct_change: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    swing: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
