from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawTushareStockBasic(Base):
    __tablename__ = "stock_basic"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(64))
    area: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(64))
    fullname: Mapped[str | None] = mapped_column(String(128))
    enname: Mapped[str | None] = mapped_column(String(128))
    cnspell: Mapped[str | None] = mapped_column(String(32))
    market: Mapped[str | None] = mapped_column(String(32))
    exchange: Mapped[str | None] = mapped_column(String(16))
    curr_type: Mapped[str | None] = mapped_column(String(16))
    list_status: Mapped[str | None] = mapped_column(String(8))
    list_date: Mapped[date | None] = mapped_column(Date)
    delist_date: Mapped[date | None] = mapped_column(Date)
    is_hs: Mapped[str | None] = mapped_column(String(8))
    act_name: Mapped[str | None] = mapped_column(String(128))
    act_ent_type: Mapped[str | None] = mapped_column(String(64))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'stock_basic'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
