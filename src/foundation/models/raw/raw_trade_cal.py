from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawTradeCal(Base):
    __tablename__ = "trade_cal"
    __table_args__ = {"schema": "raw"}

    exchange: Mapped[str] = mapped_column(String(16), primary_key=True)
    cal_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool | None] = mapped_column(Boolean)
    pretrade_date: Mapped[date | None] = mapped_column(Date)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'trade_cal'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
