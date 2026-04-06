from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class FundAdjFactor(TimestampMixin, Base):
    __tablename__ = "fund_adj_factor"
    __table_args__ = (
        Index("idx_fund_adj_factor_trade_date", "trade_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adj_factor: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
