from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawFundAdj(Base):
    __tablename__ = "fund_adj"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adj_factor: Mapped[float | None] = mapped_column(Numeric(20, 8))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'fund_adj'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
