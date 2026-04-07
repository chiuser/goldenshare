from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class BrokerRecommend(TimestampMixin, Base):
    __tablename__ = "broker_recommend"
    __table_args__ = (
        Index("idx_broker_recommend_month", "month"),
        Index("idx_broker_recommend_trade_date", "trade_date"),
        Index("idx_broker_recommend_ts_code_month", "ts_code", "month"),
        {"schema": "core"},
    )

    month: Mapped[str] = mapped_column(String(6), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    broker: Mapped[str] = mapped_column(String(128), primary_key=True)
    currency: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(128))
    trade_date: Mapped[date | None] = mapped_column(Date)
    close: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    pct_change: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    industry: Mapped[str | None] = mapped_column(String(128))
    broker_mkt: Mapped[str | None] = mapped_column(String(64))
    author: Mapped[str | None] = mapped_column(String(128))
    recom_type: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    offset: Mapped[int | None] = mapped_column(Integer)
