from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, JSON, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class WealthMarketTurnoverSnapshot(Base):
    __tablename__ = "wealth_market_turnover_snapshot"
    __table_args__ = (
        Index(
            "idx_wealth_market_turnover_snapshot_lookup",
            "type",
            "market",
            "freq",
            "build_status",
            "trade_date",
        ),
        {"schema": "core_serving"},
    )

    type: Mapped[str] = mapped_column(String(16), primary_key=True)
    market: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    freq: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    latest_trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    security_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    total_vol: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    build_status: Mapped[str] = mapped_column(String(16), nullable=False, default="READY", server_default="READY")
    build_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1", server_default="v1")
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    build_note: Mapped[str | None] = mapped_column(Text)
