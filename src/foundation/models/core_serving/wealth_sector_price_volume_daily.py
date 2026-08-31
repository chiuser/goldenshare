from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from src.foundation.models.core_serving.wealth_sector_momentum_daily import COMPARISON_IDENTITY_CHECK_SQL


class WealthSectorPriceVolumeDaily(Base):
    __tablename__ = "wealth_sector_price_volume_daily"
    __table_args__ = (
        ForeignKeyConstraint(
            ("batch_id", "trade_date"),
            ("core_serving.wealth_sector_analysis_publish_batch.batch_id", "core_serving.wealth_sector_analysis_publish_batch.trade_date"),
            name="fk_wealth_sector_price_volume_batch_date",
        ),
        CheckConstraint("period IN (1, 5, 10, 20, 30)", name="wealth_sector_price_volume_period_allowed"),
        CheckConstraint(COMPARISON_IDENTITY_CHECK_SQL, name="wealth_sector_price_volume_comparison_identity"),
        Index("idx_wealth_sector_price_volume_price_rank", "trade_date", "comparison_scope", "comparison_key", "period", "price_rank", "sector_code"),
        Index("idx_wealth_sector_price_volume_amount_rank", "trade_date", "comparison_scope", "comparison_key", "period", "amount_rank", "sector_code"),
        Index("idx_wealth_sector_price_volume_state", "trade_date", "comparison_scope", "comparison_key", "period", "distribution_state", "sector_code"),
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
    price_momentum_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    price_missing_reason: Mapped[str | None] = mapped_column(String(64))
    price_rank: Mapped[int | None] = mapped_column(Integer)
    price_rankable_count: Mapped[int | None] = mapped_column(Integer)
    price_percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    amount_activity_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    amount_missing_reason: Mapped[str | None] = mapped_column(String(64))
    amount_rank: Mapped[int | None] = mapped_column(Integer)
    amount_rankable_count: Mapped[int | None] = mapped_column(Integer)
    amount_percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    distribution_state: Mapped[str | None] = mapped_column(String(32))
    formula_key: Mapped[str] = mapped_column(String(64), nullable=False)
    formula_version: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    missing_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
