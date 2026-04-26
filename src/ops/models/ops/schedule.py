from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class OpsSchedule(TimestampMixin, Base):
    __tablename__ = "schedule"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('dataset_action', 'workflow', 'maintenance_action')",
            name="ck_ops_schedule_target_type_allowed",
        ),
        CheckConstraint(
            "(target_type <> 'dataset_action') OR (target_key LIKE '%.maintain')",
            name="ck_ops_schedule_dataset_action_target_key_maintain",
        ),
        Index("idx_ops_schedule_status_next_run_at", "status", "next_run_at"),
        Index("idx_ops_schedule_target_type_target_key", "target_type", "target_key"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    schedule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="schedule", server_default="schedule")
    cron_expr: Mapped[str | None] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai")
    calendar_policy: Mapped[str | None] = mapped_column(String(32))
    probe_config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retry_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    concurrency_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
