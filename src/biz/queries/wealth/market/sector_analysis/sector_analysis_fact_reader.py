from __future__ import annotations

from dataclasses import dataclass
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
from src.foundation.models.core_serving.wealth_sector_hierarchy import (
    WealthSectorHierarchy,
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
