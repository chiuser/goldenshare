from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawThsDaily(Base):
    __tablename__ = "ths_daily"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float | None] = mapped_column(Numeric(24, 6))
    open: Mapped[float | None] = mapped_column(Numeric(24, 6))
    high: Mapped[float | None] = mapped_column(Numeric(24, 6))
    low: Mapped[float | None] = mapped_column(Numeric(24, 6))
    pre_close: Mapped[float | None] = mapped_column(Numeric(24, 6))
    avg_price: Mapped[float | None] = mapped_column(Numeric(24, 6))
    change: Mapped[float | None] = mapped_column(Numeric(24, 6))
    pct_change: Mapped[float | None] = mapped_column(Numeric(18, 6))
    vol: Mapped[float | None] = mapped_column(Numeric(30, 4))
    turnover_rate: Mapped[float | None] = mapped_column(Numeric(18, 6))
    total_mv: Mapped[float | None] = mapped_column(Numeric(30, 4))
    float_mv: Mapped[float | None] = mapped_column(Numeric(30, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'ths_daily'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
