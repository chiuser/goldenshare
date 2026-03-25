from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class SyncJobState(Base):
    __tablename__ = "sync_job_state"
    __table_args__ = {"schema": "ops"}

    job_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_table: Mapped[str] = mapped_column(String(128), nullable=False)
    last_success_date: Mapped[date | None] = mapped_column(Date)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_cursor: Mapped[str | None] = mapped_column(String(128))
    full_sync_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
