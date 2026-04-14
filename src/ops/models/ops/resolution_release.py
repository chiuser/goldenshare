from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class ResolutionRelease(TimestampMixin, Base):
    __tablename__ = "resolution_release"
    __table_args__ = (
        Index("idx_resolution_release_dataset_triggered_at", "dataset_key", "triggered_at"),
        Index("idx_resolution_release_status_triggered_at", "status", "triggered_at"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    target_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="previewing", server_default="previewing")
    triggered_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rollback_to_release_id: Mapped[int | None] = mapped_column(BigInteger)
