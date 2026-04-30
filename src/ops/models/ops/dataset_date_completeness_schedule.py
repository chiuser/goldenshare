from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class DatasetDateCompletenessSchedule(TimestampMixin, Base):
    __tablename__ = "dataset_date_completeness_schedule"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'paused')", name="dataset_date_completeness_schedule_status_allowed"),
        CheckConstraint(
            "window_mode IN ('fixed_range', 'rolling')",
            name="dataset_date_completeness_schedule_window_mode_allowed",
        ),
        CheckConstraint(
            "(window_mode <> 'fixed_range') OR (start_date IS NOT NULL AND end_date IS NOT NULL AND start_date <= end_date)",
            name="dataset_date_completeness_schedule_fixed_range_valid",
        ),
        CheckConstraint(
            "(window_mode <> 'rolling') OR (lookback_count IS NOT NULL AND lookback_count > 0 AND lookback_unit IS NOT NULL)",
            name="dataset_date_completeness_schedule_rolling_window_valid",
        ),
        CheckConstraint(
            "(lookback_unit IS NULL) OR (lookback_unit IN ('calendar_day', 'open_day', 'month'))",
            name="dataset_date_completeness_schedule_lookback_unit_allowed",
        ),
        CheckConstraint(
            "calendar_scope IN ('default_cn_market', 'cn_a_share', 'hk_market', 'custom_exchange')",
            name="dataset_date_completeness_schedule_calendar_scope_allowed",
        ),
        Index("idx_dataset_date_completeness_schedule_status_next", "status", "next_run_at"),
        Index("idx_dataset_date_completeness_schedule_dataset", "dataset_key"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    dataset_key: Mapped[str] = mapped_column(String(96), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")

    window_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    lookback_count: Mapped[int | None] = mapped_column(Integer)
    lookback_unit: Mapped[str | None] = mapped_column(String(32))
    calendar_scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="default_cn_market",
        server_default="default_cn_market",
    )
    calendar_exchange: Mapped[str | None] = mapped_column(String(32))

    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
