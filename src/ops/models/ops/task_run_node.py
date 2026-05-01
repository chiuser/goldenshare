from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class TaskRunNode(TimestampMixin, Base):
    __tablename__ = "task_run_node"
    __table_args__ = (
        UniqueConstraint("task_run_id", "node_key", name="uk_task_run_node_run_node_key"),
        Index("idx_task_run_node_run_sequence", "task_run_id", "sequence_no", "id"),
        Index("idx_task_run_node_run_status", "task_run_id", "status"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ops.task_run.id", ondelete="CASCADE"), nullable=False)
    parent_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ops.task_run_node.id", ondelete="CASCADE"))

    node_key: Mapped[str] = mapped_column(String(160), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_key: Mapped[str | None] = mapped_column(String(96))

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    time_input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    rows_fetched: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rows_saved: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rows_rejected: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rejected_reason_counts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    issue_id: Mapped[int | None] = mapped_column(BigInteger)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
