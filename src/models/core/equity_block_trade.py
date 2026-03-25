from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class EquityBlockTrade(TimestampMixin, Base):
    __tablename__ = "equity_block_trade"
    __table_args__ = (
        Index("idx_equity_block_trade_trade_date", "trade_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    buyer: Mapped[str] = mapped_column(String(128), primary_key=True)
    seller: Mapped[str] = mapped_column(String(128), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), primary_key=True)
    vol: Mapped[Decimal] = mapped_column(Numeric(20, 4), primary_key=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
