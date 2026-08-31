from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKeyConstraint, Index, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class WealthSectorDailyInsightItem(Base):
    __tablename__ = "wealth_sector_daily_insight_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ("batch_id", "trade_date"),
            ("core_serving.wealth_sector_analysis_publish_batch.batch_id", "core_serving.wealth_sector_analysis_publish_batch.trade_date"),
            name="fk_wealth_sector_insight_item_batch_date",
        ),
        CheckConstraint(
            "category IN ('HEAD_GAINER', 'HEAD_LOSER', 'STRENGTHENING', 'WEAKENING')",
            name="wealth_sector_insight_item_category_allowed",
        ),
        Index("idx_wealth_sector_insight_item_stable_order", "batch_id", "industry_level", "category", "stable_order", "sector_code"),
        {"schema": "core_serving"},
    )

    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    industry_level: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    stable_order: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    hierarchy_path: Mapped[str] = mapped_column(String(512), nullable=False)
    return_pct_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    return_pct_5d: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    return_pct_20d: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    current_rank_20d: Mapped[int | None] = mapped_column(Integer)
    current_rankable_count_20d: Mapped[int | None] = mapped_column(Integer)
    current_percentile_20d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    previous_rank_20d: Mapped[int | None] = mapped_column(Integer)
    previous_rankable_count_20d: Mapped[int | None] = mapped_column(Integer)
    previous_percentile_20d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    rank_change: Mapped[int | None] = mapped_column(Integer)
    percentile_change_pp: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    price_volume_state_current: Mapped[str | None] = mapped_column(String(32))
    price_volume_state_previous: Mapped[str | None] = mapped_column(String(32))
    dual_qualification_20d_80_current: Mapped[str | None] = mapped_column(String(32))
    dual_qualification_20d_80_previous: Mapped[str | None] = mapped_column(String(32))
    rotation_status_20d_current: Mapped[str | None] = mapped_column(String(32))
    rotation_status_20d_previous: Mapped[str | None] = mapped_column(String(32))
    member_up_pct_current: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    member_up_pct_previous: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    turnover_up_pct_current: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    turnover_up_pct_previous: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    ma20_above_pct_current: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    ma20_above_pct_previous: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    primary_evidence_type: Mapped[str | None] = mapped_column(String(64))
    secondary_evidence_type_1: Mapped[str | None] = mapped_column(String(64))
    secondary_evidence_type_2: Mapped[str | None] = mapped_column(String(64))
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False)
