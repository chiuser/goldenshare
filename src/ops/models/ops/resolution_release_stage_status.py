from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class ResolutionReleaseStageStatus(Base):
    __tablename__ = "resolution_release_stage_status"
    __table_args__ = (
        Index("idx_resolution_release_stage_status_release", "release_id", "stage"),
        Index("idx_resolution_release_stage_status_dataset_source", "dataset_key", "source_key", "stage"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    release_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    rows_in: Mapped[int | None] = mapped_column(BigInteger)
    rows_out: Mapped[int | None] = mapped_column(BigInteger)
    message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
