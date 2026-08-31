from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKeyConstraint, Integer, Numeric, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class WealthSectorDailyInsightSummary(Base):
    __tablename__ = "wealth_sector_daily_insight_summary"
    __table_args__ = (
        ForeignKeyConstraint(
            ("batch_id", "trade_date"),
            ("core_serving.wealth_sector_analysis_publish_batch.batch_id", "core_serving.wealth_sector_analysis_publish_batch.trade_date"),
            name="fk_wealth_sector_insight_summary_batch_date",
        ),
        CheckConstraint("industry_level BETWEEN 1 AND 3", name="wealth_sector_insight_summary_level_range"),
        CheckConstraint("sector_count = calculable_count + missing_count", name="wealth_sector_insight_summary_count_consistent"),
        {"schema": "core_serving"},
    )

    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    industry_level: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_count: Mapped[int] = mapped_column(Integer, nullable=False)
    calculable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_count: Mapped[int] = mapped_column(Integer, nullable=False)
    up_count: Mapped[int] = mapped_column(Integer, nullable=False)
    down_count: Mapped[int] = mapped_column(Integer, nullable=False)
    flat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    median_change_pct_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    dual_momentum_count_20d_80: Mapped[int] = mapped_column(Integer, nullable=False)
    leading_improving_count_20d_5d: Mapped[int] = mapped_column(Integer, nullable=False)
    price_volume_joint_count_20d: Mapped[int] = mapped_column(Integer, nullable=False)
    breadth_up_share_above_50_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_history_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_date_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_price_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_amount_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_adj_factor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_group_size_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_coverage_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_previous_batch_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_other_count: Mapped[int] = mapped_column(Integer, nullable=False)
