from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class TaskRunIssue(Base):
    __tablename__ = "task_run_issue"
    __table_args__ = (
        UniqueConstraint("task_run_id", "fingerprint", name="uk_task_run_issue_run_fingerprint"),
        Index("idx_task_run_issue_run_occurred", "task_run_id", "occurred_at"),
        Index("idx_task_run_issue_code_occurred", "code", "occurred_at"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ops.task_run.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[int | None] = mapped_column(BigInteger)

    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    operator_message: Mapped[str | None] = mapped_column(Text)
    suggested_action: Mapped[str | None] = mapped_column(Text)

    technical_message: Mapped[str | None] = mapped_column(Text)
    technical_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    object_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_phase: Mapped[str | None] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
