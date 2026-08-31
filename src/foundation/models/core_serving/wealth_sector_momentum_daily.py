from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


COMPARISON_IDENTITY_CHECK_SQL = """
(
  (comparison_scope='LEVEL_1' AND comparison_key='GLOBAL:L1' AND parent_sector_code IS NULL AND industry_level=1)
  OR (comparison_scope='LEVEL_2' AND comparison_key='GLOBAL:L2' AND parent_sector_code IS NULL AND industry_level=2)
  OR (comparison_scope='LEVEL_3' AND comparison_key='GLOBAL:L3' AND parent_sector_code IS NULL AND industry_level=3)
  OR (comparison_scope='LEVEL_1_CHILDREN' AND comparison_key='PARENT:L1:' || parent_sector_code AND parent_sector_code IS NOT NULL AND industry_level=2)
  OR (comparison_scope='LEVEL_2_CHILDREN' AND comparison_key='PARENT:L2:' || parent_sector_code AND parent_sector_code IS NOT NULL AND industry_level=3)
)
"""


class WealthSectorMomentumDaily(Base):
    __tablename__ = "wealth_sector_momentum_daily"
    __table_args__ = (
        ForeignKeyConstraint(
            ("batch_id", "trade_date"),
            ("core_serving.wealth_sector_analysis_publish_batch.batch_id", "core_serving.wealth_sector_analysis_publish_batch.trade_date"),
            name="fk_wealth_sector_momentum_batch_date",
        ),
        CheckConstraint("period IN (1, 5, 10, 20, 30)", name="wealth_sector_momentum_period_allowed"),
        CheckConstraint("industry_level BETWEEN 1 AND 3", name="wealth_sector_momentum_level_range"),
        CheckConstraint("calculation_status IN ('CALCULABLE', 'UNAVAILABLE')", name="wealth_sector_momentum_status_allowed"),
        CheckConstraint("percentile IS NULL OR percentile BETWEEN 0 AND 100", name="wealth_sector_momentum_percentile_range"),
        CheckConstraint(COMPARISON_IDENTITY_CHECK_SQL, name="wealth_sector_momentum_comparison_identity"),
        CheckConstraint(
            "(strength_rank IS NULL AND rankable_count IS NULL) OR "
            "(strength_rank BETWEEN 1 AND rankable_count)",
            name="wealth_sector_momentum_rank_consistent",
        ),
        Index(
            "idx_wealth_sector_momentum_trade_scope_period_rank",
            "trade_date", "comparison_scope", "comparison_key", "period", "strength_rank", "sector_code",
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
    formula_key: Mapped[str] = mapped_column(String(64), nullable=False)
    formula_version: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    missing_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
