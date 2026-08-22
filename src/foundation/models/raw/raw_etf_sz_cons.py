from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawEtfSzCons(Base):
    __tablename__ = "etf_sz_cons"
    __table_args__ = (
        Index("idx_raw_tushare_etf_sz_cons_ts_code_trade_date", "ts_code", "trade_date"),
        Index("idx_raw_tushare_etf_sz_cons_con_code", "con_code"),
        {"schema": "raw_tushare"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    con_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    con_name: Mapped[str | None] = mapped_column(String(128))
    qty: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    sub_flag: Mapped[str | None] = mapped_column(String(16))
    cpr: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    rdr: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    sub_cc: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    red_cc: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    exchange: Mapped[str | None] = mapped_column(String(16))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'etf_sz_cons'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
