from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class DatasetSubjectCompletenessGapDetail(Base):
    __tablename__ = "dataset_subject_completeness_gap_detail"
    __table_args__ = (
        Index("idx_dataset_subject_completeness_detail_run", "run_id", "id"),
        Index("idx_dataset_subject_completeness_detail_gap", "gap_id", "id"),
        Index("idx_dataset_subject_completeness_detail_dataset_bucket", "dataset_key", "bucket_value"),
        Index("idx_dataset_subject_completeness_detail_subject", "dataset_key", "subject_kind", "subject_key"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ops.dataset_date_completeness_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    gap_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ops.dataset_subject_completeness_gap.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_key: Mapped[str] = mapped_column(String(96), nullable=False)
    bucket_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket_value: Mapped[date] = mapped_column(Date, nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(96), nullable=False)
    subject_name: Mapped[str | None] = mapped_column(String(160))
    subject_key_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    actual_key_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lifecycle_start: Mapped[date | None] = mapped_column(Date)
    lifecycle_end: Mapped[date | None] = mapped_column(Date)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_message: Mapped[str] = mapped_column(Text, nullable=False)
    target_table: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
