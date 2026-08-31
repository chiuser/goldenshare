from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar

from .contract import (
    FORMULA_BUNDLE_VERSION,
    TEMPLATE_VERSION,
    DailyFactsPreview,
    SectorAnalysisDailyFactsSourceNotReadyError,
    canonical_json_hash,
)
from .materialization_service import SectorAnalysisDailyFactsMaterializationService


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


class SectorAnalysisReplayPlanner:
    def __init__(
        self,
        materialization_service: SectorAnalysisDailyFactsMaterializationService | None = None,
    ) -> None:
        self._materialization_service = (
            materialization_service or SectorAnalysisDailyFactsMaterializationService()
        )

    def plan(
        self,
        session: Session,
        *,
        start_date: date,
        end_date: date,
    ) -> SectorAnalysisReplayPlan:
        if start_date > end_date:
            raise ValueError("start_date must not be later than end_date")
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
        effective_start = open_trade_dates[0]

        units: list[SectorAnalysisReplayUnit] = []
        gaps: list[SectorAnalysisReplayGap] = []
        hierarchy_version: str | None = None
        warmup_start_date: date | None = None
        for trade_date in open_trade_dates:
            try:
                preview = self._materialization_service.preview_trade_date(
                    session,
                    trade_date=trade_date,
                )
            except SectorAnalysisDailyFactsSourceNotReadyError as exc:
                gaps.append(
                    SectorAnalysisReplayGap(
                        trade_date=trade_date,
                        reason_code=exc.code,
                        message=str(exc),
                    )
                )
                continue
            if hierarchy_version is None:
                hierarchy_version = preview.hierarchy_version
            elif preview.hierarchy_version != hierarchy_version:
                gaps.append(
                    SectorAnalysisReplayGap(
                        trade_date=trade_date,
                        reason_code="SA_DAILY_FACT_PLAN_DRIFT",
                        message=(
                            "回补窗口内层级版本不唯一："
                            f"expected={hierarchy_version}, actual={preview.hierarchy_version}"
                        ),
                    )
                )
                continue
            if warmup_start_date is None:
                warmup_start_date = self._warmup_start(preview)
            units.append(
                SectorAnalysisReplayUnit(
                    trade_date=trade_date,
                    hierarchy_version=preview.hierarchy_version,
                    source_hash=preview.source_hash,
                    source_dates=dict(preview.source_dates),
                    source_row_counts=dict(preview.source_row_counts),
                    expected_fact_count_ranges=self._fact_count_ranges(preview),
                )
            )

        plan_payload = {
            "startDate": effective_start,
            "endDate": end_date,
            "warmupStartDate": warmup_start_date,
            "openTradeDates": open_trade_dates,
            "hierarchyVersion": hierarchy_version,
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
            start_date=effective_start,
            end_date=end_date,
            warmup_start_date=warmup_start_date,
            open_trade_dates=open_trade_dates,
            units=tuple(units),
            gaps=tuple(gaps),
            hierarchy_version=hierarchy_version,
            apply_ready=(
                not gaps
                and hierarchy_version is not None
                and len(units) == len(open_trade_dates)
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
