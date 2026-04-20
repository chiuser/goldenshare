from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class JobExecutionStep(TimestampMixin, Base):
    __tablename__ = "job_execution_step"
    __table_args__ = (
        Index("idx_job_execution_step_execution_sequence", "execution_id", "sequence_no"),
        Index("idx_job_execution_step_execution_status", "execution_id", "status"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    step_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence_no: Mapped[int] = mapped_column(nullable=False)
    unit_kind: Mapped[str | None] = mapped_column(String(32))
    unit_value: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_fetched: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rows_written: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    message: Mapped[str | None] = mapped_column(Text)
    failure_policy_effective: Mapped[str | None] = mapped_column(String(32))
    depends_on_step_keys_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    blocked_by_step_key: Mapped[str | None] = mapped_column(String(128))
    skip_reason_code: Mapped[str | None] = mapped_column(String(64))
    unit_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    unit_done: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    unit_failed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
