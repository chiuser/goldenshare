from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class DatasetDateCompletenessExclusion(Base):
    __tablename__ = "dataset_date_completeness_exclusion"
    __table_args__ = (
        Index("idx_dataset_date_completeness_exclusion_run", "run_id", "id"),
        Index("idx_dataset_date_completeness_exclusion_dataset_bucket", "dataset_key", "bucket_value"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ops.dataset_date_completeness_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_key: Mapped[str] = mapped_column(String(96), nullable=False)
    bucket_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket_value: Mapped[date] = mapped_column(Date, nullable=False)
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
