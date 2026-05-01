from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class TaskRun(TimestampMixin, Base):
    __tablename__ = "task_run"
    __table_args__ = (
        Index("idx_task_run_status_requested_at", "status", "requested_at"),
        Index("idx_task_run_resource_requested_at", "resource_key", "requested_at"),
        Index("idx_task_run_schedule_requested_at", "schedule_id", "requested_at"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_key: Mapped[str | None] = mapped_column(String(96))
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="maintain", server_default="maintain")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    schedule_id: Mapped[int | None] = mapped_column(BigInteger)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", server_default="queued")
    status_reason_code: Mapped[str | None] = mapped_column(String(64))

    time_input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    filters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    request_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    plan_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    unit_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    unit_done: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    unit_failed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    progress_percent: Mapped[int | None] = mapped_column(Integer)
    current_node_id: Mapped[int | None] = mapped_column(BigInteger)
    current_object_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    rows_fetched: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rows_saved: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rows_rejected: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rejected_reason_counts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    primary_issue_id: Mapped[int | None] = mapped_column(BigInteger)

    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
