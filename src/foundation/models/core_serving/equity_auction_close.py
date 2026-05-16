from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityAuctionClose(TimestampMixin, Base):
    __tablename__ = "equity_auction_close"
    __table_args__ = (
        Index("idx_equity_auction_close_trade_date", "trade_date"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
