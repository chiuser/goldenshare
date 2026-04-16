from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawStockSt(Base):
    __tablename__ = "stock_st"
    __table_args__ = (
        Index("idx_raw_tushare_stock_st_trade_date", "trade_date"),
        Index("idx_raw_tushare_stock_st_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    type_name: Mapped[str | None] = mapped_column(String(128))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'stock_st'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
