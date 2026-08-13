from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar

from .sector_heat_config import canonical_json_hash
from .sector_heat_contract import PriorPublishedHeat
from .sector_heat_materialization_service import SectorHeatMaterializationService
from .sector_heat_source_query import SectorHeatSourceNotReadyError, SourceCompletionEvidence


@dataclass(frozen=True, slots=True)
class SectorHeatReplayUnit:
    trade_date: date
    plan_hash: str
    content_hash: str
    config_version: str
    score_version: str
    config_hash: str
    source_hash: str
    expected_rows: int
    expected_valid_count: int
    expected_invalid_count: int
    source_dates: Mapping[str, object]
    source_row_counts: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SectorHeatReplayGap:
    trade_date: date
    reason_code: str
    message: str


@dataclass(frozen=True, slots=True)
class SectorHeatReplayPlan:
    start_date: date
    end_date: date
    open_trade_dates: tuple[date, ...]
    units: tuple[SectorHeatReplayUnit, ...]
    gaps: tuple[SectorHeatReplayGap, ...]
    apply_ready: bool
    plan_hash: str
    expected_rows: int


class SectorHeatReplayPlanner:
    def __init__(self, materialization_service: SectorHeatMaterializationService | None = None) -> None:
        self._materialization_service = materialization_service or SectorHeatMaterializationService()

    def plan(
        self,
        session: Session,
        *,
        start_date: date,
        end_date: date,
        completion_evidence: Sequence[SourceCompletionEvidence] = (),
    ) -> SectorHeatReplayPlan:
        if start_date > end_date:
            raise ValueError("start_date must not be later than end_date")
        open_trade_dates = tuple(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date >= start_date,
                    TradeCalendar.trade_date <= end_date,
                )
                .order_by(TradeCalendar.trade_date)
            )
        )
        if len(open_trade_dates) < 60:
            raise ValueError(f"replay PLAN requires at least 60 open trade dates, got {len(open_trade_dates)}")

        units: list[SectorHeatReplayUnit] = []
        gaps: list[SectorHeatReplayGap] = []
        simulated_history: dict[date, dict[str, PriorPublishedHeat]] = {}
        chain_blocked = False
        for trade_date in open_trade_dates:
            if chain_blocked:
                gaps.append(
                    SectorHeatReplayGap(
                        trade_date=trade_date,
                        reason_code="PREDECESSOR_GAP",
                        message="an earlier replay date is not ready, so derived previous-Heat lineage cannot be frozen",
                    )
                )
                continue
            try:
                preview = self._materialization_service.preview_trade_date(
                    session,
                    trade_date=trade_date,
                    completion_evidence=completion_evidence,
                    prior_published_override=simulated_history or None,
                )
            except SectorHeatSourceNotReadyError as exc:
                gaps.append(
                    SectorHeatReplayGap(
                        trade_date=trade_date,
                        reason_code="SOURCE_NOT_READY",
                        message=str(exc),
                    )
                )
                chain_blocked = True
                continue
            units.append(
                SectorHeatReplayUnit(
                    trade_date=trade_date,
                    plan_hash=preview.plan_hash,
                    content_hash=preview.content_hash,
                    config_version=preview.config_version,
                    score_version=preview.score_version,
                    config_hash=preview.config_hash,
                    source_hash=preview.source_hash,
                    expected_rows=preview.rows_written,
                    expected_valid_count=preview.valid_count,
                    expected_invalid_count=preview.invalid_count,
                    source_dates=dict(preview.source_dates),
                    source_row_counts=dict(preview.source_row_counts),
                )
            )
            simulated_history[trade_date] = dict(preview.published_by_code)

        plan_payload = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "openTradeDates": [item.isoformat() for item in open_trade_dates],
            "units": [
                {
                    "tradeDate": unit.trade_date.isoformat(),
                    "planHash": unit.plan_hash,
                    "contentHash": unit.content_hash,
                    "configVersion": unit.config_version,
                    "scoreVersion": unit.score_version,
                    "configHash": unit.config_hash,
                    "sourceHash": unit.source_hash,
                    "expectedRows": unit.expected_rows,
                    "expectedValidCount": unit.expected_valid_count,
                    "expectedInvalidCount": unit.expected_invalid_count,
                    "sourceDates": dict(unit.source_dates),
                    "sourceRowCounts": dict(unit.source_row_counts),
                }
                for unit in units
            ],
            "gaps": [
                {
                    "tradeDate": gap.trade_date.isoformat(),
                    "reasonCode": gap.reason_code,
                    "message": gap.message,
                }
                for gap in gaps
            ],
        }
        return SectorHeatReplayPlan(
            start_date=start_date,
            end_date=end_date,
            open_trade_dates=open_trade_dates,
            units=tuple(units),
            gaps=tuple(gaps),
            apply_ready=not gaps and len(units) == len(open_trade_dates),
            plan_hash=canonical_json_hash(plan_payload),
            expected_rows=sum(unit.expected_rows for unit in units),
        )
