from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityStockSt(TimestampMixin, Base):
    __tablename__ = "equity_stock_st"
    __table_args__ = (
        Index("idx_equity_stock_st_trade_date", "trade_date"),
        Index("idx_equity_stock_st_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    type_name: Mapped[str | None] = mapped_column(String(128))
