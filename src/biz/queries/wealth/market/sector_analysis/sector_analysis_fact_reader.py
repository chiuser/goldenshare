from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchySnapshot,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    FORMULA_BUNDLE_VERSION,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    FORMULA_KEY,
    FORMULA_VERSION,
    SectorDataQueryError,
    SectorDateAvailabilityFact,
    SectorMomentumPeriod,
    SectorMomentumScope,
    SectorScopeInvalidError,
    SectorTradingDateResolution,
    classify_availability,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import (
    WealthSectorAnalysisPublishBatch,
)
from src.foundation.models.core_serving.wealth_sector_momentum_daily import (
    WealthSectorMomentumDaily,
)


@dataclass(frozen=True, slots=True)
class SectorPublishedCalendarDate:
    availability: SectorDateAvailabilityFact
    batch_id: UUID | None


@dataclass(frozen=True, slots=True)
class SectorPublishedCoverage:
    coverage_start_date: date
    coverage_end_date: date
    calendar_dates: tuple[SectorPublishedCalendarDate, ...]

    @property
    def published_dates(self) -> tuple[SectorDateAvailabilityFact, ...]:
        return tuple(
            item.availability for item in self.calendar_dates if item.batch_id is not None
        )

    @property
    def batch_by_date(self) -> dict[date, UUID]:
        return {
            item.availability.trade_date: item.batch_id
            for item in self.calendar_dates
            if item.batch_id is not None
        }


@dataclass(frozen=True, slots=True)
class SectorPublishedMomentumRow:
    batch_id: UUID
    trade_date: date
    comparison_scope: str
    comparison_key: str
    parent_sector_code: str | None
    sector_code: str
    sector_name: str
    industry_level: int
    hierarchy_path: str
    period: int
    return_pct: Decimal | None
    strength_rank: int | None
    rankable_count: int | None
    percentile: Decimal | None
    calculation_status: str
    missing_reason: str


@dataclass(frozen=True, slots=True)
class SectorMomentumFactSelection:
    trade_dates: tuple[date, ...]
    comparison_scope: SectorMomentumScope
    comparison_key: str


class SectorAnalysisFactReader:
    """Read immutable sector-analysis facts through their PUBLISHED batch identity."""

    def load_momentum_coverage(
        self,
        session: Session,
        *,
        coverage_end_date: date,
        hierarchy: SectorHierarchySnapshot,
    ) -> SectorPublishedCoverage:
        summary = (
            select(
                WealthSectorMomentumDaily.batch_id.label("batch_id"),
                func.count(WealthSectorMomentumDaily.sector_code).label("row_count"),
                func.sum(
                    case(
                        (WealthSectorMomentumDaily.calculation_status == "CALCULABLE", 1),
                        else_=0,
                    )
                ).label("valid_count"),
                func.min(WealthSectorMomentumDaily.formula_key).label("min_formula_key"),
                func.max(WealthSectorMomentumDaily.formula_key).label("max_formula_key"),
                func.min(WealthSectorMomentumDaily.formula_version).label(
                    "min_formula_version"
                ),
                func.max(WealthSectorMomentumDaily.formula_version).label(
                    "max_formula_version"
                ),
            )
            .where(
                WealthSectorMomentumDaily.period == 1,
                WealthSectorMomentumDaily.comparison_scope.in_(
                    ("LEVEL_1", "LEVEL_2", "LEVEL_3")
                ),
            )
            .group_by(WealthSectorMomentumDaily.batch_id)
            .subquery()
        )
        first_published_date = (
            select(func.min(WealthSectorAnalysisPublishBatch.trade_date))
            .where(WealthSectorAnalysisPublishBatch.status == "PUBLISHED")
            .scalar_subquery()
        )
        rows = session.execute(
            select(
                TradeCalendar.trade_date,
                WealthSectorAnalysisPublishBatch.batch_id,
                WealthSectorAnalysisPublishBatch.hierarchy_version,
                WealthSectorAnalysisPublishBatch.formula_bundle_version,
                summary.c.row_count,
                summary.c.valid_count,
                summary.c.min_formula_key,
                summary.c.max_formula_key,
                summary.c.min_formula_version,
                summary.c.max_formula_version,
            )
            .outerjoin(
                WealthSectorAnalysisPublishBatch,
                and_(
                    WealthSectorAnalysisPublishBatch.trade_date
                    == TradeCalendar.trade_date,
                    WealthSectorAnalysisPublishBatch.status == "PUBLISHED",
                ),
            )
            .outerjoin(
                summary,
                summary.c.batch_id == WealthSectorAnalysisPublishBatch.batch_id,
            )
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date >= first_published_date,
                TradeCalendar.trade_date <= coverage_end_date,
            )
            .order_by(TradeCalendar.trade_date)
        ).all()
        if not rows:
            raise SectorDataQueryError("published sector-analysis coverage is empty")

        expected_count = len(hierarchy.nodes)
        calendar_dates: list[SectorPublishedCalendarDate] = []
        for row in rows:
            if row.batch_id is None:
                valid_count = 0
            else:
                self._validate_batch_identity(
                    hierarchy_version=row.hierarchy_version,
                    formula_bundle_version=row.formula_bundle_version,
                    hierarchy=hierarchy,
                )
                if int(row.row_count or 0) != expected_count:
                    raise SectorDataQueryError(
                        "published momentum coverage does not match the hierarchy"
                    )
                if (
                    row.min_formula_key != FORMULA_KEY
                    or row.max_formula_key != FORMULA_KEY
                    or int(row.min_formula_version or 0) != FORMULA_VERSION
                    or int(row.max_formula_version or 0) != FORMULA_VERSION
                ):
                    raise SectorDataQueryError(
                        "published momentum formula identity is inconsistent"
                    )
                valid_count = int(row.valid_count or 0)
            calendar_dates.append(
                SectorPublishedCalendarDate(
                    availability=SectorDateAvailabilityFact(
                        trade_date=row.trade_date,
                        availability=classify_availability(
                            valid_count=valid_count,
                            expected_count=expected_count,
                        ),
                        expected_sector_count=expected_count,
                        valid_sector_count=valid_count,
                    ),
                    batch_id=row.batch_id,
                )
            )
        published = tuple(item for item in calendar_dates if item.batch_id is not None)
        if not published:
            raise SectorDataQueryError("published sector-analysis coverage is empty")
        return SectorPublishedCoverage(
            coverage_start_date=published[0].availability.trade_date,
            coverage_end_date=coverage_end_date,
            calendar_dates=tuple(calendar_dates),
        )

    @staticmethod
    def resolve_trading_date(
        coverage: SectorPublishedCoverage,
        *,
        expected_trade_date: date,
        is_explicit: bool,
    ) -> SectorTradingDateResolution:
        if (
            expected_trade_date < coverage.coverage_start_date
            or expected_trade_date > coverage.coverage_end_date
        ):
            raise SectorScopeInvalidError("tradeDate 超出可用交易日范围")
        by_date = {
            item.availability.trade_date: item for item in coverage.calendar_dates
        }
        expected_item = by_date.get(expected_trade_date)
        if expected_item is None:
            raise SectorScopeInvalidError("tradeDate 必须是 SSE 开市日")
        expected = expected_item.availability
        if is_explicit or expected_item.batch_id is not None:
            observed = expected
        else:
            observed_item = next(
                (
                    item
                    for item in reversed(coverage.calendar_dates)
                    if item.availability.trade_date < expected_trade_date
                    and item.batch_id is not None
                ),
                None,
            )
            observed = observed_item.availability if observed_item is not None else None
        return SectorTradingDateResolution(
            coverage_start_date=coverage.coverage_start_date,
            coverage_end_date=coverage.coverage_end_date,
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
        if count <= 0 or count > 60:
            raise SectorDataQueryError("published history window must be between 1 and 60")
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

    def load_momentum_rows(
        self,
        session: Session,
        *,
        selections: tuple[SectorMomentumFactSelection, ...],
        period: SectorMomentumPeriod,
        hierarchy: SectorHierarchySnapshot,
        sector_codes: tuple[str, ...] | None = None,
    ) -> tuple[SectorPublishedMomentumRow, ...]:
        selections = tuple(item for item in selections if item.trade_dates)
        if not selections:
            return ()
        selection_predicate = or_(
            *(
                and_(
                    WealthSectorAnalysisPublishBatch.trade_date.in_(item.trade_dates),
                    WealthSectorMomentumDaily.comparison_scope
                    == item.comparison_scope,
                    WealthSectorMomentumDaily.comparison_key == item.comparison_key,
                )
                for item in selections
            )
        )
        statement = (
            select(
                WealthSectorAnalysisPublishBatch.batch_id,
                WealthSectorAnalysisPublishBatch.trade_date,
                WealthSectorAnalysisPublishBatch.hierarchy_version,
                WealthSectorAnalysisPublishBatch.formula_bundle_version,
                WealthSectorMomentumDaily.comparison_scope,
                WealthSectorMomentumDaily.comparison_key,
                WealthSectorMomentumDaily.parent_sector_code,
                WealthSectorMomentumDaily.sector_code,
                WealthSectorMomentumDaily.sector_name,
                WealthSectorMomentumDaily.industry_level,
                WealthSectorMomentumDaily.hierarchy_path,
                WealthSectorMomentumDaily.period,
                WealthSectorMomentumDaily.return_pct,
                WealthSectorMomentumDaily.strength_rank,
                WealthSectorMomentumDaily.rankable_count,
                WealthSectorMomentumDaily.percentile,
                WealthSectorMomentumDaily.formula_key,
                WealthSectorMomentumDaily.formula_version,
                WealthSectorMomentumDaily.calculation_status,
                WealthSectorMomentumDaily.missing_reason,
            )
            .join(
                WealthSectorAnalysisPublishBatch,
                and_(
                    WealthSectorAnalysisPublishBatch.batch_id
                    == WealthSectorMomentumDaily.batch_id,
                    WealthSectorAnalysisPublishBatch.trade_date
                    == WealthSectorMomentumDaily.trade_date,
                    WealthSectorAnalysisPublishBatch.status == "PUBLISHED",
                ),
            )
            .where(
                selection_predicate,
                WealthSectorMomentumDaily.period == period,
            )
        )
        if sector_codes is not None:
            statement = statement.where(
                WealthSectorMomentumDaily.sector_code.in_(sector_codes)
            )
        rows = session.execute(
            statement.order_by(
                WealthSectorAnalysisPublishBatch.trade_date,
                WealthSectorMomentumDaily.comparison_key,
                WealthSectorMomentumDaily.sector_code,
            )
        ).all()
        results: list[SectorPublishedMomentumRow] = []
        for row in rows:
            self._validate_batch_identity(
                hierarchy_version=row.hierarchy_version,
                formula_bundle_version=row.formula_bundle_version,
                hierarchy=hierarchy,
            )
            node = hierarchy.nodes_by_code.get(row.sector_code)
            if (
                node is None
                or node.sector_name != row.sector_name
                or node.industry_level != int(row.industry_level)
                or node.hierarchy_path != row.hierarchy_path
            ):
                raise SectorDataQueryError(
                    "published momentum row does not match the hierarchy"
                )
            if row.formula_key != FORMULA_KEY or int(row.formula_version) != FORMULA_VERSION:
                raise SectorDataQueryError(
                    "published momentum formula identity is inconsistent"
                )
            self._validate_momentum_values(row)
            results.append(
                SectorPublishedMomentumRow(
                    batch_id=row.batch_id,
                    trade_date=row.trade_date,
                    comparison_scope=row.comparison_scope,
                    comparison_key=row.comparison_key,
                    parent_sector_code=row.parent_sector_code,
                    sector_code=row.sector_code,
                    sector_name=row.sector_name,
                    industry_level=int(row.industry_level),
                    hierarchy_path=row.hierarchy_path,
                    period=int(row.period),
                    return_pct=row.return_pct,
                    strength_rank=row.strength_rank,
                    rankable_count=row.rankable_count,
                    percentile=row.percentile,
                    calculation_status=row.calculation_status,
                    missing_reason=row.missing_reason,
                )
            )
        return tuple(results)

    @staticmethod
    def _validate_batch_identity(
        *,
        hierarchy_version: str,
        formula_bundle_version: str,
        hierarchy: SectorHierarchySnapshot,
    ) -> None:
        if hierarchy_version != hierarchy.baseline_version:
            raise SectorDataQueryError(
                "published sector-analysis hierarchy version is inconsistent"
            )
        if formula_bundle_version != FORMULA_BUNDLE_VERSION:
            raise SectorDataQueryError(
                "published sector-analysis formula bundle is inconsistent"
            )

    @staticmethod
    def _validate_momentum_values(row) -> None:  # type: ignore[no-untyped-def]
        values = (
            row.return_pct,
            row.strength_rank,
            row.rankable_count,
            row.percentile,
        )
        if row.calculation_status == "CALCULABLE":
            if any(value is None for value in values) or row.missing_reason != "NONE":
                raise SectorDataQueryError(
                    "published calculable momentum row is internally inconsistent"
                )
            if int(row.strength_rank) > int(row.rankable_count):
                raise SectorDataQueryError(
                    "published momentum rank exceeds its denominator"
                )
            return
        if row.calculation_status != "UNAVAILABLE":
            raise SectorDataQueryError("published momentum status is unsupported")
        if any(value is not None for value in values) or row.missing_reason == "NONE":
            raise SectorDataQueryError(
                "published unavailable momentum row is internally inconsistent"
            )
