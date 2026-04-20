from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class JobExecutionEvent(Base):
    __tablename__ = "job_execution_event"
    __table_args__ = (
        UniqueConstraint("event_id", name="uk_job_execution_event_event_id"),
        Index("idx_job_execution_event_execution_occurred_at", "execution_id", "occurred_at"),
        Index("idx_job_execution_event_step_occurred_at", "step_id", "occurred_at"),
        Index(
            "idx_job_execution_event_correlation_occurred",
            "correlation_id",
            "occurred_at",
        ),
        Index(
            "idx_job_execution_event_execution_step_unit_occurred",
            "execution_id",
            "step_id",
            "unit_id",
            "occurred_at",
        ),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    step_id: Mapped[int | None] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO", server_default="INFO")
    message: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, default=lambda: uuid4().hex)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    unit_id: Mapped[str | None] = mapped_column(String(128))
    producer: Mapped[str] = mapped_column(String(32), nullable=False, default="runtime", server_default="runtime")
    dedupe_key: Mapped[str | None] = mapped_column(String(128))
