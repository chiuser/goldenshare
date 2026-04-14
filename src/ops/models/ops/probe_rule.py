from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class ProbeRule(TimestampMixin, Base):
    __tablename__ = "probe_rule"
    __table_args__ = (
        Index("idx_probe_rule_status_dataset", "status", "dataset_key"),
        Index("idx_probe_rule_dataset_source", "dataset_key", "source_key"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    window_start: Mapped[str | None] = mapped_column(String(16))
    window_end: Mapped[str | None] = mapped_column(String(16))
    probe_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300, server_default="300")
    probe_condition_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    on_success_action_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    max_triggers_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai")
    last_probed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
