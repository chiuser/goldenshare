from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, JSON, Numeric, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class EtfRealtimeAlert(Base):
    __tablename__ = "etf_realtime_alert"
    __table_args__ = (
        Index("idx_etf_realtime_alert_date_code_window", "trade_date", "ts_code", "window_minutes"),
        Index("idx_etf_realtime_alert_triggered_at", "triggered_at"),
        Index("idx_etf_realtime_alert_severity_triggered", "severity", "triggered_at"),
        Index("idx_etf_realtime_alert_cooldown_triggered", "cooldown_key", "triggered_at"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_end_time: Mapped[time] = mapped_column(Time, nullable=False)
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    etf_name: Mapped[str | None] = mapped_column(String(128))
    group_key: Mapped[str] = mapped_column(String(64), nullable=False)
    group_name: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_id: Mapped[int | None] = mapped_column(BigInteger)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    current_amount_yuan: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    baseline_amount_yuan: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    ratio: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    baseline_trade_dates_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    cooldown_key: Mapped[str] = mapped_column(String(256), nullable=False)
    feishu_status: Mapped[str] = mapped_column(String(16), nullable=False)
    feishu_message_id: Mapped[str | None] = mapped_column(String(128))
    feishu_error: Mapped[str | None] = mapped_column(Text)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
