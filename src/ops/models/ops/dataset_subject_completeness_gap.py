from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class DatasetSubjectCompletenessGap(Base):
    __tablename__ = "dataset_subject_completeness_gap"
    __table_args__ = (
        CheckConstraint("missing_cell_count >= 0", name="dataset_subject_completeness_gap_missing_non_negative"),
        CheckConstraint("affected_subject_count >= 0", name="dataset_subject_completeness_gap_subject_non_negative"),
        Index("idx_dataset_subject_completeness_gap_run", "run_id", "id"),
        Index("idx_dataset_subject_completeness_gap_dataset_bucket", "dataset_key", "bucket_value"),
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
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_key_fields_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    actual_key_fields_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    missing_cell_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    affected_subject_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_subjects_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
