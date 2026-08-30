from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDataQueryError,
    SectorSelectionInvalidError,
    classify_availability,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    SectorPriceVolumeCoverageFacts,
    SectorPriceVolumeDailyFact,
    SectorPriceVolumeDateAvailabilityFact,
)
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar


_POSITIVE_INFINITY = Decimal("Infinity")
_NEGATIVE_INFINITY = Decimal("-Infinity")


def _valid_price_volume_predicate(model=DcDaily):
    return and_(
        model.close.is_not(None),
        model.close > 0,
        model.close < _POSITIVE_INFINITY,
        model.pct_change.is_not(None),
        model.pct_change > _NEGATIVE_INFINITY,
        model.pct_change < _POSITIVE_INFINITY,
        model.amount.is_not(None),
        model.amount >= 0,
        model.amount < _POSITIVE_INFINITY,
    )


class SectorPriceVolumeQuery:
    """Bounded read-only access to the three approved price-volume sources."""

    @staticmethod
    def load_trade_date_coverage(
        session: Session,
        *,
        hierarchy_codes: tuple[str, ...],
        expected_trade_date: date,
    ) -> SectorPriceVolumeCoverageFacts:
        if not hierarchy_codes:
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
                DcDaily.ts_code.in_(hierarchy_codes),
                DcDaily.trade_date <= expected_trade_date,
                _valid_price_volume_predicate(),
            )
            .group_by(DcDaily.trade_date)
            .cte("price_volume_daily_counts")
            .prefix_with("MATERIALIZED")
        )
        coverage_start = select(func.min(daily_counts.c.trade_date)).scalar_subquery()
        rows = session.execute(
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
                TradeCalendar.trade_date <= expected_trade_date,
            )
            .order_by(TradeCalendar.trade_date)
        ).all()
        if not rows:
            raise SectorDataQueryError("price-volume coverage window is empty")
        expected_count = len(hierarchy_codes)
        dates = tuple(
            SectorPriceVolumeDateAvailabilityFact(
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
        return SectorPriceVolumeCoverageFacts(
            coverage_start_date=dates[0].trade_date,
            coverage_end_date=dates[-1].trade_date,
            trade_dates=dates,
        )

    @staticmethod
    def load_exact_trade_date_status(
        session: Session,
        *,
        hierarchy_codes: tuple[str, ...],
        trade_date: date,
    ) -> SectorPriceVolumeDateAvailabilityFact:
        if not hierarchy_codes:
            raise SectorDataQueryError("sector hierarchy contains no codes")
        calendar_is_open = (
            select(TradeCalendar.is_open)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.trade_date == trade_date,
            )
            .scalar_subquery()
        )
        valid_count = (
            select(func.count())
            .select_from(DcDaily)
            .where(
                DcDaily.category == "行业板块",
                DcDaily.ts_code.in_(hierarchy_codes),
                DcDaily.trade_date == trade_date,
                _valid_price_volume_predicate(),
            )
            .scalar_subquery()
        )
        coverage_start_date = (
            select(func.min(DcDaily.trade_date))
            .where(
                DcDaily.category == "行业板块",
                DcDaily.ts_code.in_(hierarchy_codes),
                DcDaily.trade_date <= trade_date,
                _valid_price_volume_predicate(),
            )
            .scalar_subquery()
        )
        row = session.execute(
            select(
                calendar_is_open.label("calendar_is_open"),
                valid_count.label("valid_sector_count"),
                coverage_start_date.label("coverage_start_date"),
            )
        ).one()
        if row.calendar_is_open is not True:
            raise SectorSelectionInvalidError("tradeDate 必须是 SSE 开市日")
        if row.coverage_start_date is None:
            raise SectorSelectionInvalidError("tradeDate 早于量价数据覆盖范围")
        expected_count = len(hierarchy_codes)
        count = int(row.valid_sector_count)
        return SectorPriceVolumeDateAvailabilityFact(
            trade_date=trade_date,
            availability=classify_availability(
                valid_count=count,
                expected_count=expected_count,
            ),
            expected_sector_count=expected_count,
            valid_sector_count=count,
        )

    @staticmethod
    def load_open_dates(
        session: Session,
        *,
        end_date: date,
        count: int,
    ) -> tuple[date, ...]:
        if count <= 0 or count > 119:
            raise SectorDataQueryError("open-date window must be between 1 and 119")
        rows = session.scalars(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= end_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(count)
        ).all()
        return tuple(reversed(rows))

    @staticmethod
    def load_facts(
        session: Session,
        *,
        sector_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> tuple[SectorPriceVolumeDailyFact, ...]:
        if not sector_codes:
            return ()
        rows = session.execute(
            select(
                DcDaily.ts_code,
                DcDaily.trade_date,
                DcDaily.close,
                DcDaily.pct_change,
                DcDaily.amount,
            )
            .where(
                DcDaily.category == "行业板块",
                DcDaily.ts_code.in_(sector_codes),
                DcDaily.trade_date.between(start_date, end_date),
            )
            .order_by(DcDaily.trade_date, DcDaily.ts_code)
        ).all()
        facts = tuple(
            SectorPriceVolumeDailyFact(
                sector_code=row.ts_code,
                trade_date=row.trade_date,
                close=row.close,
                pct_change=row.pct_change,
                amount=row.amount,
            )
            for row in rows
        )
        keys = tuple((item.sector_code, item.trade_date) for item in facts)
        if len(keys) != len(set(keys)):
            raise SectorDataQueryError("price-volume facts contain duplicate business keys")
        return facts
