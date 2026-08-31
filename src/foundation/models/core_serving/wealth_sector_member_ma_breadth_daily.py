from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from src.foundation.models.core_serving.wealth_sector_member_breadth_daily import REASON_ARRAY
from src.foundation.models.core_serving.wealth_sector_momentum_daily import COMPARISON_IDENTITY_CHECK_SQL


class WealthSectorMemberMaBreadthDaily(Base):
    __tablename__ = "wealth_sector_member_ma_breadth_daily"
    __table_args__ = (
        ForeignKeyConstraint(
            ("batch_id", "trade_date"),
            ("core_serving.wealth_sector_analysis_publish_batch.batch_id", "core_serving.wealth_sector_analysis_publish_batch.trade_date"),
            name="fk_wealth_sector_member_ma_batch_date",
        ),
        CheckConstraint("ma_period IN (5, 10, 15, 20, 30, 60)", name="wealth_sector_member_ma_period_allowed"),
        CheckConstraint("coverage_pct BETWEEN 0 AND 100", name="wealth_sector_member_ma_coverage_range"),
        CheckConstraint(COMPARISON_IDENTITY_CHECK_SQL, name="wealth_sector_member_ma_comparison_identity"),
        Index("idx_wealth_sector_member_ma_up_rank", "trade_date", "comparison_scope", "comparison_key", "ma_period", "up_rank", "sector_code"),
        Index("idx_wealth_sector_member_ma_down_rank", "trade_date", "comparison_scope", "comparison_key", "ma_period", "down_rank", "sector_code"),
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
    ma_period: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    calculable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    qualification: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(REASON_ARRAY, nullable=False)
    above_count: Mapped[int] = mapped_column(Integer, nullable=False)
    equal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    below_count: Mapped[int] = mapped_column(Integer, nullable=False)
    above_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    equal_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    below_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    up_rank: Mapped[int | None] = mapped_column(Integer)
    up_rankable_count: Mapped[int | None] = mapped_column(Integer)
    up_percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    down_rank: Mapped[int | None] = mapped_column(Integer)
    down_rankable_count: Mapped[int | None] = mapped_column(Integer)
    down_percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    formula_key: Mapped[str] = mapped_column(String(64), nullable=False)
    formula_version: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    missing_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
