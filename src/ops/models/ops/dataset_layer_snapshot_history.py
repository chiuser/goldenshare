from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class DatasetLayerSnapshotHistory(Base):
    __tablename__ = "dataset_layer_snapshot_history"
    __table_args__ = (
        Index("idx_dataset_layer_snapshot_history_snapshot_date", "snapshot_date"),
        Index("idx_dataset_layer_snapshot_history_dataset_stage", "dataset_key", "stage", "snapshot_date"),
        Index("idx_dataset_layer_snapshot_history_source_stage", "source_key", "stage", "snapshot_date"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rows_in: Mapped[int | None] = mapped_column(BigInteger)
    rows_out: Mapped[int | None] = mapped_column(BigInteger)
    error_count: Mapped[int | None] = mapped_column(Integer)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lag_seconds: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
