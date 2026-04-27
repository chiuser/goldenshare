from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class DatasetLayerSnapshotCurrent(Base):
    __tablename__ = "dataset_layer_snapshot_current"
    __table_args__ = (
        PrimaryKeyConstraint("dataset_key", "source_key", "stage", name="pk_dataset_layer_snapshot_current"),
        Index("idx_dataset_layer_snapshot_current_stage_status", "stage", "status"),
        Index("idx_dataset_layer_snapshot_current_calculated_at", "calculated_at"),
        {"schema": "ops"},
    )

    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(32), nullable=False, default="combined")
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rows_in: Mapped[int | None] = mapped_column(BigInteger().with_variant(Integer, "sqlite"))
    rows_out: Mapped[int | None] = mapped_column(BigInteger().with_variant(Integer, "sqlite"))
    error_count: Mapped[int | None] = mapped_column(Integer)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lag_seconds: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    status_reason_code: Mapped[str | None] = mapped_column(String(64))
    task_run_id: Mapped[int | None] = mapped_column(BigInteger)
    run_profile: Mapped[str | None] = mapped_column(String(32))
