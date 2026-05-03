from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class DatasetDateCompletenessRun(TimestampMixin, Base):
    __tablename__ = "dataset_date_completeness_run"
    __table_args__ = (
        CheckConstraint("run_mode IN ('manual', 'scheduled')", name="dataset_date_completeness_run_mode_allowed"),
        CheckConstraint(
            "run_status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name="dataset_date_completeness_run_status_allowed",
        ),
        CheckConstraint(
            "(result_status IS NULL) OR (result_status IN ('passed', 'failed', 'error'))",
            name="dataset_date_completeness_result_status_allowed",
        ),
        CheckConstraint("start_date <= end_date", name="dataset_date_completeness_run_range_valid"),
        CheckConstraint("expected_bucket_count >= 0", name="dataset_date_completeness_expected_non_negative"),
        CheckConstraint("actual_bucket_count >= 0", name="dataset_date_completeness_actual_non_negative"),
        CheckConstraint("missing_bucket_count >= 0", name="dataset_date_completeness_missing_non_negative"),
        CheckConstraint("excluded_bucket_count >= 0", name="dataset_date_completeness_excluded_non_negative"),
        CheckConstraint("gap_range_count >= 0", name="dataset_date_completeness_gap_range_non_negative"),
        CheckConstraint(
            "(result_status <> 'passed') OR (missing_bucket_count = 0)",
            name="dataset_date_completeness_passed_has_no_missing",
        ),
        CheckConstraint(
            "(result_status <> 'failed') OR (missing_bucket_count > 0)",
            name="dataset_date_completeness_failed_has_missing",
        ),
        Index("idx_dataset_date_completeness_run_status_requested", "run_status", "requested_at"),
        Index("idx_dataset_date_completeness_run_dataset_requested", "dataset_key", "requested_at"),
        Index("idx_dataset_date_completeness_run_result_finished", "result_status", "finished_at"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    dataset_key: Mapped[str] = mapped_column(String(96), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    target_table: Mapped[str] = mapped_column(String(160), nullable=False)

    run_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    run_status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", server_default="queued")
    result_status: Mapped[str | None] = mapped_column(String(24))

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    date_axis: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket_rule: Mapped[str] = mapped_column(String(32), nullable=False)
    window_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    input_shape: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_field: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket_window_rule: Mapped[str] = mapped_column(String(32), nullable=False, default="none", server_default="none")
    bucket_applicability_rule: Mapped[str] = mapped_column(String(64), nullable=False, default="always", server_default="always")
    row_identity_filters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")

    expected_bucket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    actual_bucket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    missing_bucket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    excluded_bucket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    gap_range_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    current_stage: Mapped[str | None] = mapped_column(String(64))
    operator_message: Mapped[str | None] = mapped_column(Text)
    technical_message: Mapped[str | None] = mapped_column(Text)

    requested_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    schedule_id: Mapped[int | None] = mapped_column(BigInteger)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
