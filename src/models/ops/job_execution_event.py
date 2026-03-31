from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class JobExecutionEvent(Base):
    __tablename__ = "job_execution_event"
    __table_args__ = (
        Index("idx_job_execution_event_execution_occurred_at", "execution_id", "occurred_at"),
        Index("idx_job_execution_event_step_occurred_at", "step_id", "occurred_at"),
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
