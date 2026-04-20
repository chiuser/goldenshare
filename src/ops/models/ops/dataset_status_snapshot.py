from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class DatasetStatusSnapshot(Base):
    __tablename__ = "dataset_status_snapshot"
    __table_args__ = {"schema": "ops"}

    dataset_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    resource_key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    domain_key: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)
    target_table: Mapped[str] = mapped_column(String(128), nullable=False)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False)
    state_business_date: Mapped[date | None] = mapped_column(Date)
    earliest_business_date: Mapped[date | None] = mapped_column(Date)
    observed_business_date: Mapped[date | None] = mapped_column(Date)
    latest_business_date: Mapped[date | None] = mapped_column(Date)
    business_date_source: Mapped[str] = mapped_column(String(32), nullable=False, default="none", server_default="none")
    freshness_note: Mapped[str | None] = mapped_column(Text)
    latest_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_date: Mapped[date | None] = mapped_column(Date)
    expected_business_date: Mapped[date | None] = mapped_column(Date)
    lag_days: Mapped[int | None] = mapped_column(Integer)
    freshness_status: Mapped[str] = mapped_column(String(16), nullable=False)
    recent_failure_message: Mapped[str | None] = mapped_column(Text)
    recent_failure_summary: Mapped[str | None] = mapped_column(String(255))
    recent_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    primary_execution_spec_key: Mapped[str | None] = mapped_column(String(128))
    full_sync_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pipeline_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="single_source_direct", server_default="single_source_direct")
    raw_stage_status: Mapped[str | None] = mapped_column(String(16))
    std_stage_status: Mapped[str | None] = mapped_column(String(16))
    resolution_stage_status: Mapped[str | None] = mapped_column(String(16))
    serving_stage_status: Mapped[str | None] = mapped_column(String(16))
    state_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
