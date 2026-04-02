from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class ThsHot(TimestampMixin, Base):
    __tablename__ = "ths_hot"
    __table_args__ = (
        Index("idx_ths_hot_trade_date", "trade_date"),
        Index("idx_ths_hot_data_type_trade_date", "data_type", "trade_date"),
        Index("idx_ths_hot_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "core"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    data_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    rank_time: Mapped[str] = mapped_column(String(32), primary_key=True)
    query_market: Mapped[str] = mapped_column(String(32), primary_key=True)
    query_is_new: Mapped[str] = mapped_column(String(8), primary_key=True)
    ts_name: Mapped[str | None] = mapped_column(String(128))
    rank: Mapped[int | None] = mapped_column(Integer)
    pct_change: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    concept: Mapped[str | None] = mapped_column(String(512))
    rank_reason: Mapped[str | None] = mapped_column(String(512))
    hot: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    raw_payload: Mapped[str | None] = mapped_column(Text)
