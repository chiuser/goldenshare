from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawEtfShareSize(Base):
    __tablename__ = "etf_share_size"
    __table_args__ = (
        Index("idx_raw_tushare_etf_share_size_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "raw_tushare"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    etf_name: Mapped[str | None] = mapped_column(String(256))
    total_share: Mapped[float | None] = mapped_column(Numeric(24, 6))
    total_size: Mapped[float | None] = mapped_column(Numeric(24, 6))
    nav: Mapped[float | None] = mapped_column(Numeric(18, 8))
    close: Mapped[float | None] = mapped_column(Numeric(18, 8))
    exchange: Mapped[str | None] = mapped_column(String(16))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'etf_share_size'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
