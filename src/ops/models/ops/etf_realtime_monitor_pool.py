from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EtfRealtimeMonitorPool(TimestampMixin, Base):
    __tablename__ = "etf_realtime_monitor_pool"
    __table_args__ = (
        Index("uq_etf_realtime_monitor_pool_ts_code", "ts_code", unique=True),
        Index("idx_etf_realtime_monitor_pool_group_enabled", "group_key", "enabled"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    group_key: Mapped[str] = mapped_column(String(64), nullable=False)
    group_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
