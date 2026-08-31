from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from sqlalchemy import select

from src.biz.services.wealth.market.sector_analysis.daily_facts import (
    FORMULA_BUNDLE_VERSION,
    TEMPLATE_VERSION,
    SectorAnalysisDailyFactsMaterializationService,
    SectorAnalysisReplayPlanner,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    DailyFactsPreview,
    SectorAnalysisDailyFactsPlanDriftError,
    canonical_json_hash,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)


DAILY_ACTION_KEY = "maintenance.materialize_wealth_sector_analysis_daily"
REPLAY_ACTION_KEY = "maintenance.replay_wealth_sector_analysis_history"


class SectorAnalysisDailyTaskExecutor:
    def __init__(
        self,
        *,
        session_factory,  # type: ignore[no-untyped-def]
        materialization_service: SectorAnalysisDailyFactsMaterializationService | None = None,
        replay_planner: SectorAnalysisReplayPlanner | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._service = materialization_service or SectorAnalysisDailyFactsMaterializationService(
            session_factory=session_factory
        )
        self._replay_planner = replay_planner or SectorAnalysisReplayPlanner(self._service)

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        if request.action_key == REPLAY_ACTION_KEY:
            return self._plan_replay(request)
        if request.action_key != DAILY_ACTION_KEY:
            raise ValueError(f"unsupported sector-analysis action: {request.action_key}")
        trade_date = self._required_date(request.params, "trade_date")
        with self._session_factory() as session:
            preview = self._service.preview_trade_date(session, trade_date=trade_date)
            session.rollback()
        readiness = request.params.get("readiness")
        if isinstance(readiness, Mapping):
            expected = (
                readiness.get("sourceHash"),
                readiness.get("planHash"),
                readiness.get("contentHash"),
            )
            actual = (preview.source_hash, preview.plan_hash, preview.content_hash)
            if any(value not in (None, "") for value in expected) and tuple(
                None if value in (None, "") else str(value) for value in expected
            ) != actual:
                raise SectorAnalysisDailyFactsPlanDriftError(
                    "scheduler readiness与executor plan不一致"
                )
        unit = MaintenanceExecutionUnit(
            unit_key=f"wealth-sector-analysis-daily:{trade_date.isoformat()}",
            payload={
                "trade_date": trade_date.isoformat(),
                "expected_source_hash": preview.source_hash,
                "expected_plan_hash": preview.plan_hash,
                "expected_content_hash": preview.content_hash,
                "expected_fact_counts": dict(preview.expected_fact_counts),
            },
        )
        return MaintenanceExecutionPlan(
            plan_hash=canonical_json_hash(
                {
                    "actionKey": request.action_key,
                    "unitKey": unit.unit_key,
                    "payload": dict(unit.payload),
                }
            ),
            units=(unit,),
            expected_rows=sum(preview.expected_fact_counts.values()),
            metadata={
                "trade_date": trade_date.isoformat(),
                "hierarchy_version": preview.hierarchy_version,
                "source_hash": preview.source_hash,
                "content_hash": preview.content_hash,
            },
        )

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        trade_date = self._required_date(unit.payload, "trade_date")
        if unit.payload.get("replay_unit") is True:
            with self._session_factory() as session:
                if unit.payload.get("validate_replay_scope") is True:
                    self._validate_replay_scope(session, unit.payload)
                preview = self._service.preview_trade_date(session, trade_date=trade_date)
                self._validate_replay_preview(preview, unit.payload)
                session.rollback()
            expected_source_hash = self._required_text(unit.payload, "expected_source_hash")
            expected_plan_hash = preview.plan_hash
            expected_content_hash = preview.content_hash
        else:
            expected_source_hash = self._required_text(unit.payload, "expected_source_hash")
            expected_plan_hash = self._required_text(unit.payload, "expected_plan_hash")
            expected_content_hash = self._required_text(unit.payload, "expected_content_hash")
        result = self._service.materialize_trade_date(
            trade_date=trade_date,
            expected_source_hash=expected_source_hash,
            expected_plan_hash=expected_plan_hash,
            expected_content_hash=expected_content_hash,
        )
        return MaintenanceExecutionResult(
            rows_fetched=result.rows_saved,
            rows_saved=result.rows_saved,
            summary_message=(
                f"板块分析每日事实 {trade_date.isoformat()} "
                f"{'幂等跳过' if result.idempotent else '已发布'}：rows={result.rows_saved}"
            ),
            metadata={
                "trade_date": trade_date.isoformat(),
                "batch_id": str(result.batch_id) if result.batch_id else None,
                "plan_hash": result.plan_hash,
                "content_hash": result.content_hash,
                "idempotent": result.idempotent,
            },
        )

    def _plan_replay(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        start_date = self._required_date(request.params, "start_date")
        end_date = self._required_date(request.params, "end_date")
        with self._session_factory() as session:
            replay = self._replay_planner.plan(
                session,
                start_date=start_date,
                end_date=end_date,
            )
            session.rollback()
        target_dates_hash = canonical_json_hash(replay.open_trade_dates)
        units = tuple(
            MaintenanceExecutionUnit(
                unit_key=f"wealth-sector-analysis-daily:{unit.trade_date.isoformat()}",
                payload={
                    "replay_unit": True,
                    "validate_replay_scope": index == 0,
                    "trade_date": unit.trade_date.isoformat(),
                    "replay_start_date": replay.start_date.isoformat(),
                    "replay_end_date": replay.end_date.isoformat(),
                    "target_dates_hash": target_dates_hash,
                    "expected_hierarchy_version": unit.hierarchy_version,
                    "expected_formula_bundle_version": FORMULA_BUNDLE_VERSION,
                    "expected_template_version": TEMPLATE_VERSION,
                    "expected_source_hash": unit.source_hash,
                    "expected_source_dates": dict(unit.source_dates),
                    "expected_source_row_counts": dict(unit.source_row_counts),
                    "expected_fact_count_ranges": {
                        table: {"min": bounds[0], "max": bounds[1]}
                        for table, bounds in sorted(unit.expected_fact_count_ranges.items())
                    },
                },
            )
            for index, unit in enumerate(replay.units)
        )
        return MaintenanceExecutionPlan(
            plan_hash=replay.plan_hash,
            units=units,
            apply_ready=replay.apply_ready,
            expected_rows=replay.expected_rows_max,
            metadata={
                "requested_start_date": start_date.isoformat(),
                "start_date": replay.start_date.isoformat(),
                "end_date": replay.end_date.isoformat(),
                "warmup_start_date": (
                    replay.warmup_start_date.isoformat()
                    if replay.warmup_start_date is not None
                    else None
                ),
                "open_trade_dates": [item.isoformat() for item in replay.open_trade_dates],
                "target_dates_hash": target_dates_hash,
                "hierarchy_version": replay.hierarchy_version,
                "formula_bundle_version": FORMULA_BUNDLE_VERSION,
                "template_version": TEMPLATE_VERSION,
                "expected_rows_min": replay.expected_rows_min,
                "expected_rows_max": replay.expected_rows_max,
                "gaps": [
                    {
                        "trade_date": gap.trade_date.isoformat(),
                        "reason_code": gap.reason_code,
                        "message": gap.message,
                    }
                    for gap in replay.gaps
                ],
            },
        )

    @staticmethod
    def _validate_replay_preview(
        preview: DailyFactsPreview,
        payload: Mapping[str, Any],
    ) -> None:
        expected_identity = (
            str(payload.get("expected_hierarchy_version") or ""),
            str(payload.get("expected_formula_bundle_version") or ""),
            str(payload.get("expected_template_version") or ""),
            str(payload.get("expected_source_hash") or ""),
        )
        actual_identity = (
            preview.hierarchy_version,
            FORMULA_BUNDLE_VERSION,
            TEMPLATE_VERSION,
            preview.source_hash,
        )
        if expected_identity != actual_identity:
            raise SectorAnalysisDailyFactsPlanDriftError(
                "回补APPLY的层级、公式、模板或来源hash已偏离冻结PLAN"
            )
        if dict(payload.get("expected_source_dates") or {}) != dict(preview.source_dates):
            raise SectorAnalysisDailyFactsPlanDriftError("回补APPLY的来源日期证据已偏离冻结PLAN")
        if dict(payload.get("expected_source_row_counts") or {}) != dict(preview.source_row_counts):
            raise SectorAnalysisDailyFactsPlanDriftError("回补APPLY的来源行数证据已偏离冻结PLAN")
        raw_ranges = payload.get("expected_fact_count_ranges")
        if not isinstance(raw_ranges, Mapping) or set(raw_ranges) != set(preview.expected_fact_counts):
            raise SectorAnalysisDailyFactsPlanDriftError("回补APPLY的事实表计数范围非法")
        for table, actual in preview.expected_fact_counts.items():
            bounds = raw_ranges.get(table)
            if not isinstance(bounds, Mapping):
                raise SectorAnalysisDailyFactsPlanDriftError("回补APPLY的事实表计数范围非法")
            try:
                minimum = int(bounds["min"])
                maximum = int(bounds["max"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SectorAnalysisDailyFactsPlanDriftError(
                    "回补APPLY的事实表计数范围非法"
                ) from exc
            if minimum < 0 or maximum < minimum or not minimum <= int(actual) <= maximum:
                raise SectorAnalysisDailyFactsPlanDriftError(
                    f"回补APPLY的{table}行数超出冻结PLAN范围"
                )

    @staticmethod
    def _validate_replay_scope(session, payload: Mapping[str, Any]) -> None:  # type: ignore[no-untyped-def]
        start_date = SectorAnalysisDailyTaskExecutor._required_date(payload, "replay_start_date")
        end_date = SectorAnalysisDailyTaskExecutor._required_date(payload, "replay_end_date")
        current_dates = tuple(
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
        if canonical_json_hash(current_dates) != str(payload.get("target_dates_hash") or ""):
            raise SectorAnalysisDailyFactsPlanDriftError("回补APPLY的SSE交易日清单已偏离冻结PLAN")

    @staticmethod
    def _required_date(values: Mapping[str, Any], key: str) -> date:
        value = values.get(key)
        if isinstance(value, date):
            return value
        if value in (None, ""):
            raise ValueError(f"{key} is required")
        return date.fromisoformat(str(value))

    @staticmethod
    def _required_text(values: Mapping[str, Any], key: str) -> str:
        value = str(values.get(key) or "").strip()
        if not value:
            raise ValueError(f"{key} is required")
        return value
