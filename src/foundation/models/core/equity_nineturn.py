from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityNineTurn(TimestampMixin, Base):
    __tablename__ = "equity_nineturn"
    __table_args__ = (
        Index("idx_equity_nineturn_trade_date", "trade_date"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    freq: Mapped[str | None] = mapped_column(String(16))
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    up_count: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    down_count: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    nine_up_turn: Mapped[str | None] = mapped_column(String(16))
    nine_down_turn: Mapped[str | None] = mapped_column(String(16))
