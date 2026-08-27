from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDataQueryError,
    SectorDateAvailabilityFact,
    classify_availability,
)
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar


class SectorAnalysisMetaQuery:
    """Load the complete open-date coverage series in one bounded statement."""

    def load_coverage(
        self,
        session: Session,
        *,
        coverage_end_date: date,
        sector_codes: tuple[str, ...],
    ) -> tuple[date, tuple[SectorDateAvailabilityFact, ...]]:
        if not sector_codes:
            raise SectorDataQueryError("sector hierarchy contains no codes")
        daily_counts = (
            select(
                DcDaily.trade_date.label("trade_date"),
                func.count().label("valid_sector_count"),
            )
            .join(
                TradeCalendar,
                and_(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date == DcDaily.trade_date,
                ),
            )
            .where(
                DcDaily.category == "行业板块",
                DcDaily.ts_code.in_(sector_codes),
                DcDaily.trade_date <= coverage_end_date,
                _valid_fact_predicate(),
            )
            .group_by(DcDaily.trade_date)
            .cte("sector_daily_counts")
            .prefix_with("MATERIALIZED")
        )
        coverage_start = select(func.min(daily_counts.c.trade_date)).scalar_subquery()
        statement = (
            select(
                TradeCalendar.trade_date,
                func.coalesce(daily_counts.c.valid_sector_count, 0).label(
                    "valid_sector_count"
                ),
            )
            .select_from(TradeCalendar)
            .outerjoin(
                daily_counts,
                daily_counts.c.trade_date == TradeCalendar.trade_date,
            )
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date >= coverage_start,
                TradeCalendar.trade_date <= coverage_end_date,
            )
            .order_by(TradeCalendar.trade_date)
        )
        rows = session.execute(statement).all()
        if not rows:
            raise SectorDataQueryError("sector coverage window is empty")
        expected_count = len(sector_codes)
        coverage = tuple(
            SectorDateAvailabilityFact(
                trade_date=row.trade_date,
                availability=classify_availability(
                    valid_count=int(row.valid_sector_count),
                    expected_count=expected_count,
                ),
                expected_sector_count=expected_count,
                valid_sector_count=int(row.valid_sector_count),
            )
            for row in rows
        )
        return coverage[0].trade_date, coverage


_POSITIVE_INFINITY = Decimal("Infinity")
_NEGATIVE_INFINITY = Decimal("-Infinity")


def _valid_fact_predicate(model=DcDaily):
    return and_(
        model.close.is_not(None),
        model.close > 0,
        model.close < _POSITIVE_INFINITY,
        model.pct_change.is_not(None),
        model.pct_change > _NEGATIVE_INFINITY,
        model.pct_change < _POSITIVE_INFINITY,
    )
