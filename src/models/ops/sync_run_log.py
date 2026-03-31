from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class SyncRunLog(Base):
    __tablename__ = "sync_run_log"
    __table_args__ = (
        Index("idx_sync_run_log_job_name_started_at", "job_name", "started_at"),
        Index("idx_sync_run_log_execution_id", "execution_id"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    execution_id: Mapped[int | None] = mapped_column(BigInteger)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)
    run_type: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rows_fetched: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    rows_written: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    message: Mapped[str | None] = mapped_column(Text)
