from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class JobExecution(TimestampMixin, Base):
    __tablename__ = "job_execution"
    __table_args__ = (
        Index("idx_job_execution_status_requested_at", "status", "requested_at"),
        Index("idx_job_execution_schedule_id_requested_at", "schedule_id", "requested_at"),
        Index("idx_job_execution_spec_requested_at", "spec_type", "spec_key", "requested_at"),
        Index("idx_job_execution_dataset_requested_at", "dataset_key", "requested_at"),
        Index("idx_job_execution_source_stage_requested_at", "source_key", "stage", "requested_at"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    schedule_id: Mapped[int | None] = mapped_column(BigInteger)
    spec_type: Mapped[str] = mapped_column(String(32), nullable=False)
    spec_key: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_key: Mapped[str | None] = mapped_column(String(64))
    source_key: Mapped[str | None] = mapped_column(String(32))
    stage: Mapped[str | None] = mapped_column(String(16))
    policy_version: Mapped[int | None] = mapped_column(Integer)
    run_scope: Mapped[str | None] = mapped_column(String(32))
    trigger_source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", server_default="queued")
    priority: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    requested_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    summary_message: Mapped[str | None] = mapped_column(Text)
    rows_fetched: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rows_written: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    progress_current: Mapped[int | None] = mapped_column(BigInteger)
    progress_total: Mapped[int | None] = mapped_column(BigInteger)
    progress_percent: Mapped[int | None] = mapped_column(Integer)
    progress_message: Mapped[str | None] = mapped_column(Text)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
