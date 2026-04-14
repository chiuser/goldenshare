from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawDcMember(Base):
    __tablename__ = "dc_member"
    __table_args__ = {"schema": "raw_tushare"}

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    con_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'dc_member'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
