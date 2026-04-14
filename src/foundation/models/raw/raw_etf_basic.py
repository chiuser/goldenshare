from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawEtfBasic(Base):
    __tablename__ = "etf_basic"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    csname: Mapped[str | None] = mapped_column(String(128))
    extname: Mapped[str | None] = mapped_column(String(256))
    cname: Mapped[str | None] = mapped_column(String(256))
    index_code: Mapped[str | None] = mapped_column(String(16))
    index_name: Mapped[str | None] = mapped_column(String(128))
    setup_date: Mapped[date | None] = mapped_column(Date)
    list_date: Mapped[date | None] = mapped_column(Date)
    list_status: Mapped[str | None] = mapped_column(String(8))
    exchange: Mapped[str | None] = mapped_column(String(16))
    mgr_name: Mapped[str | None] = mapped_column(String(128))
    custod_name: Mapped[str | None] = mapped_column(String(128))
    mgt_fee: Mapped[float | None] = mapped_column(Numeric(12, 6))
    etf_type: Mapped[str | None] = mapped_column(String(64))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'etf_basic'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
