from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class JobExecutionUnit(TimestampMixin, Base):
    __tablename__ = "job_execution_unit"
    __table_args__ = (
        UniqueConstraint("execution_id", "unit_id", name="uk_job_execution_unit_execution_unit"),
        Index("idx_job_execution_unit_step_status", "step_id", "status"),
        Index("idx_job_execution_unit_execution_status", "execution_id", "status"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    step_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retryable: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    rows_fetched: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rows_written: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    unit_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
