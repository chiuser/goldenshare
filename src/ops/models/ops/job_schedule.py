from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class JobSchedule(TimestampMixin, Base):
    __tablename__ = "job_schedule"
    __table_args__ = (
        Index("idx_job_schedule_status_next_run_at", "status", "next_run_at"),
        Index("idx_job_schedule_spec_type_spec_key", "spec_type", "spec_key"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    spec_type: Mapped[str] = mapped_column(String(32), nullable=False)
    spec_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    schedule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cron_expr: Mapped[str | None] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai")
    calendar_policy: Mapped[str | None] = mapped_column(String(32))
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retry_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    concurrency_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
