from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawHkBasic(Base):
    __tablename__ = "hk_basic"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    fullname: Mapped[str | None] = mapped_column(String(256))
    enname: Mapped[str | None] = mapped_column(String(256))
    cn_spell: Mapped[str | None] = mapped_column(String(64))
    market: Mapped[str | None] = mapped_column(String(32))
    list_status: Mapped[str | None] = mapped_column(String(8))
    list_date: Mapped[date | None] = mapped_column(Date)
    delist_date: Mapped[date | None] = mapped_column(Date)
    trade_unit: Mapped[int | None] = mapped_column(Integer)
    isin: Mapped[str | None] = mapped_column(String(32))
    curr_type: Mapped[str | None] = mapped_column(String(16))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'hk_basic'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
