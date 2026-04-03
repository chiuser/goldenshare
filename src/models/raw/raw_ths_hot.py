from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawThsHot(Base):
    __tablename__ = "ths_hot"
    __table_args__ = {"schema": "raw"}

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    data_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    rank_time: Mapped[str] = mapped_column(String(32), primary_key=True)
    query_market: Mapped[str] = mapped_column(String(32), primary_key=True)
    query_is_new: Mapped[str] = mapped_column(String(8), primary_key=True)
    ts_name: Mapped[str | None] = mapped_column(String(128))
    rank: Mapped[int | None] = mapped_column(Integer)
    pct_change: Mapped[float | None] = mapped_column(Numeric(10, 4))
    current_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    concept: Mapped[str | None] = mapped_column(Text)
    rank_reason: Mapped[str | None] = mapped_column(Text)
    hot: Mapped[float | None] = mapped_column(Numeric(20, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'ths_hot'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
