from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchySnapshot,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    FORMULA_BUNDLE_VERSION,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    FORMULA_KEY as DUAL_FORMULA_KEY,
    FORMULA_VERSION as DUAL_FORMULA_VERSION,
    MINIMUM_GROUP_SIZE,
    SectorDualMomentumAbsoluteStatus,
    SectorDualMomentumCoordinateStatus,
    SectorDualMomentumDisplayStatus,
    SectorDualMomentumLeadingThreshold,
    SectorDualMomentumPeriod,
    SectorDualMomentumQualificationStatus,
    SectorDualMomentumRelativeStatus,
    parse_dual_momentum_leading_threshold,
    parse_dual_momentum_period,
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
    resolve_scope_pool,
)
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_contract import (
    FORMULA_KEY as ROTATION_FORMULA_KEY,
    FORMULA_VERSION as ROTATION_FORMULA_VERSION,
    SectorRelativeGroupInterpretation,
    SectorRelativeCoordinateStatus,
    SectorRelativeRotationStatus,
    parse_relative_rotation_period,
)
from src.foundation.models.core_serving.wealth_sector_relative_rotation_daily import (
    WealthSectorRelativeRotationDaily,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import (
    WealthSectorAnalysisPublishBatch,
)
from src.foundation.models.core_serving.wealth_sector_hierarchy import (
    WealthSectorHierarchy,
)
from src.foundation.models.core_serving.wealth_sector_dual_momentum_daily import (
    WealthSectorDualMomentumDaily,
)
from src.foundation.models.core_serving.wealth_sector_momentum_daily import (
    WealthSectorMomentumDaily,
)
from src.foundation.models.core_serving.wealth_sector_member_breadth_daily import (
    WealthSectorMemberBreadthDaily,
)
from src.foundation.models.core_serving.wealth_sector_member_ma_breadth_daily import (
    WealthSectorMemberMaBreadthDaily,
)
from src.foundation.models.core_serving.wealth_sector_price_volume_daily import (
    WealthSectorPriceVolumeDaily,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    FORMULA_KEY as PRICE_VOLUME_FORMULA_KEY,
    FORMULA_VERSION as PRICE_VOLUME_FORMULA_VERSION,
    SectorPriceVolumeMetricFact,
    SectorPriceVolumeMissingReason,
    SectorPriceVolumeState,
    parse_price_volume_period,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MEMBER_BREADTH_FORMULA_KEY,
    MEMBER_BREADTH_FORMULA_VERSION,
    MemberBreadthCompositionFact,
    MetricCoverageFact,
    ordered_member_breadth_reasons,
    parse_member_breadth_metric,
    parse_member_breadth_direction,
    parse_member_breadth_ma_period,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorSelectionInvalidError,
)


@dataclass(frozen=True, slots=True)
class SectorPublishedPriceVolumeRow:
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
    price_momentum_pct: Decimal | None
    amount_activity_pct: Decimal | None
    price_missing_reason: str | None
    amount_missing_reason: str | None
    price_rank: int | None
    price_rankable_count: int | None
    amount_rank: int | None
    amount_rankable_count: int | None
    distribution_state: SectorPriceVolumeState | None
    calculation_status: str
    missing_reason: str

    @property
    def metric(self) -> SectorPriceVolumeMetricFact:
        return SectorPriceVolumeMetricFact(
            sector_code=self.sector_code, trade_date=self.trade_date,
            price_momentum_pct=self.price_momentum_pct,
            amount_activity_pct=self.amount_activity_pct,
            price_missing_reason=(SectorPriceVolumeMissingReason(self.price_missing_reason)
                                  if self.price_missing_reason is not None else None),
            amount_missing_reason=(SectorPriceVolumeMissingReason(self.amount_missing_reason)
                                   if self.amount_missing_reason is not None else None),
        )


@dataclass(frozen=True, slots=True)
class SectorPublishedBreadthRow:
    sector_code: str
    composition: MemberBreadthCompositionFact
    rank: int | None
    rank_total: int | None


@dataclass(frozen=True, slots=True)
class SectorPublishedBreadthDay:
    trade_date: date
    batch_id: UUID | None
    compositions: tuple[MemberBreadthCompositionFact, ...]


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
class SectorPublishedDualMomentumRow(SectorPublishedMomentumRow):
    absolute_status: SectorDualMomentumAbsoluteStatus
    relative_status: SectorDualMomentumRelativeStatus
    qualification_status: SectorDualMomentumQualificationStatus
    coordinate_status: SectorDualMomentumCoordinateStatus
    display_status: SectorDualMomentumDisplayStatus


@dataclass(frozen=True, slots=True)
class SectorPublishedRelativeRotationRow(SectorPublishedMomentumRow):
    comparison_trade_date: date
    comparison_return_pct: Decimal | None
    comparison_strength_rank: int | None
    comparison_rankable_count: int | None
    comparison_percentile: Decimal | None
    percentile_delta_5d: Decimal | None
    rotation_status: SectorRelativeRotationStatus
    coordinate_status: SectorRelativeCoordinateStatus
    group_interpretation: SectorRelativeGroupInterpretation
    current_missing_reason: str | None
    comparison_missing_reason: str | None


@dataclass(frozen=True, slots=True)
class SectorMomentumFactSelection:
    trade_dates: tuple[date, ...]
    comparison_scope: SectorMomentumScope
    comparison_key: str


@dataclass(frozen=True, slots=True)
class SectorMomentumHistorySelection:
    trade_dates: tuple[date, ...]
    comparison_scope: SectorMomentumScope
    comparison_key: str
    selected_sector_code: str
    expected_sector_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.trade_dates or len(self.trade_dates) > 60:
            raise SectorDataQueryError(
                "published momentum history selection must contain 1 to 60 dates"
            )
        if self.trade_dates != tuple(sorted(set(self.trade_dates))):
            raise SectorDataQueryError(
                "published momentum history dates must be unique and ascending"
            )
        if not self.expected_sector_codes or len(self.expected_sector_codes) != len(
            set(self.expected_sector_codes)
        ):
            raise SectorDataQueryError(
                "published momentum history comparison pool is invalid"
            )
        if self.selected_sector_code not in self.expected_sector_codes:
            raise SectorDataQueryError(
                "selected sector is outside the momentum history comparison pool"
            )
        expected_key = {
            "LEVEL_1": "GLOBAL:L1",
            "LEVEL_2": "GLOBAL:L2",
            "LEVEL_3": "GLOBAL:L3",
        }.get(self.comparison_scope)
        if expected_key is not None:
            if self.comparison_key != expected_key:
                raise SectorDataQueryError(
                    "published momentum history scope and key are inconsistent"
                )
            return
        key_prefix = {
            "LEVEL_1_CHILDREN": "PARENT:L1:",
            "LEVEL_2_CHILDREN": "PARENT:L2:",
        }.get(self.comparison_scope)
        if key_prefix is None or not self.comparison_key.startswith(key_prefix):
            raise SectorDataQueryError(
                "published momentum history scope and key are inconsistent"
            )
        if not self.comparison_key.removeprefix(key_prefix):
            raise SectorDataQueryError(
                "published momentum history parent key is incomplete"
            )


@dataclass(frozen=True, slots=True)
class SectorPublishedMomentumHistorySlice:
    batch_id: UUID
    trade_date: date
    comparison_scope: SectorMomentumScope
    comparison_key: str
    selected_sector_code: str
    selected_return_pct: Decimal | None
    selected_strength_rank: int | None
    selected_percentile: Decimal | None
    selected_calculation_status: str
    selected_missing_reason: str
    row_count: int
    calculable_count: int


def _breadth_columns(model, metric: str, label: str = ""):
    prefix = (
        ""
        if metric == "MA_POSITION"
        else "member_"
        if metric == "MEMBER_COUNT"
        else "turnover_"
    )
    names = {"source_count": "source_member_count"}
    names.update(
        {
            name: prefix + name
            for name in (
                "calculable_count",
                "coverage_pct",
                "qualification",
                "reason_codes",
            )
        }
    )
    for direction, stored in (("up", "above"), ("flat", "equal"), ("down", "below")):
        for suffix in ("count", "pct"):
            names[direction + "_" + suffix] = (
                (stored if metric == "MA_POSITION" else prefix + direction)
                + "_"
                + suffix
            )
    return tuple(
        getattr(model, column).label(label + name) for name, column in names.items()
    )


def _validate_breadth_identity(row, node, parent, *, prefix: str = "") -> None:
    values = row if hasattr(row, "keys") else row._mapping
    expected = dict(
        sector_code=node.sector_code,
        sector_name=node.sector_name,
        industry_level=node.industry_level,
        hierarchy_path=node.hierarchy_path,
        parent_sector_code=parent,
        formula_key=MEMBER_BREADTH_FORMULA_KEY,
        formula_version=MEMBER_BREADTH_FORMULA_VERSION,
    )
    if any(values[prefix + key] != value for key, value in expected.items()):
        raise SectorDataQueryError("published breadth identity is inconsistent")


def _breadth_composition(
    row, metric: str, prefix: str = ""
) -> MemberBreadthCompositionFact:
    def value(name):
        return row[prefix + name]

    source, count = value("source_count"), value("calculable_count")
    counts = tuple(value(d + "_count") for d in ("up", "flat", "down"))
    percentages = tuple(value(d + "_pct") for d in ("up", "flat", "down"))
    coverage, reasons, qualification = (
        value("coverage_pct"),
        value("reason_codes"),
        value("qualification"),
    )
    if (
        any(type(n) is not int or n < 0 for n in (source, count, *counts))
        or count > source
        or sum(counts) != count
    ):
        raise SectorDataQueryError("published breadth counts are invalid")
    if coverage is None or not coverage.is_finite() or not 0 <= coverage <= 100:
        raise SectorDataQueryError("published breadth coverage is invalid")
    expected_coverage = Decimal(count) / source * 100 if source else Decimal(0)
    if abs(coverage - expected_coverage) > Decimal("0.00005"):
        raise SectorDataQueryError("published breadth coverage does not match counts")
    if not isinstance(reasons, (list, tuple)) or tuple(
        reasons
    ) != ordered_member_breadth_reasons(reasons):
        raise SectorDataQueryError("published breadth reasons are invalid")
    present = all(p is not None for p in percentages)
    if not present and any(p is not None for p in percentages):
        raise SectorDataQueryError(
            "published breadth percentages must be null together"
        )
    if present and (
        any(not p.is_finite() or not 0 <= p <= 100 for p in percentages)
        or abs(sum(percentages) - 100) > Decimal("0.00015")
    ):
        raise SectorDataQueryError("published breadth percentages are invalid")
    eligible = count >= 5 and coverage >= 80 and present
    if (
        qualification not in {"ELIGIBLE", "INELIGIBLE"}
        or (qualification == "ELIGIBLE") != eligible
    ):
        raise SectorDataQueryError("published breadth qualification is inconsistent")
    return MemberBreadthCompositionFact(
        metric=metric,
        up_count=counts[0],
        flat_count=counts[1],
        down_count=counts[2],
        up_pct=percentages[0],
        flat_pct=percentages[1],
        down_pct=percentages[2],
        coverage=MetricCoverageFact(source, count, coverage, eligible, tuple(reasons)),
    )


class SectorAnalysisFactReader:
    """Read immutable sector-analysis facts through their PUBLISHED batch identity."""

    def load_momentum_coverage(
        self,
        session: Session,
        *,
        coverage_end_date: date,
        hierarchy: SectorHierarchySnapshot,
        allow_empty: bool = False,
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
        if allow_empty:
            # Price-volume can render an empty Meta before its first publication.
            first_published_date = func.coalesce(
                select(func.min(WealthSectorAnalysisPublishBatch.trade_date))
                .where(
                    WealthSectorAnalysisPublishBatch.status == "PUBLISHED",
                    WealthSectorAnalysisPublishBatch.trade_date <= coverage_end_date,
                )
                .scalar_subquery(),
                coverage_end_date,
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
        if not published and not allow_empty:
            raise SectorDataQueryError("published sector-analysis coverage is empty")
        return SectorPublishedCoverage(
            coverage_start_date=calendar_dates[0].availability.trade_date,
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

    def load_dual_momentum_rows(
        self,
        session: Session,
        *,
        batch_id: UUID,
        trade_date: date,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
        period: SectorDualMomentumPeriod,
        leading_threshold: SectorDualMomentumLeadingThreshold,
        hierarchy: SectorHierarchySnapshot,
    ) -> tuple[SectorPublishedDualMomentumRow, ...]:
        """Read one published slice; never inspect or repair its upstream inputs."""
        parse_dual_momentum_period(period)
        parse_dual_momentum_leading_threshold(leading_threshold)
        pool = resolve_scope_pool(
            hierarchy, scope=scope, level1_code=level1_code, level2_code=level2_code,
        )
        parent_code = (
            level1_code if scope == "LEVEL_1_CHILDREN"
            else level2_code if scope == "LEVEL_2_CHILDREN" else None
        )
        key = {
            "LEVEL_1": "GLOBAL:L1", "LEVEL_2": "GLOBAL:L2", "LEVEL_3": "GLOBAL:L3",
            "LEVEL_1_CHILDREN": f"PARENT:L1:{level1_code}",
            "LEVEL_2_CHILDREN": f"PARENT:L2:{level2_code}",
        }[scope]
        fact, batch = WealthSectorDualMomentumDaily, WealthSectorAnalysisPublishBatch
        base_fields = tuple(field.name for field in fields(SectorPublishedMomentumRow))
        statement = (
            select(
                *(getattr(fact, name) for name in base_fields),
                fact.absolute_status, fact.coordinate_status,
                getattr(fact, f"relative_status_{leading_threshold}").label("relative_status"),
                getattr(fact, f"qualification_status_{leading_threshold}").label("qualification_status"),
                getattr(fact, f"display_status_{leading_threshold}").label("display_status"),
                fact.minimum_group_size, fact.formula_key, fact.formula_version,
                batch.hierarchy_version, batch.formula_bundle_version,
            )
            .join(batch, and_(
                batch.batch_id == fact.batch_id,
                batch.trade_date == fact.trade_date,
                batch.status == "PUBLISHED",
            ))
            .where(
                fact.batch_id == batch_id, fact.trade_date == trade_date,
                fact.comparison_scope == scope, fact.comparison_key == key,
                fact.period == period,
            )
            .order_by(fact.sector_code)
        )
        rows = session.execute(statement).all()
        expected_codes = {node.sector_code for node in pool}
        if len(rows) != len(expected_codes) or {row.sector_code for row in rows} != expected_codes:
            raise SectorDataQueryError("published dual-momentum slice does not match its object pool")
        calculable_count = sum(row.calculation_status == "CALCULABLE" for row in rows)
        result = []
        for row in rows:
            self._validate_batch_identity(
                hierarchy_version=row.hierarchy_version,
                formula_bundle_version=row.formula_bundle_version, hierarchy=hierarchy,
            )
            node = hierarchy.nodes_by_code[row.sector_code]
            if (
                row.parent_sector_code != parent_code
                or row.sector_name != node.sector_name
                or row.industry_level != node.industry_level
                or row.hierarchy_path != node.hierarchy_path
                or row.formula_key != DUAL_FORMULA_KEY
                or row.formula_version != DUAL_FORMULA_VERSION
                or row.minimum_group_size != MINIMUM_GROUP_SIZE
            ):
                raise SectorDataQueryError("published dual-momentum identity is inconsistent")
            self._validate_momentum_values(row)
            if row.calculation_status == "CALCULABLE" and (
                not row.return_pct.is_finite() or not row.percentile.is_finite()
                or not 0 <= row.percentile <= 100
                or not 1 <= row.strength_rank <= calculable_count
                or row.rankable_count != calculable_count
            ):
                raise SectorDataQueryError("published dual-momentum values are invalid")
            result.append(SectorPublishedDualMomentumRow(**{
                field.name: row._mapping[field.name]
                for field in fields(SectorPublishedDualMomentumRow)
            }))
        return tuple(result)

    def load_price_volume_rows(
        self, session: Session, *, batch_id: UUID, trade_date: date,
        scope: SectorMomentumScope, level1_code: str | None, level2_code: str | None,
        period: int, hierarchy: SectorHierarchySnapshot,
    ) -> tuple[SectorPublishedPriceVolumeRow, ...]:
        return self._load_price_volume_rows(
            session, batch_by_date={trade_date: batch_id}, scope=scope,
            level1_code=level1_code, level2_code=level2_code, period=period,
            hierarchy=hierarchy, selected_sector_code=None,
        )

    def load_price_volume_history(
        self, session: Session, *, batch_by_date: dict[date, UUID],
        scope: SectorMomentumScope, level1_code: str | None, level2_code: str | None,
        period: int, hierarchy: SectorHierarchySnapshot, selected_sector_code: str,
    ) -> tuple[SectorPublishedPriceVolumeRow, ...]:
        if len(batch_by_date) > 60:
            raise SectorDataQueryError("published price-volume history exceeds 60 slots")
        return self._load_price_volume_rows(
            session, batch_by_date=batch_by_date, scope=scope,
            level1_code=level1_code, level2_code=level2_code, period=period,
            hierarchy=hierarchy, selected_sector_code=selected_sector_code,
        )

    def _load_price_volume_rows(
        self, session: Session, *, batch_by_date: dict[date, UUID],
        scope: SectorMomentumScope, level1_code: str | None, level2_code: str | None,
        period: int, hierarchy: SectorHierarchySnapshot, selected_sector_code: str | None,
    ) -> tuple[SectorPublishedPriceVolumeRow, ...]:
        parse_price_volume_period(period)
        pool = resolve_scope_pool(
            hierarchy, scope=scope, level1_code=level1_code, level2_code=level2_code,
        )
        expected_codes = {node.sector_code for node in pool}
        if selected_sector_code is not None:
            if selected_sector_code not in expected_codes:
                raise SectorDataQueryError("published price-volume selection is outside its pool")
            expected_codes = {selected_sector_code}
        if not batch_by_date:
            return ()
        parent_code = (level1_code if scope == "LEVEL_1_CHILDREN"
                       else level2_code if scope == "LEVEL_2_CHILDREN" else None)
        key = {
            "LEVEL_1": "GLOBAL:L1", "LEVEL_2": "GLOBAL:L2", "LEVEL_3": "GLOBAL:L3",
            "LEVEL_1_CHILDREN": f"PARENT:L1:{level1_code}",
            "LEVEL_2_CHILDREN": f"PARENT:L2:{level2_code}",
        }[scope]
        fact, batch = WealthSectorPriceVolumeDaily, WealthSectorAnalysisPublishBatch
        statement = (
            select(
                *(getattr(fact, field.name) for field in fields(SectorPublishedPriceVolumeRow)),
                fact.formula_key, fact.formula_version,
                batch.hierarchy_version, batch.formula_bundle_version,
            )
            .join(batch, and_(batch.batch_id == fact.batch_id,
                             batch.trade_date == fact.trade_date, batch.status == "PUBLISHED"))
            .where(
                or_(*(and_(fact.trade_date == day, fact.batch_id == batch_id)
                      for day, batch_id in sorted(batch_by_date.items()))),
                fact.comparison_scope == scope, fact.comparison_key == key, fact.period == period,
            )
            .order_by(fact.trade_date, fact.sector_code)
        )
        if selected_sector_code is not None:
            statement = statement.where(fact.sector_code == selected_sector_code)
        rows = session.execute(statement).all()
        expected_keys = {(day, code) for day in batch_by_date for code in expected_codes}
        if len(rows) != len(expected_keys) or {
            (row.trade_date, row.sector_code) for row in rows
        } != expected_keys:
            raise SectorDataQueryError("published price-volume slice does not match its selection")
        result = []
        for row in rows:
            self._validate_batch_identity(
                hierarchy_version=row.hierarchy_version,
                formula_bundle_version=row.formula_bundle_version, hierarchy=hierarchy,
            )
            node = hierarchy.nodes_by_code[row.sector_code]
            if (row.parent_sector_code != parent_code or row.sector_name != node.sector_name
                or row.industry_level != node.industry_level or row.hierarchy_path != node.hierarchy_path
                or row.formula_key != PRICE_VOLUME_FORMULA_KEY
                or row.formula_version != PRICE_VOLUME_FORMULA_VERSION):
                raise SectorDataQueryError("published price-volume identity is inconsistent")
            projected = SectorPublishedPriceVolumeRow(**{
                field.name: row._mapping[field.name] for field in fields(SectorPublishedPriceVolumeRow)
            })
            self._validate_price_volume_values(projected, pool_size=len(pool))
            result.append(projected)
        if selected_sector_code is None:
            for prefix, field in (("price", "price_momentum_pct"), ("amount", "amount_activity_pct")):
                count = sum(getattr(row, field) is not None for row in result)
                if any(getattr(row, field) is not None
                       and getattr(row, f"{prefix}_rankable_count") != count for row in result):
                    raise SectorDataQueryError("published price-volume group counts are inconsistent")
        return tuple(result)

    @staticmethod
    def _validate_price_volume_values(row: SectorPublishedPriceVolumeRow, *, pool_size: int) -> None:
        try:
            metric = row.metric
        except (TypeError, ValueError) as exc:
            raise SectorDataQueryError("published price-volume metric is inconsistent") from exc
        for prefix, value in (("price", metric.price_momentum_pct), ("amount", metric.amount_activity_pct)):
            rank, count = getattr(row, f"{prefix}_rank"), getattr(row, f"{prefix}_rankable_count")
            if value is None:
                if rank is not None or count is not None:
                    raise SectorDataQueryError("missing published price-volume metric carries ranks")
            elif type(rank) is not int or type(count) is not int or not 1 <= rank <= count <= pool_size:
                raise SectorDataQueryError("published price-volume rank is inconsistent")
        both = metric.price_momentum_pct is not None and metric.amount_activity_pct is not None
        if (row.calculation_status != ("CALCULABLE" if both else "UNAVAILABLE")
            or row.missing_reason != (row.price_missing_reason or row.amount_missing_reason or "NONE")):
            raise SectorDataQueryError("published price-volume status is inconsistent")
        if not both:
            if row.distribution_state is not None:
                raise SectorDataQueryError("missing published coordinate carries a state")
        else:
            # Validate the stored quadrant, never substitute a recomputed state.
            signs = {"JOINT": (True, True), "PRICE_ONLY": (True, False),
                     "AMOUNT_ONLY": (False, True), "NEUTRAL": (False, False)}
            if signs.get(row.distribution_state) != (
                metric.price_momentum_pct > 0, metric.amount_activity_pct > 0,
            ):
                raise SectorDataQueryError("published price-volume state contradicts its values")

    def load_relative_rotation_rows(
        self, session: Session, *, batch_id: UUID, trade_date: date,
        scope: SectorMomentumScope, level1_code: str | None, level2_code: str | None,
        period: int, hierarchy: SectorHierarchySnapshot,
    ) -> tuple[SectorPublishedRelativeRotationRow, ...]:
        """Read the complete current pool, not its historical cross product."""
        return self._load_relative_rotation_rows(
            session, batch_by_date={trade_date: batch_id}, scope=scope,
            level1_code=level1_code, level2_code=level2_code, period=period,
            hierarchy=hierarchy, selected_sector_code=None,
        )

    def load_relative_rotation_history(
        self, session: Session, *, batch_by_date: dict[date, UUID],
        scope: SectorMomentumScope, level1_code: str | None, level2_code: str | None,
        period: int, hierarchy: SectorHierarchySnapshot, selected_sector_code: str,
    ) -> tuple[SectorPublishedRelativeRotationRow, ...]:
        """One selected sector per published date; absent dates remain caller-owned slots."""
        if not batch_by_date:
            return ()
        if len(batch_by_date) > 59:
            raise SectorDataQueryError("published rotation history exceeds 59 previous slots")
        return self._load_relative_rotation_rows(
            session, batch_by_date=batch_by_date, scope=scope,
            level1_code=level1_code, level2_code=level2_code, period=period,
            hierarchy=hierarchy, selected_sector_code=selected_sector_code,
        )

    def _load_relative_rotation_rows(
        self, session: Session, *, batch_by_date: dict[date, UUID],
        scope: SectorMomentumScope, level1_code: str | None, level2_code: str | None,
        period: int, hierarchy: SectorHierarchySnapshot, selected_sector_code: str | None,
    ) -> tuple[SectorPublishedRelativeRotationRow, ...]:
        parse_relative_rotation_period(period)
        pool = resolve_scope_pool(
            hierarchy, scope=scope, level1_code=level1_code, level2_code=level2_code,
        )
        expected_codes = {node.sector_code for node in pool}
        if selected_sector_code is not None:
            if selected_sector_code not in expected_codes:
                raise SectorDataQueryError("published rotation selection is outside its pool")
            expected_codes = {selected_sector_code}
        parent_code = (
            level1_code if scope == "LEVEL_1_CHILDREN"
            else level2_code if scope == "LEVEL_2_CHILDREN" else None
        )
        key = {
            "LEVEL_1": "GLOBAL:L1", "LEVEL_2": "GLOBAL:L2", "LEVEL_3": "GLOBAL:L3",
            "LEVEL_1_CHILDREN": f"PARENT:L1:{level1_code}",
            "LEVEL_2_CHILDREN": f"PARENT:L2:{level2_code}",
        }[scope]
        fact, batch = WealthSectorRelativeRotationDaily, WealthSectorAnalysisPublishBatch
        statement = (
            select(
                *(getattr(fact, field.name) for field in fields(SectorPublishedRelativeRotationRow)),
                fact.minimum_group_size, fact.formula_key, fact.formula_version,
                batch.hierarchy_version, batch.formula_bundle_version,
            )
            .join(batch, and_(
                batch.batch_id == fact.batch_id, batch.trade_date == fact.trade_date,
                batch.status == "PUBLISHED",
            ))
            .where(
                or_(*(and_(fact.trade_date == day, fact.batch_id == batch_id)
                      for day, batch_id in sorted(batch_by_date.items()))),
                fact.comparison_scope == scope, fact.comparison_key == key,
                fact.period == period,
            )
            .order_by(fact.trade_date, fact.sector_code)
        )
        if selected_sector_code is not None:
            statement = statement.where(fact.sector_code == selected_sector_code)
        rows = session.execute(statement).all()
        expected_keys = {(day, code) for day in batch_by_date for code in expected_codes}
        if len(rows) != len(expected_keys) or {
            (row.trade_date, row.sector_code) for row in rows
        } != expected_keys:
            raise SectorDataQueryError("published rotation slice does not match its selection")
        result = []
        for row in rows:
            self._validate_batch_identity(
                hierarchy_version=row.hierarchy_version,
                formula_bundle_version=row.formula_bundle_version, hierarchy=hierarchy,
            )
            node = hierarchy.nodes_by_code[row.sector_code]
            if (
                row.parent_sector_code != parent_code
                or row.sector_name != node.sector_name
                or row.industry_level != node.industry_level
                or row.hierarchy_path != node.hierarchy_path
                or row.formula_key != ROTATION_FORMULA_KEY
                or row.formula_version != ROTATION_FORMULA_VERSION
                or row.minimum_group_size != MINIMUM_GROUP_SIZE
                or row.comparison_trade_date >= row.trade_date
            ):
                raise SectorDataQueryError("published rotation identity is inconsistent")
            self._validate_rotation_values(row, pool_size=len(pool))
            result.append(SectorPublishedRelativeRotationRow(**{
                field.name: row._mapping[field.name]
                for field in fields(SectorPublishedRelativeRotationRow)
            }))
        if selected_sector_code is None:
            current_count = sum(row.percentile is not None for row in rows)
            comparison_count = sum(row.comparison_percentile is not None for row in rows)
            expected_group = (
                "QUADRANT" if min(current_count, comparison_count) >= MINIMUM_GROUP_SIZE
                else "SAMPLE_INSUFFICIENT"
            )
            if any(
                row.group_interpretation != expected_group
                or (row.percentile is not None and row.rankable_count != current_count)
                or (row.comparison_percentile is not None
                    and row.comparison_rankable_count != comparison_count)
                for row in rows
            ):
                raise SectorDataQueryError("published rotation group fields are inconsistent")
        return tuple(result)

    @staticmethod
    def _validate_rotation_values(row, *, pool_size: int) -> None:
        # Validate stored response shape only; do not re-audit upstream prices.
        missing_reasons = {
            "HISTORY_INSUFFICIENT", "DATE_MISSING", "CLOSE_MISSING",
            "CLOSE_NON_POSITIVE", "PCT_CHANGE_MISSING",
        }
        for prefix, reason in (
            ("", row.current_missing_reason),
            ("comparison_", row.comparison_missing_reason),
        ):
            value, rank, count, percentile = (
                getattr(row, prefix + name)
                for name in ("return_pct", "strength_rank", "rankable_count", "percentile")
            )
            if percentile is None:
                if any(item is not None for item in (value, rank, count)) or reason not in missing_reasons:
                    raise SectorDataQueryError("published rotation missing fields are inconsistent")
            elif (
                value is None or rank is None or count is None or reason is not None
                or not value.is_finite() or not percentile.is_finite()
                or not 0 <= percentile <= 100 or not 1 <= rank <= count <= pool_size
            ):
                raise SectorDataQueryError("published rotation numeric fields are invalid")
        complete = row.percentile is not None and row.comparison_percentile is not None
        if row.group_interpretation not in {"QUADRANT", "SAMPLE_INSUFFICIENT"}:
            raise SectorDataQueryError("published rotation group interpretation is invalid")
        if complete:
            delta = row.percentile_delta_5d
            if (
                delta is None or not delta.is_finite() or not -100 <= delta <= 100
                or row.coordinate_status != "PLOTTABLE"
                or row.calculation_status != "CALCULABLE" or row.missing_reason != "NONE"
                or (row.group_interpretation == "SAMPLE_INSUFFICIENT"
                    and row.rotation_status != "SAMPLE_INSUFFICIENT")
                or (row.group_interpretation == "QUADRANT" and row.rotation_status not in {
                    "LEADING_IMPROVING", "WEAK_IMPROVING",
                    "STRONG_NOT_IMPROVING", "WEAK_NOT_IMPROVING",
                })
            ):
                raise SectorDataQueryError("published rotation coordinates are inconsistent")
        elif (
            row.percentile_delta_5d is not None or row.coordinate_status != "UNAVAILABLE"
            or row.rotation_status != "DATA_INSUFFICIENT"
            or row.calculation_status != "UNAVAILABLE"
            or row.missing_reason != (row.current_missing_reason or row.comparison_missing_reason)
        ):
            raise SectorDataQueryError("published rotation unavailable fields are inconsistent")

    def load_breadth_rankings(
        self,
        session: Session,
        *,
        batch_id: UUID,
        trade_date: date,
        hierarchy: SectorHierarchySnapshot,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
        metric: str,
        direction: str,
        ma_period: int,
    ) -> tuple[SectorPublishedBreadthRow, ...]:
        parse_member_breadth_metric(metric)
        parse_member_breadth_direction(direction)
        parse_member_breadth_ma_period(ma_period)
        pool = resolve_scope_pool(
            hierarchy, scope=scope, level1_code=level1_code, level2_code=level2_code
        )
        parent = (
            level1_code
            if scope == "LEVEL_1_CHILDREN"
            else level2_code
            if scope == "LEVEL_2_CHILDREN"
            else None
        )
        key = {
            "LEVEL_1": "GLOBAL:L1",
            "LEVEL_2": "GLOBAL:L2",
            "LEVEL_3": "GLOBAL:L3",
            "LEVEL_1_CHILDREN": f"PARENT:L1:{level1_code}",
            "LEVEL_2_CHILDREN": f"PARENT:L2:{level2_code}",
        }[scope]
        fact = (
            WealthSectorMemberMaBreadthDaily
            if metric == "MA_POSITION"
            else WealthSectorMemberBreadthDaily
        )
        prefix = (
            ""
            if metric == "MA_POSITION"
            else "member_"
            if metric == "MEMBER_COUNT"
            else "turnover_"
        )
        rank_prefix = prefix + direction.lower()
        batch = WealthSectorAnalysisPublishBatch
        statement = (
            select(
                fact.sector_code,
                fact.sector_name,
                fact.industry_level,
                fact.hierarchy_path,
                fact.parent_sector_code,
                fact.formula_key,
                fact.formula_version,
                batch.hierarchy_version,
                batch.formula_bundle_version,
                *_breadth_columns(fact, metric),
                getattr(fact, rank_prefix + "_rank").label("rank"),
                getattr(fact, rank_prefix + "_rankable_count").label("rank_total"),
            )
            .join(
                batch,
                and_(
                    batch.batch_id == fact.batch_id,
                    batch.trade_date == fact.trade_date,
                    batch.status == "PUBLISHED",
                ),
            )
            .where(
                fact.batch_id == batch_id,
                fact.trade_date == trade_date,
                fact.comparison_scope == scope,
                fact.comparison_key == key,
            )
            .order_by(fact.sector_code)
        )
        if metric == "MA_POSITION":
            statement = statement.where(fact.ma_period == ma_period)
        rows = session.execute(statement).all()
        if len(rows) != len(pool) or {r.sector_code for r in rows} != {
            n.sector_code for n in pool
        }:
            raise SectorDataQueryError(
                "published breadth comparison pool is incomplete"
            )
        result = []
        for row in rows:
            self._validate_batch_identity(
                hierarchy_version=row.hierarchy_version,
                formula_bundle_version=row.formula_bundle_version,
                hierarchy=hierarchy,
            )
            _validate_breadth_identity(
                row, hierarchy.nodes_by_code[row.sector_code], parent
            )
            composition = _breadth_composition(row._mapping, metric)
            if composition.coverage.eligible:
                if (
                    row.rank is None
                    or row.rank_total is None
                    or not 1 <= row.rank <= row.rank_total <= len(pool)
                ):
                    raise SectorDataQueryError("published breadth rank is invalid")
            elif row.rank is not None or row.rank_total is not None:
                raise SectorDataQueryError("ineligible breadth cannot carry a rank")
            result.append(
                SectorPublishedBreadthRow(
                    row.sector_code, composition, row.rank, row.rank_total
                )
            )
        total = sum(row.rank is not None for row in result)
        if any(row.rank_total != total for row in result if row.rank is not None):
            raise SectorDataQueryError("published breadth rank denominator is invalid")
        return tuple(
            sorted(result, key=lambda r: (r.rank is None, r.rank or 0, r.sector_code))
        )

    def load_breadth_history(
        self,
        session: Session,
        *,
        hierarchy: SectorHierarchySnapshot,
        sector_code: str,
        trade_date: date,
        history_range: int,
        ma_period: int,
    ) -> tuple[SectorPublishedBreadthDay, ...]:
        parse_member_breadth_ma_period(ma_period)
        if (
            history_range not in (20, 30, 60)
            or sector_code not in hierarchy.nodes_by_code
        ):
            raise SectorSelectionInvalidError("成员广度历史选择不合法")
        node = hierarchy.nodes_by_code[sector_code]
        batch = WealthSectorAnalysisPublishBatch
        first_date = (
            select(func.min(batch.trade_date))
            .where(batch.status == "PUBLISHED")
            .scalar_subquery()
        )
        dates = (
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date >= first_date,
                TradeCalendar.trade_date <= trade_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(history_range)
            .subquery()
        )
        ordinary, ma = WealthSectorMemberBreadthDaily, WealthSectorMemberMaBreadthDaily
        scope, key = f"LEVEL_{node.industry_level}", f"GLOBAL:L{node.industry_level}"

        def matches(fact):
            return and_(
                fact.batch_id == batch.batch_id,
                fact.trade_date == dates.c.trade_date,
                fact.comparison_scope == scope,
                fact.comparison_key == key,
                fact.sector_code == sector_code,
            )

        identity = (
            "sector_code",
            "sector_name",
            "industry_level",
            "hierarchy_path",
            "parent_sector_code",
            "formula_key",
            "formula_version",
        )
        rows = session.execute(
            select(
                dates.c.trade_date,
                batch.batch_id,
                batch.hierarchy_version,
                batch.formula_bundle_version,
                *(getattr(ordinary, name).label("o_" + name) for name in identity),
                *(getattr(ma, name).label("a_" + name) for name in identity),
                *_breadth_columns(ordinary, "MEMBER_COUNT", "m_"),
                *_breadth_columns(ordinary, "TURNOVER", "t_"),
                *_breadth_columns(ma, "MA_POSITION", "a_"),
            )
            .select_from(dates)
            .outerjoin(
                batch,
                and_(
                    batch.trade_date == dates.c.trade_date, batch.status == "PUBLISHED"
                ),
            )
            .outerjoin(ordinary, matches(ordinary))
            .outerjoin(ma, and_(matches(ma), ma.ma_period == ma_period))
            .order_by(dates.c.trade_date)
        ).all()
        if not rows or rows[-1].trade_date != trade_date:
            raise SectorSelectionInvalidError(
                "tradeDate 必须是已发布覆盖内的 SSE 开市日"
            )
        if len({row.trade_date for row in rows}) != len(rows):
            raise SectorDataQueryError("duplicate published breadth dates")
        result = []
        for row in rows:
            if row.batch_id is None:
                result.append(SectorPublishedBreadthDay(row.trade_date, None, ()))
                continue
            self._validate_batch_identity(
                hierarchy_version=row.hierarchy_version,
                formula_bundle_version=row.formula_bundle_version,
                hierarchy=hierarchy,
            )
            for prefix in ("o_", "a_"):
                _validate_breadth_identity(row._mapping, node, None, prefix=prefix)
            comps = tuple(
                _breadth_composition(row._mapping, metric, prefix)
                for metric, prefix in (
                    ("MEMBER_COUNT", "m_"),
                    ("TURNOVER", "t_"),
                    ("MA_POSITION", "a_"),
                )
            )
            if len({c.coverage.source_count for c in comps}) != 1:
                raise SectorDataQueryError("published breadth source counts differ")
            result.append(
                SectorPublishedBreadthDay(row.trade_date, row.batch_id, comps)
            )
        return tuple(result)

    def load_momentum_history_slices(
        self,
        session: Session,
        *,
        selections: tuple[SectorMomentumHistorySelection, ...],
        period: SectorMomentumPeriod,
        hierarchy: SectorHierarchySnapshot,
    ) -> tuple[SectorPublishedMomentumHistorySlice, ...]:
        if not selections or len(selections) > 3:
            raise SectorDataQueryError(
                "published momentum history requires 1 to 3 selections"
            )
        selection_identities = tuple(
            (item.comparison_scope, item.comparison_key) for item in selections
        )
        if len(selection_identities) != len(set(selection_identities)):
            raise SectorDataQueryError(
                "published momentum history selections must be unique"
            )

        branches = tuple(
            self._momentum_history_branch(selection=selection, period=period)
            for selection in selections
        )
        combined = (
            branches[0] if len(branches) == 1 else union_all(*branches)
        ).subquery()
        rows = session.execute(
            select(combined).order_by(
                combined.c.trade_date,
                combined.c.comparison_scope,
                combined.c.comparison_key,
            )
        ).all()

        selection_by_identity = {
            (item.comparison_scope, item.comparison_key): item for item in selections
        }
        expected_groups = {
            (trade_date, item.comparison_scope, item.comparison_key)
            for item in selections
            for trade_date in item.trade_dates
        }
        seen_groups: set[tuple[date, str, str]] = set()
        results: list[SectorPublishedMomentumHistorySlice] = []
        for row in rows:
            group_key = (row.trade_date, row.comparison_scope, row.comparison_key)
            if group_key not in expected_groups or group_key in seen_groups:
                raise SectorDataQueryError(
                    "published momentum history returned an unexpected group"
                )
            seen_groups.add(group_key)
            selection = selection_by_identity.get(
                (row.comparison_scope, row.comparison_key)
            )
            if selection is None:
                raise SectorDataQueryError(
                    "published momentum history returned an unknown selection"
                )
            self._validate_batch_identity(
                hierarchy_version=row.hierarchy_version,
                formula_bundle_version=row.formula_bundle_version,
                hierarchy=hierarchy,
            )
            row_count = int(row.row_count or 0)
            calculable_count = int(row.calculable_count or 0)
            if (
                row_count != len(selection.expected_sector_codes)
                or int(row.distinct_sector_count or 0) != row_count
                or int(row.unexpected_sector_count or 0) != 0
            ):
                raise SectorDataQueryError(
                    "published momentum history slice does not match the comparison pool"
                )
            if (
                int(row.hierarchy_error_count or 0) != 0
                or int(row.parent_error_count or 0) != 0
            ):
                raise SectorDataQueryError(
                    "published momentum history slice does not match the hierarchy"
                )
            if int(row.formula_error_count or 0) != 0:
                raise SectorDataQueryError(
                    "published momentum history formula identity is inconsistent"
                )
            if int(row.value_error_count or 0) != 0:
                raise SectorDataQueryError(
                    "published momentum history values are internally inconsistent"
                )
            if int(row.selected_count or 0) != 1:
                raise SectorDataQueryError(
                    "published momentum history selected sector is missing or duplicated"
                )
            min_denominator = row.min_rankable_count
            max_denominator = row.max_rankable_count
            if calculable_count == 0:
                if min_denominator is not None or max_denominator is not None:
                    raise SectorDataQueryError(
                        "published momentum history rank denominator is inconsistent"
                    )
            elif (
                min_denominator is None
                or max_denominator is None
                or int(min_denominator) != calculable_count
                or int(max_denominator) != calculable_count
            ):
                raise SectorDataQueryError(
                    "published momentum history rank denominator is inconsistent"
                )

            results.append(
                SectorPublishedMomentumHistorySlice(
                    batch_id=row.batch_id,
                    trade_date=row.trade_date,
                    comparison_scope=row.comparison_scope,
                    comparison_key=row.comparison_key,
                    selected_sector_code=selection.selected_sector_code,
                    selected_return_pct=row.selected_return_pct,
                    selected_strength_rank=row.selected_strength_rank,
                    selected_percentile=row.selected_percentile,
                    selected_calculation_status=row.selected_calculation_status,
                    selected_missing_reason=row.selected_missing_reason,
                    row_count=row_count,
                    calculable_count=calculable_count,
                )
            )
        return tuple(results)

    @staticmethod
    def _momentum_history_branch(
        *,
        selection: SectorMomentumHistorySelection,
        period: SectorMomentumPeriod,
    ):
        fact = WealthSectorMomentumDaily
        batch = WealthSectorAnalysisPublishBatch
        hierarchy = WealthSectorHierarchy
        expected_sector_codes = selection.expected_sector_codes
        expected_level = {
            "LEVEL_1": 1,
            "LEVEL_2": 2,
            "LEVEL_3": 3,
            "LEVEL_1_CHILDREN": 2,
            "LEVEL_2_CHILDREN": 3,
        }[selection.comparison_scope]
        expected_parent_code = (
            selection.comparison_key.rsplit(":", 1)[-1]
            if selection.comparison_scope in {"LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"}
            else None
        )
        is_calculable = fact.calculation_status == "CALCULABLE"
        is_unavailable = fact.calculation_status == "UNAVAILABLE"
        invalid_calculable = and_(
            is_calculable,
            or_(
                fact.return_pct.is_(None),
                fact.strength_rank.is_(None),
                fact.rankable_count.is_(None),
                fact.percentile.is_(None),
                fact.missing_reason != "NONE",
                fact.strength_rank < 1,
                fact.rankable_count < 1,
                fact.strength_rank > fact.rankable_count,
                fact.percentile < 0,
                fact.percentile > 100,
            ),
        )
        invalid_unavailable = and_(
            is_unavailable,
            or_(
                fact.return_pct.is_not(None),
                fact.strength_rank.is_not(None),
                fact.rankable_count.is_not(None),
                fact.percentile.is_not(None),
                fact.missing_reason == "NONE",
            ),
        )
        hierarchy_error = or_(
            hierarchy.sector_code.is_(None),
            hierarchy.baseline_version != batch.hierarchy_version,
            hierarchy.sector_name != fact.sector_name,
            hierarchy.industry_level != fact.industry_level,
            hierarchy.hierarchy_path != fact.hierarchy_path,
            fact.industry_level != expected_level,
        )
        parent_error = (
            fact.parent_sector_code.is_not(None)
            if expected_parent_code is None
            else or_(
                fact.parent_sector_code.is_(None),
                fact.parent_sector_code != expected_parent_code,
            )
        )
        selected = fact.sector_code == selection.selected_sector_code

        def count_if(predicate, label: str):  # type: ignore[no-untyped-def]
            return func.sum(case((predicate, 1), else_=0)).label(label)

        return (
            select(
                batch.batch_id.label("batch_id"),
                batch.trade_date.label("trade_date"),
                batch.hierarchy_version.label("hierarchy_version"),
                batch.formula_bundle_version.label("formula_bundle_version"),
                literal(selection.comparison_scope).label("comparison_scope"),
                literal(selection.comparison_key).label("comparison_key"),
                func.count(fact.sector_code).label("row_count"),
                func.count(func.distinct(fact.sector_code)).label(
                    "distinct_sector_count"
                ),
                count_if(
                    fact.sector_code.not_in(expected_sector_codes),
                    "unexpected_sector_count",
                ),
                count_if(hierarchy_error, "hierarchy_error_count"),
                count_if(parent_error, "parent_error_count"),
                count_if(
                    or_(
                        fact.formula_key != FORMULA_KEY,
                        fact.formula_version != FORMULA_VERSION,
                    ),
                    "formula_error_count",
                ),
                count_if(
                    or_(
                        fact.calculation_status.not_in(("CALCULABLE", "UNAVAILABLE")),
                        fact.missing_reason.is_(None),
                        invalid_calculable,
                        invalid_unavailable,
                    ),
                    "value_error_count",
                ),
                count_if(is_calculable, "calculable_count"),
                func.min(case((is_calculable, fact.rankable_count))).label(
                    "min_rankable_count"
                ),
                func.max(case((is_calculable, fact.rankable_count))).label(
                    "max_rankable_count"
                ),
                count_if(selected, "selected_count"),
                func.max(case((selected, fact.return_pct))).label(
                    "selected_return_pct"
                ),
                func.max(case((selected, fact.strength_rank))).label(
                    "selected_strength_rank"
                ),
                func.max(case((selected, fact.percentile))).label(
                    "selected_percentile"
                ),
                func.max(case((selected, fact.calculation_status))).label(
                    "selected_calculation_status"
                ),
                func.max(case((selected, fact.missing_reason))).label(
                    "selected_missing_reason"
                ),
            )
            .join(
                batch,
                and_(
                    batch.batch_id == fact.batch_id,
                    batch.trade_date == fact.trade_date,
                    batch.status == "PUBLISHED",
                ),
            )
            .outerjoin(hierarchy, hierarchy.sector_code == fact.sector_code)
            .where(
                batch.trade_date.in_(selection.trade_dates),
                fact.comparison_scope == selection.comparison_scope,
                fact.comparison_key == selection.comparison_key,
                fact.period == period,
            )
            .group_by(
                batch.batch_id,
                batch.trade_date,
                batch.hierarchy_version,
                batch.formula_bundle_version,
            )
        )

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
