from __future__ import annotations

from datetime import date

from sqlalchemy import and_, case, func, literal, select
from sqlalchemy.orm import Session, aliased

from src.biz.queries.wealth.market.sector_analysis.sector_analysis_meta_query import (
    _valid_fact_predicate,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDailyFact,
    SectorDataQueryError,
    SectorDateAvailabilityFact,
    SectorScopeInvalidError,
    SectorTradingDateResolution,
    classify_availability,
)
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar


class SectorMomentumQuery:
    """Bounded read-only access to calendar and industry daily facts."""

    def resolve_trading_date(
        self,
        session: Session,
        *,
        expected_trade_date: date,
        coverage_end_date: date,
        sector_codes: tuple[str, ...],
        is_explicit: bool,
    ) -> SectorTradingDateResolution:
        if not sector_codes:
            raise SectorDataQueryError("sector hierarchy contains no codes")
        expected_count = len(sector_codes)
        coverage_start = (
            select(DcDaily.trade_date)
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
                _valid_fact_predicate(),
            )
            .order_by(DcDaily.trade_date)
            .limit(1)
            .scalar_subquery()
        )
        expected_is_open = (
            select(func.count())
            .select_from(TradeCalendar)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date == expected_trade_date,
            )
            .scalar_subquery()
        )
        expected_valid_count = (
            select(func.count())
            .select_from(DcDaily)
            .where(
                DcDaily.category == "行业板块",
                DcDaily.ts_code.in_(sector_codes),
                DcDaily.trade_date == expected_trade_date,
                _valid_fact_predicate(),
            )
            .scalar_subquery()
        )
        expected_facts = select(
            coverage_start.label("coverage_start_date"),
            expected_is_open.label("expected_is_open"),
            expected_valid_count.label("expected_valid_count"),
        ).cte("expected_sector_facts")
        candidate_calendar = aliased(TradeCalendar)
        candidate_daily = aliased(DcDaily)
        candidate_valid_count = (
            select(func.count())
            .select_from(candidate_daily)
            .where(
                candidate_daily.category == "行业板块",
                candidate_daily.ts_code.in_(sector_codes),
                candidate_daily.trade_date == candidate_calendar.trade_date,
                _valid_fact_predicate(candidate_daily),
            )
            .correlate(candidate_calendar)
            .scalar_subquery()
        )
        latest_complete_date = (
            select(candidate_calendar.trade_date)
            .where(
                candidate_calendar.exchange == "SSE",
                candidate_calendar.is_open.is_(True),
                candidate_calendar.trade_date >= expected_facts.c.coverage_start_date,
                candidate_calendar.trade_date <= expected_trade_date,
                candidate_valid_count == expected_count,
            )
            .order_by(candidate_calendar.trade_date.desc())
            .limit(1)
            .scalar_subquery()
        )
        row = session.execute(
            select(
                expected_facts.c.coverage_start_date,
                expected_facts.c.expected_is_open,
                expected_facts.c.expected_valid_count,
                case(
                    (
                        literal(is_explicit).is_(True)
                        | (expected_facts.c.expected_valid_count == expected_count),
                        literal(None),
                    ),
                    else_=latest_complete_date,
                ).label("latest_complete_date"),
            ).select_from(expected_facts)
        ).one()
        if row.coverage_start_date is None:
            raise SectorDataQueryError("sector coverage window is empty")
        if expected_trade_date < row.coverage_start_date or expected_trade_date > coverage_end_date:
            raise SectorScopeInvalidError("tradeDate 超出可用交易日范围")
        if int(row.expected_is_open) != 1:
            raise SectorScopeInvalidError("tradeDate 必须是 SSE 开市日")

        expected = SectorDateAvailabilityFact(
            trade_date=expected_trade_date,
            availability=classify_availability(
                valid_count=int(row.expected_valid_count),
                expected_count=expected_count,
            ),
            expected_sector_count=expected_count,
            valid_sector_count=int(row.expected_valid_count),
        )
        if is_explicit or expected.availability == "COMPLETE":
            observed = expected
        elif row.latest_complete_date is None:
            observed = None
        else:
            observed = SectorDateAvailabilityFact(
                trade_date=row.latest_complete_date,
                availability="COMPLETE",
                expected_sector_count=expected_count,
                valid_sector_count=expected_count,
            )
        return SectorTradingDateResolution(
            coverage_start_date=row.coverage_start_date,
            coverage_end_date=coverage_end_date,
            expected=expected,
            observed=observed,
            is_explicit=is_explicit,
        )

    @staticmethod
    def load_open_dates(
        session: Session,
        *,
        end_date: date,
        count: int,
    ) -> tuple[date, ...]:
        if count <= 0 or count > 95:
            raise SectorDataQueryError("open-date window must be between 1 and 95")
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
    ) -> tuple[SectorDailyFact, ...]:
        if not sector_codes:
            return ()
        rows = session.execute(
            select(
                DcDaily.ts_code,
                DcDaily.trade_date,
                DcDaily.close,
                DcDaily.pct_change,
            )
            .where(
                DcDaily.category == "行业板块",
                DcDaily.ts_code.in_(sector_codes),
                DcDaily.trade_date.between(start_date, end_date),
            )
            .order_by(DcDaily.trade_date, DcDaily.ts_code)
        ).all()
        return tuple(
            SectorDailyFact(
                sector_code=row.ts_code,
                trade_date=row.trade_date,
                close=row.close,
                pct_change=row.pct_change,
            )
            for row in rows
        )
