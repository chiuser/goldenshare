from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Index, Integer, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EtfRealtimeMonitorRule(TimestampMixin, Base):
    __tablename__ = "etf_realtime_monitor_rule"
    __table_args__ = (
        Index("uq_etf_realtime_monitor_rule_scope_window", "scope_type", "scope_key", "window_minutes", unique=True),
        Index("idx_etf_realtime_monitor_rule_enabled", "enabled"),
        CheckConstraint("scope_type in ('global', 'group', 'etf')", name="scope_type_valid"),
        CheckConstraint("window_minutes in (1, 5, 15)", name="window_minutes_valid"),
        CheckConstraint("observe_ratio > 0", name="observe_ratio_positive"),
        CheckConstraint("observe_ratio <= alert_ratio", name="observe_not_above_alert"),
        CheckConstraint("alert_ratio <= strong_ratio", name="alert_not_above_strong"),
        CheckConstraint("cooldown_minutes > 0", name="cooldown_minutes_positive"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    window_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    observe_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    alert_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    strong_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    feishu_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
