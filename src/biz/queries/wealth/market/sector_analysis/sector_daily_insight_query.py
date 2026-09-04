from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.daily_facts.replay_planner import (
    MIN_PUBLISH_DATE,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import (
    WealthSectorAnalysisPublishBatch as Batch,
)
from src.foundation.models.core_serving.wealth_sector_daily_insight_item import (
    WealthSectorDailyInsightItem as Item,
)
from src.foundation.models.core_serving.wealth_sector_daily_insight_summary import (
    WealthSectorDailyInsightSummary as Summary,
)


# Explicit projections: never expose batch hashes, source payloads or ORM models.
BATCH_FIELDS = (
    "batch_id",
    "trade_date",
    "previous_trade_date",
    "hierarchy_version",
    "formula_bundle_version",
    "template_version",
    "published_at",
    "calculated_at",
)
SUMMARY_FIELDS = (
    "sector_count",
    "calculable_count",
    "missing_count",
    "up_count",
    "down_count",
    "flat_count",
    "median_change_pct_1d",
    "dual_momentum_count_20d_80",
    "leading_improving_count_20d_5d",
    "price_volume_joint_count_20d",
    "breadth_up_share_above_50_count",
    "missing_history_count",
    "missing_date_count",
    "missing_price_count",
    "missing_member_count",
    "missing_amount_count",
    "missing_adj_factor_count",
    "missing_group_size_count",
    "missing_coverage_count",
    "missing_previous_batch_count",
    "missing_other_count",
)
ITEM_FIELDS = (
    "sector_code",
    "sector_name",
    "hierarchy_path",
    "industry_level",
    "event_type",
    "return_pct_1d",
    "return_pct_5d",
    "return_pct_20d",
    "current_rank_20d",
    "current_rankable_count_20d",
    "current_percentile_20d",
    "previous_rank_20d",
    "previous_rankable_count_20d",
    "previous_percentile_20d",
    "rank_change",
    "percentile_change_pp",
    "price_volume_state_current",
    "price_volume_state_previous",
    "dual_qualification_20d_80_current",
    "dual_qualification_20d_80_previous",
    "rotation_status_20d_current",
    "rotation_status_20d_previous",
    "member_up_pct_current",
    "member_up_pct_previous",
    "turnover_up_pct_current",
    "turnover_up_pct_previous",
    "ma20_above_pct_current",
    "ma20_above_pct_previous",
    "primary_evidence_type",
    "template_key",
    "template_version",
    "rendered_text",
)


class SectorDailyInsightBatchMismatchError(ValueError):
    pass


class SectorDailyInsightQuery:
    """Only calendar and immutable published insight facts; no method calculation."""

    def load_coverage(self, session: Session, *, end_date: date):
        calendar = (
            select(TradeCalendar.trade_date, TradeCalendar.pretrade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date >= MIN_PUBLISH_DATE,
                TradeCalendar.trade_date <= end_date,
            )
            .cte("insight_calendar")
        )
        return (
            session.execute(
                select(
                    calendar.c.trade_date,
                    calendar.c.pretrade_date,
                    *(
                        getattr(Batch, field)
                        for field in BATCH_FIELDS
                        if field != "trade_date"
                    ),
                )
                .select_from(calendar)
                .outerjoin(
                    Batch,
                    and_(
                        Batch.trade_date == calendar.c.trade_date,
                        Batch.status == "PUBLISHED",
                    ),
                )
                .order_by(calendar.c.trade_date)
            )
            .mappings()
            .all()
        )

    def load_batch(self, session: Session, *, trade_date: date):
        return (
            session.execute(
                select(*(getattr(Batch, field) for field in BATCH_FIELDS)).where(
                    Batch.trade_date == trade_date,
                    Batch.status == "PUBLISHED",
                )
            )
            .mappings()
            .one_or_none()
        )

    def load_summary(
        self, session: Session, *, batch_id: UUID, trade_date: date, level: int
    ):
        row = (
            session.execute(
                select(
                    Summary.batch_id.label("summary_batch_id"),
                    *(getattr(Summary, field) for field in SUMMARY_FIELDS),
                )
                .select_from(Batch)
                .outerjoin(
                    Summary,
                    and_(
                        Summary.batch_id == Batch.batch_id,
                        Summary.trade_date == Batch.trade_date,
                        Summary.industry_level == level,
                    ),
                )
                .where(
                    Batch.batch_id == batch_id,
                    Batch.trade_date == trade_date,
                    Batch.status == "PUBLISHED",
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise SectorDailyInsightBatchMismatchError(
                "published batch changed while reading summary"
            )
        if row["summary_batch_id"] is None:
            raise ValueError("published insight summary is missing")
        return row

    def load_items(
        self, session: Session, *, batch_id: UUID, trade_date: date, level: int
    ):
        rows = (
            session.execute(
                select(
                    Item.category,
                    Item.stable_order,
                    *(getattr(Item, field) for field in ITEM_FIELDS),
                    Item.secondary_evidence_type_1,
                    Item.secondary_evidence_type_2,
                )
                .select_from(Batch)
                .outerjoin(
                    Item,
                    and_(
                        Item.batch_id == Batch.batch_id,
                        Item.trade_date == Batch.trade_date,
                        Item.industry_level == level,
                    ),
                )
                .where(
                    Batch.batch_id == batch_id,
                    Batch.trade_date == trade_date,
                    Batch.status == "PUBLISHED",
                )
                .order_by(Item.category, Item.stable_order, Item.sector_code)
            )
            .mappings()
            .all()
        )
        if not rows:
            raise SectorDailyInsightBatchMismatchError(
                "published batch changed while reading items"
            )
        return [row for row in rows if row["sector_code"] is not None]
