from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawBrokerRecommend(Base):
    __tablename__ = "broker_recommend"
    __table_args__ = {"schema": "raw"}

    month: Mapped[str] = mapped_column(String(6), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    broker: Mapped[str] = mapped_column(String(128), primary_key=True)
    currency: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(128))
    trade_date: Mapped[date | None] = mapped_column(Date)
    close: Mapped[float | None] = mapped_column(Numeric(20, 4))
    pct_change: Mapped[float | None] = mapped_column(Numeric(10, 4))
    target_price: Mapped[float | None] = mapped_column(Numeric(20, 4))
    industry: Mapped[str | None] = mapped_column(String(128))
    broker_mkt: Mapped[str | None] = mapped_column(String(64))
    author: Mapped[str | None] = mapped_column(String(128))
    recom_type: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    offset: Mapped[int | None] = mapped_column(Integer)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'broker_recommend'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
