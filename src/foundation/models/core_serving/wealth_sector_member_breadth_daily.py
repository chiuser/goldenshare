from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, Integer, JSON, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from src.foundation.models.core_serving.wealth_sector_momentum_daily import COMPARISON_IDENTITY_CHECK_SQL


REASON_ARRAY = JSON().with_variant(ARRAY(String(64)), "postgresql")


class WealthSectorMemberBreadthDaily(Base):
    __tablename__ = "wealth_sector_member_breadth_daily"
    __table_args__ = (
        ForeignKeyConstraint(
            ("batch_id", "trade_date"),
            ("core_serving.wealth_sector_analysis_publish_batch.batch_id", "core_serving.wealth_sector_analysis_publish_batch.trade_date"),
            name="fk_wealth_sector_member_breadth_batch_date",
        ),
        CheckConstraint(
            "member_coverage_pct BETWEEN 0 AND 100 AND turnover_coverage_pct BETWEEN 0 AND 100",
            name="wealth_sector_member_breadth_coverage_range",
        ),
        CheckConstraint(COMPARISON_IDENTITY_CHECK_SQL, name="wealth_sector_member_breadth_comparison_identity"),
        Index("idx_wealth_sector_member_up_rank", "trade_date", "comparison_scope", "comparison_key", "member_up_rank", "sector_code"),
        Index("idx_wealth_sector_member_down_rank", "trade_date", "comparison_scope", "comparison_key", "member_down_rank", "sector_code"),
        Index("idx_wealth_sector_turnover_up_rank", "trade_date", "comparison_scope", "comparison_key", "turnover_up_rank", "sector_code"),
        Index("idx_wealth_sector_turnover_down_rank", "trade_date", "comparison_scope", "comparison_key", "turnover_down_rank", "sector_code"),
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
    source_member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    member_calculable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    member_coverage_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    member_qualification: Mapped[str] = mapped_column(String(16), nullable=False)
    member_reason_codes: Mapped[list[str]] = mapped_column(REASON_ARRAY, nullable=False)
    member_up_count: Mapped[int] = mapped_column(Integer, nullable=False)
    member_flat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    member_down_count: Mapped[int] = mapped_column(Integer, nullable=False)
    member_up_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    member_flat_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    member_down_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    member_up_rank: Mapped[int | None] = mapped_column(Integer)
    member_up_rankable_count: Mapped[int | None] = mapped_column(Integer)
    member_up_percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    member_down_rank: Mapped[int | None] = mapped_column(Integer)
    member_down_rankable_count: Mapped[int | None] = mapped_column(Integer)
    member_down_percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    turnover_calculable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    turnover_coverage_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    turnover_qualification: Mapped[str] = mapped_column(String(16), nullable=False)
    turnover_reason_codes: Mapped[list[str]] = mapped_column(REASON_ARRAY, nullable=False)
    turnover_up_count: Mapped[int] = mapped_column(Integer, nullable=False)
    turnover_flat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    turnover_down_count: Mapped[int] = mapped_column(Integer, nullable=False)
    turnover_up_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    turnover_flat_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    turnover_down_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    turnover_up_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    turnover_flat_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    turnover_down_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    turnover_up_rank: Mapped[int | None] = mapped_column(Integer)
    turnover_up_rankable_count: Mapped[int | None] = mapped_column(Integer)
    turnover_up_percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    turnover_down_rank: Mapped[int | None] = mapped_column(Integer)
    turnover_down_rankable_count: Mapped[int | None] = mapped_column(Integer)
    turnover_down_percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    formula_key: Mapped[str] = mapped_column(String(64), nullable=False)
    formula_version: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    missing_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
