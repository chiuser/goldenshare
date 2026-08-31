from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from src.foundation.models.core_serving.wealth_sector_momentum_daily import COMPARISON_IDENTITY_CHECK_SQL


class WealthSectorDualMomentumDaily(Base):
    __tablename__ = "wealth_sector_dual_momentum_daily"
    __table_args__ = (
        ForeignKeyConstraint(
            ("batch_id", "trade_date"),
            ("core_serving.wealth_sector_analysis_publish_batch.batch_id", "core_serving.wealth_sector_analysis_publish_batch.trade_date"),
            name="fk_wealth_sector_dual_momentum_batch_date",
        ),
        CheckConstraint("period IN (5, 10, 20, 30)", name="wealth_sector_dual_period_allowed"),
        CheckConstraint("minimum_group_size = 3", name="wealth_sector_dual_min_group_fixed"),
        CheckConstraint("percentile IS NULL OR percentile BETWEEN 0 AND 100", name="wealth_sector_dual_percentile_range"),
        CheckConstraint(COMPARISON_IDENTITY_CHECK_SQL, name="wealth_sector_dual_comparison_identity"),
        Index(
            "idx_wealth_sector_dual_trade_scope_period_q80",
            "trade_date", "comparison_scope", "comparison_key", "period", "qualification_status_80", "sector_code",
        ),
        {"schema": "core_serving"},
    )

    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    comparison_scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    comparison_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_sector_code: Mapped[str | None] = mapped_column(String(16))
    sector_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    industry_level: Mapped[int] = mapped_column(Integer, nullable=False)
    hierarchy_path: Mapped[str] = mapped_column(String(512), nullable=False)
    period: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    strength_rank: Mapped[int | None] = mapped_column(Integer)
    rankable_count: Mapped[int | None] = mapped_column(Integer)
    percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    absolute_status: Mapped[str] = mapped_column(String(32), nullable=False)
    coordinate_status: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_status_70: Mapped[str] = mapped_column(String(32), nullable=False)
    qualification_status_70: Mapped[str] = mapped_column(String(32), nullable=False)
    display_status_70: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_status_80: Mapped[str] = mapped_column(String(32), nullable=False)
    qualification_status_80: Mapped[str] = mapped_column(String(32), nullable=False)
    display_status_80: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_status_90: Mapped[str] = mapped_column(String(32), nullable=False)
    qualification_status_90: Mapped[str] = mapped_column(String(32), nullable=False)
    display_status_90: Mapped[str] = mapped_column(String(32), nullable=False)
    minimum_group_size: Mapped[int] = mapped_column(Integer, nullable=False)
    formula_key: Mapped[str] = mapped_column(String(64), nullable=False)
    formula_version: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    missing_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
