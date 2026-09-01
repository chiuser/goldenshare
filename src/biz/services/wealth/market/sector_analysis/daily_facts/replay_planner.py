from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.biz.queries.wealth.market.common.sector_hierarchy_query import SectorHierarchyQuery

from .contract import (
    FORMULA_BUNDLE_VERSION,
    TEMPLATE_VERSION,
    DailyFactsPreview,
    SectorAnalysisDailyFactsSourceNotReadyError,
    canonical_json_hash,
)
from .materialization_service import SectorAnalysisDailyFactsMaterializationService
from .source_query import ensure_repeatable_read_only_transaction


MIN_PUBLISH_DATE = date(2025, 1, 1)
INSIGHT_ITEM_MAX_PER_SECTOR = 2


@dataclass(frozen=True, slots=True)
class SectorAnalysisReplayUnit:
    trade_date: date
    hierarchy_version: str
    source_hash: str
    source_dates: Mapping[str, str]
    source_row_counts: Mapping[str, int]
    expected_fact_count_ranges: Mapping[str, tuple[int, int]]
    warmup_start_date: date | None


@dataclass(frozen=True, slots=True)
class SectorAnalysisReplayGap:
    trade_date: date
    reason_code: str
    message: str


@dataclass(frozen=True, slots=True)
class SectorAnalysisReplayPlan:
    start_date: date
    end_date: date
    warmup_start_date: date | None
    open_trade_dates: tuple[date, ...]
    units: tuple[SectorAnalysisReplayUnit, ...]
    gaps: tuple[SectorAnalysisReplayGap, ...]
    hierarchy_version: str | None
    apply_ready: bool
    plan_hash: str
    expected_rows_min: int
    expected_rows_max: int


@dataclass(frozen=True, slots=True)
class SectorAnalysisReplayScope:
    requested_start_date: date
    start_date: date
    end_date: date
    open_trade_dates: tuple[date, ...]
    hierarchy_version: str


class SectorAnalysisReplayPlanner:
    def __init__(
        self,
        materialization_service: SectorAnalysisDailyFactsMaterializationService | None = None,
        hierarchy_query: SectorHierarchyQuery | None = None,
    ) -> None:
        self._materialization_service = (
            materialization_service or SectorAnalysisDailyFactsMaterializationService()
        )
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()

    def resolve_scope(
        self,
        session: Session,
        *,
        start_date: date,
        end_date: date,
    ) -> SectorAnalysisReplayScope:
        if start_date > end_date:
            raise ValueError("start_date must not be later than end_date")
        ensure_repeatable_read_only_transaction(session)
        requested_floor = max(start_date, MIN_PUBLISH_DATE)
        open_trade_dates = tuple(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date >= requested_floor,
                    TradeCalendar.trade_date <= end_date,
                )
                .order_by(TradeCalendar.trade_date)
            )
        )
        if not open_trade_dates:
            raise ValueError("replay PLAN has no SSE open trade dates")
        hierarchy = self._hierarchy_query.load(session)
        return SectorAnalysisReplayScope(
            requested_start_date=start_date,
            start_date=open_trade_dates[0],
            end_date=end_date,
            open_trade_dates=open_trade_dates,
            hierarchy_version=hierarchy.baseline_version,
        )

    def preview_unit(
        self,
        session: Session,
        *,
        scope: SectorAnalysisReplayScope,
        trade_date: date,
        cancel_check: Callable[[], None] | None = None,
        phase_update: Callable[[str], None] | None = None,
    ) -> SectorAnalysisReplayUnit | SectorAnalysisReplayGap:
        if trade_date not in scope.open_trade_dates:
            raise ValueError("replay trade_date is outside the frozen scope")
        ensure_repeatable_read_only_transaction(session)
        try:
            preview = self._materialization_service.preview_trade_date(
                session,
                trade_date=trade_date,
                cancel_check=cancel_check,
                phase_update=phase_update,
            )
        except SectorAnalysisDailyFactsSourceNotReadyError as exc:
            return SectorAnalysisReplayGap(
                trade_date=trade_date,
                reason_code=exc.code,
                message=str(exc),
            )
        if preview.hierarchy_version != scope.hierarchy_version:
            return SectorAnalysisReplayGap(
                trade_date=trade_date,
                reason_code="SA_DAILY_FACT_PLAN_DRIFT",
                message=(
                    "回补窗口内层级版本不唯一："
                    f"expected={scope.hierarchy_version}, actual={preview.hierarchy_version}"
                ),
            )
        return SectorAnalysisReplayUnit(
            trade_date=trade_date,
            hierarchy_version=preview.hierarchy_version,
            source_hash=preview.source_hash,
            source_dates=dict(preview.source_dates),
            source_row_counts=dict(preview.source_row_counts),
            expected_fact_count_ranges=self._fact_count_ranges(preview),
            warmup_start_date=self._warmup_start(preview),
        )

    def finalize(
        self,
        *,
        scope: SectorAnalysisReplayScope,
        results: tuple[SectorAnalysisReplayUnit | SectorAnalysisReplayGap, ...],
    ) -> SectorAnalysisReplayPlan:
        if tuple(item.trade_date for item in results) != scope.open_trade_dates:
            raise ValueError("replay results do not cover the frozen scope in order")
        units = tuple(item for item in results if isinstance(item, SectorAnalysisReplayUnit))
        gaps = tuple(item for item in results if isinstance(item, SectorAnalysisReplayGap))
        warmup_start_date = next(
            (item.warmup_start_date for item in units if item.warmup_start_date is not None),
            None,
        )

        plan_payload = {
            "startDate": scope.start_date,
            "endDate": scope.end_date,
            "warmupStartDate": warmup_start_date,
            "openTradeDates": scope.open_trade_dates,
            "hierarchyVersion": scope.hierarchy_version,
            "formulaBundleVersion": FORMULA_BUNDLE_VERSION,
            "templateVersion": TEMPLATE_VERSION,
            "units": [self._unit_payload(unit) for unit in units],
            "gaps": [
                {
                    "tradeDate": gap.trade_date,
                    "reasonCode": gap.reason_code,
                    "message": gap.message,
                }
                for gap in gaps
            ],
        }
        expected_rows_min = sum(
            minimum
            for unit in units
            for minimum, _maximum in unit.expected_fact_count_ranges.values()
        )
        expected_rows_max = sum(
            maximum
            for unit in units
            for _minimum, maximum in unit.expected_fact_count_ranges.values()
        )
        return SectorAnalysisReplayPlan(
            start_date=scope.start_date,
            end_date=scope.end_date,
            warmup_start_date=warmup_start_date,
            open_trade_dates=scope.open_trade_dates,
            units=units,
            gaps=gaps,
            hierarchy_version=scope.hierarchy_version,
            apply_ready=(
                not gaps
                and len(units) == len(scope.open_trade_dates)
            ),
            plan_hash=canonical_json_hash(plan_payload),
            expected_rows_min=expected_rows_min,
            expected_rows_max=expected_rows_max,
        )

    @staticmethod
    def _fact_count_ranges(preview: DailyFactsPreview) -> dict[str, tuple[int, int]]:
        hierarchy_count = int(preview.source_row_counts.get("wealth_sector_hierarchy") or 0)
        ranges = {
            table: (int(count), int(count))
            for table, count in preview.expected_fact_counts.items()
        }
        ranges["wealth_sector_daily_insight_item"] = (
            0,
            hierarchy_count * INSIGHT_ITEM_MAX_PER_SECTOR,
        )
        return ranges

    @staticmethod
    def _warmup_start(preview: DailyFactsPreview) -> date | None:
        raw_range = str(preview.source_dates.get("trade_calendar") or "")
        raw_start = raw_range.split("..", 1)[0].strip()
        if not raw_start:
            return None
        return date.fromisoformat(raw_start)

    @staticmethod
    def _unit_payload(unit: SectorAnalysisReplayUnit) -> dict[str, object]:
        return {
            "tradeDate": unit.trade_date,
            "hierarchyVersion": unit.hierarchy_version,
            "sourceHash": unit.source_hash,
            "sourceDates": dict(unit.source_dates),
            "sourceRowCounts": dict(unit.source_row_counts),
            "expectedFactCountRanges": {
                table: {"min": bounds[0], "max": bounds[1]}
                for table, bounds in sorted(unit.expected_fact_count_ranges.items())
            },
        }
