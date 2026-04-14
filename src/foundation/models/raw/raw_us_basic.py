from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawUsBasic(Base):
    __tablename__ = "us_basic"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    enname: Mapped[str | None] = mapped_column(String(256))
    classify: Mapped[str | None] = mapped_column(String(16))
    list_date: Mapped[date | None] = mapped_column(Date)
    delist_date: Mapped[date | None] = mapped_column(Date)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'us_basic'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
