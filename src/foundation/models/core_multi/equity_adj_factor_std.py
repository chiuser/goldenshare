from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityAdjFactorStd(TimestampMixin, Base):
    __tablename__ = "equity_adj_factor_std"
    __table_args__ = (
        Index("idx_equity_adj_factor_std_trade_date", "trade_date"),
        Index("idx_equity_adj_factor_std_source_trade_date", "source_key", "trade_date"),
        {"schema": "core_multi"},
    )

    source_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adj_factor: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
