from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityMargin(TimestampMixin, Base):
    __tablename__ = "equity_margin"
    __table_args__ = (
        Index("idx_equity_margin_trade_date", "trade_date"),
        Index("idx_equity_margin_exchange_trade_date", "exchange_id", "trade_date"),
        {"schema": "core_serving"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    exchange_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    rzye: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rzmre: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rzche: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rqye: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rqmcl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rzrqye: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rqyl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
