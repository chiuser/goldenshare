from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityBlockTrade(TimestampMixin, Base):
    __tablename__ = "equity_block_trade"
    __table_args__ = (
        Index("idx_equity_block_trade_trade_date", "trade_date"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16))
    trade_date: Mapped[date] = mapped_column(Date)
    buyer: Mapped[str | None] = mapped_column(String(128))
    seller: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    vol: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
