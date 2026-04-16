from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawMargin(Base):
    __tablename__ = "margin"
    __table_args__ = (
        Index("idx_raw_tushare_margin_trade_date", "trade_date"),
        Index("idx_raw_tushare_margin_exchange_trade_date", "exchange_id", "trade_date"),
        {"schema": "raw_tushare"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    exchange_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    rzye: Mapped[float | None] = mapped_column(Numeric(20, 4))
    rzmre: Mapped[float | None] = mapped_column(Numeric(20, 4))
    rzche: Mapped[float | None] = mapped_column(Numeric(20, 4))
    rqye: Mapped[float | None] = mapped_column(Numeric(20, 4))
    rqmcl: Mapped[float | None] = mapped_column(Numeric(20, 4))
    rzrqye: Mapped[float | None] = mapped_column(Numeric(20, 4))
    rqyl: Mapped[float | None] = mapped_column(Numeric(20, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'margin'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
