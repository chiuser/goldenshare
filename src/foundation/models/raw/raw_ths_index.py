from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawThsIndex(Base):
    __tablename__ = "ths_index"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    count: Mapped[int | None] = mapped_column(Integer)
    exchange: Mapped[str | None] = mapped_column(String(16))
    list_date: Mapped[date | None] = mapped_column(Date)
    type_: Mapped[str | None] = mapped_column("type", String(32))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'ths_index'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
