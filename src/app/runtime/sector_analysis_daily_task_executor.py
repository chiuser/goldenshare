from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from sqlalchemy import select

from src.biz.services.wealth.market.sector_analysis.daily_facts import (
    FORMULA_BUNDLE_VERSION,
    TEMPLATE_VERSION,
    SectorAnalysisDailyFactsMaterializationService,
    SectorAnalysisReplayPlanner,
    SectorAnalysisReplayScope,
    SectorAnalysisReplayUnit,
    SectorAnalysisReplayGap,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    DailyFactsPreview,
    SectorAnalysisDailyFactsPlanDriftError,
    canonical_json_hash,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.biz.services.wealth.market.sector_analysis.daily_facts.source_query import (
    ensure_repeatable_read_only_transaction,
)
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenancePlanCheckpoint,
    MaintenancePlanTaskRunContext,
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
            raise RuntimeError("sector-analysis replay PLAN requires TaskRun context")
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

    def plan_for_task_run(
        self,
        request: MaintenanceExecutionRequest,
        *,
        context: MaintenancePlanTaskRunContext,
    ) -> MaintenanceExecutionPlan:
        if request.action_key != REPLAY_ACTION_KEY:
            raise ValueError("task-aware PLAN is only supported for sector-analysis replay")
        start_date = self._required_date(request.params, "start_date")
        end_date = self._required_date(request.params, "end_date")
        self._raise_if_canceled(context)
        with self._session_factory() as session:
            scope = self._replay_planner.resolve_scope(
                session,
                start_date=start_date,
                end_date=end_date,
            )
            session.rollback()
        total = len(scope.open_trade_dates)
        results: list[SectorAnalysisReplayUnit | SectorAnalysisReplayGap] = []
        context.update_phase(
            unit_done=0,
            unit_total=total,
            phase="SCOPE_RESOLVED",
            current_object=self._plan_current_object(scope.open_trade_dates[0], "SCOPE_RESOLVED"),
        )
        for trade_date in scope.open_trade_dates:
            self._raise_if_canceled(context)

            def phase_update(phase: str, *, _trade_date: date = trade_date) -> None:
                context.update_phase(
                    unit_done=len(results),
                    unit_total=total,
                    phase=phase,
                    current_object=self._plan_current_object(_trade_date, phase),
                )

            with self._session_factory() as session:
                result = self._replay_planner.preview_unit(
                    session,
                    scope=scope,
                    trade_date=trade_date,
                    cancel_check=lambda: self._raise_if_canceled(context),
                    phase_update=phase_update,
                )
                session.rollback()
            self._raise_if_canceled(context)
            results.append(result)
            units = self._maintenance_units(scope=scope, results=tuple(results))
            gaps = self._gap_payloads(tuple(results))
            context.save_checkpoint(
                MaintenancePlanCheckpoint(
                    unit_done=len(results),
                    unit_total=total,
                    units=units,
                    gaps=gaps,
                    metadata=self._replay_metadata(
                        requested_start_date=start_date,
                        scope=scope,
                        warmup_start_date=self._first_warmup(tuple(results)),
                        gaps=gaps,
                    ),
                    expected_rows=self._expected_rows_max(tuple(results)),
                    phase="CHECKPOINT_SAVED",
                    current_object=self._plan_current_object(trade_date, "CHECKPOINT_SAVED"),
                )
            )
            self._raise_if_canceled(context)

        context.update_phase(
            unit_done=total,
            unit_total=total,
            phase="FINAL_SCOPE_CHECK",
            current_object=self._plan_current_object(scope.open_trade_dates[-1], "FINAL_SCOPE_CHECK"),
        )
        self._raise_if_canceled(context)
        with self._session_factory() as session:
            final_scope = self._replay_planner.resolve_scope(
                session,
                start_date=start_date,
                end_date=end_date,
            )
            session.rollback()
        if final_scope != scope:
            raise SectorAnalysisDailyFactsPlanDriftError(
                "回补PLAN最终交易日清单或层级身份已偏离初始范围"
            )
        self._raise_if_canceled(context)
        replay = self._replay_planner.finalize(scope=scope, results=tuple(results))
        return self._to_maintenance_plan(
            replay=replay,
            requested_start_date=start_date,
        )

    @staticmethod
    def _to_maintenance_plan(
        *,
        replay,  # type: ignore[no-untyped-def]
        requested_start_date: date,
    ) -> MaintenanceExecutionPlan:
        scope = SectorAnalysisReplayScope(
            requested_start_date=requested_start_date,
            start_date=replay.start_date,
            end_date=replay.end_date,
            open_trade_dates=replay.open_trade_dates,
            hierarchy_version=str(replay.hierarchy_version or ""),
        )
        units = SectorAnalysisDailyTaskExecutor._maintenance_units(
            scope=scope,
            results=tuple(replay.units),
        )
        gaps = SectorAnalysisDailyTaskExecutor._gap_payloads(tuple(replay.gaps))
        metadata = SectorAnalysisDailyTaskExecutor._replay_metadata(
            requested_start_date=requested_start_date,
            scope=scope,
            warmup_start_date=replay.warmup_start_date,
            gaps=gaps,
        )
        metadata.update(
            {
                "expected_rows_min": replay.expected_rows_min,
                "expected_rows_max": replay.expected_rows_max,
            }
        )
        return MaintenanceExecutionPlan(
            plan_hash=replay.plan_hash,
            units=units,
            apply_ready=replay.apply_ready,
            expected_rows=replay.expected_rows_max,
            metadata=metadata,
        )

    @staticmethod
    def _maintenance_units(
        *,
        scope: SectorAnalysisReplayScope,
        results: tuple[SectorAnalysisReplayUnit | SectorAnalysisReplayGap, ...],
    ) -> tuple[MaintenanceExecutionUnit, ...]:
        target_dates_hash = canonical_json_hash(scope.open_trade_dates)
        units = tuple(
            MaintenanceExecutionUnit(
                unit_key=f"wealth-sector-analysis-daily:{unit.trade_date.isoformat()}",
                payload={
                    "replay_unit": True,
                    "validate_replay_scope": index == 0,
                    "trade_date": unit.trade_date.isoformat(),
                    "replay_start_date": scope.start_date.isoformat(),
                    "replay_end_date": scope.end_date.isoformat(),
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
            for index, unit in enumerate(
                item for item in results if isinstance(item, SectorAnalysisReplayUnit)
            )
        )
        return units

    @staticmethod
    def _gap_payloads(
        results: tuple[SectorAnalysisReplayUnit | SectorAnalysisReplayGap, ...],
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            {
                "trade_date": gap.trade_date.isoformat(),
                "reason_code": gap.reason_code,
                "message": gap.message,
            }
            for gap in results
            if isinstance(gap, SectorAnalysisReplayGap)
        )

    @staticmethod
    def _replay_metadata(
        *,
        requested_start_date: date,
        scope: SectorAnalysisReplayScope,
        warmup_start_date: date | None,
        gaps: tuple[Mapping[str, Any], ...],
    ) -> dict[str, Any]:
        return {
            "requested_start_date": requested_start_date.isoformat(),
            "start_date": scope.start_date.isoformat(),
            "end_date": scope.end_date.isoformat(),
            "warmup_start_date": warmup_start_date.isoformat() if warmup_start_date else None,
            "open_trade_dates": [item.isoformat() for item in scope.open_trade_dates],
            "target_dates_hash": canonical_json_hash(scope.open_trade_dates),
            "hierarchy_version": scope.hierarchy_version,
            "formula_bundle_version": FORMULA_BUNDLE_VERSION,
            "template_version": TEMPLATE_VERSION,
            "gaps": [dict(gap) for gap in gaps],
        }

    @staticmethod
    def _first_warmup(
        results: tuple[SectorAnalysisReplayUnit | SectorAnalysisReplayGap, ...],
    ) -> date | None:
        return next(
            (
                item.warmup_start_date
                for item in results
                if isinstance(item, SectorAnalysisReplayUnit) and item.warmup_start_date is not None
            ),
            None,
        )

    @staticmethod
    def _expected_rows_max(
        results: tuple[SectorAnalysisReplayUnit | SectorAnalysisReplayGap, ...],
    ) -> int:
        return sum(
            maximum
            for item in results
            if isinstance(item, SectorAnalysisReplayUnit)
            for _minimum, maximum in item.expected_fact_count_ranges.values()
        )

    @staticmethod
    def _plan_current_object(trade_date: date, phase: str) -> dict[str, Any]:
        return {
            "entity": {"type": "trade_date", "value": trade_date.isoformat()},
            "time": {"trade_date": trade_date.isoformat()},
            "attributes": {"phase": phase},
        }

    @staticmethod
    def _raise_if_canceled(context: MaintenancePlanTaskRunContext) -> None:
        if context.is_cancel_requested():
            raise IngestionCanceledError("sector-analysis replay PLAN cancellation requested")

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
        ensure_repeatable_read_only_transaction(session)
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
