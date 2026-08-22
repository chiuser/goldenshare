from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Numeric, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class EtfRealtimeMinuteStat(Base):
    __tablename__ = "etf_realtime_minute_stat"
    __table_args__ = (
        Index("idx_etf_realtime_minute_stat_code_date", "ts_code", "trade_date"),
        Index("idx_etf_realtime_minute_stat_date_bucket", "trade_date", "minute_bucket"),
        Index("idx_etf_realtime_minute_stat_quality_date", "data_quality", "trade_date"),
        {"schema": "ops"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    minute_bucket: Mapped[time] = mapped_column(Time, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    source_trade_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_batch_id: Mapped[str | None] = mapped_column(String(64))
    previous_batch_id: Mapped[str | None] = mapped_column(String(64))
    cumulative_amount_yuan: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    amount_delta_yuan: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    cumulative_vol: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    vol_delta: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    data_quality: Mapped[str] = mapped_column(String(16), nullable=False)
    missing_reason: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
