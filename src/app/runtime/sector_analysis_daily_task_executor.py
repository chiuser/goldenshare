from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping

from src.biz.services.wealth.market.sector_analysis.daily_facts import (
    FORMULA_BUNDLE_VERSION,
    HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
    TEMPLATE_VERSION,
    SectorAnalysisDailyFactsMaterializationService,
    SectorAnalysisHistoryInputAuditor,
    SectorAnalysisReplayPlanner,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    SectorAnalysisDailyFactsPlanDriftError,
    canonical_json_hash,
)
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
    MaintenanceInputAuditTaskRunContext,
    MaintenanceTaskRunContext,
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
        history_input_auditor: SectorAnalysisHistoryInputAuditor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._service = materialization_service or SectorAnalysisDailyFactsMaterializationService(
            session_factory=session_factory
        )
        self._replay_planner = replay_planner or SectorAnalysisReplayPlanner()
        self._history_input_auditor = (
            history_input_auditor or SectorAnalysisHistoryInputAuditor()
        )

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        if request.action_key == REPLAY_ACTION_KEY:
            raise RuntimeError("sector-analysis history requires input audit context")
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

    def audit_for_task_run(
        self,
        request: MaintenanceExecutionRequest,
        *,
        context: MaintenanceInputAuditTaskRunContext,
    ) -> MaintenanceExecutionPlan:
        if request.action_key != REPLAY_ACTION_KEY:
            raise ValueError("input audit is only supported for sector-analysis history")
        self._validate_history_request(request.params)
        start_date = self._required_date(request.params, "start_date")
        end_date = self._required_date(request.params, "end_date")
        self._raise_if_audit_canceled(context)

        def progress_update(done: int, total: int, item: str) -> None:
            context.update_audit_phase(
                audit_done=done,
                audit_total=total,
                phase="AUDITING_INPUT",
                current_object={
                    "entity": {"type": "source", "value": item},
                    "attributes": {
                        "phase": "AUDITING_INPUT",
                        "auditDone": done,
                        "auditTotal": total,
                    },
                },
            )

        with self._session_factory() as session:
            audit = self._history_input_auditor.audit(
                session,
                start_date=start_date,
                end_date=end_date,
                cancel_check=lambda: self._raise_if_audit_canceled(context),
                progress_update=progress_update,
            )
            session.rollback()
        self._raise_if_audit_canceled(context)
        units = tuple(
            MaintenanceExecutionUnit(
                unit_key=f"wealth-sector-analysis-daily:{trade_date.isoformat()}",
                payload={
                    "replay_unit": True,
                    "validate_replay_scope": index == 1,
                    "trade_date": trade_date.isoformat(),
                    "replay_start_date": (
                        audit.effective_start_date.isoformat()
                        if audit.effective_start_date
                        else None
                    ),
                    "replay_end_date": (
                        audit.effective_end_date.isoformat()
                        if audit.effective_end_date
                        else None
                    ),
                    "target_dates_hash": canonical_json_hash(audit.ordered_trade_dates),
                    "expected_hierarchy_version": audit.hierarchy_version,
                    "expected_formula_bundle_version": FORMULA_BUNDLE_VERSION,
                    "expected_template_version": TEMPLATE_VERSION,
                    "audit_contract_version": HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
                    "audit_hash": audit.audit_hash,
                    "unit_index": index,
                    "unit_total": len(audit.ordered_trade_dates),
                },
            )
            for index, trade_date in enumerate(audit.ordered_trade_dates, start=1)
        )
        return MaintenanceExecutionPlan(
            plan_hash=audit.audit_hash,
            units=units,
            apply_ready=audit.apply_ready,
            expected_rows=0,
            metadata=audit.metadata(),
        )

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        return self._execute_unit(unit, context=None)

    def execute_unit_for_task_run(
        self,
        unit: MaintenanceExecutionUnit,
        *,
        context: MaintenanceTaskRunContext,
    ) -> MaintenanceExecutionResult:
        return self._execute_unit(unit, context=context)

    def _execute_unit(
        self,
        unit: MaintenanceExecutionUnit,
        *,
        context: MaintenanceTaskRunContext | None,
    ) -> MaintenanceExecutionResult:
        trade_date = self._required_date(unit.payload, "trade_date")
        if unit.payload.get("replay_unit") is True:
            self._validate_history_unit_contract(unit.payload)
            cancel_check = (
                (lambda: self._raise_if_execution_canceled(context))
                if context is not None
                else None
            )
            if unit.payload.get("validate_replay_scope") is True:
                self._validate_replay_scope(unit.payload, cancel_check=cancel_check)
            phase_update = (
                (lambda phase: self._update_apply_phase(context, unit.payload, phase))
                if context is not None
                else None
            )
            result = self._service.materialize_trade_date(
                trade_date=trade_date,
                expected_hierarchy_version=self._required_text(
                    unit.payload, "expected_hierarchy_version"
                ),
                cancel_check=cancel_check,
                phase_update=phase_update,
            )
        else:
            result = self._service.materialize_trade_date(
                trade_date=trade_date,
                expected_source_hash=self._required_text(
                    unit.payload, "expected_source_hash"
                ),
                expected_plan_hash=self._required_text(
                    unit.payload, "expected_plan_hash"
                ),
                expected_content_hash=self._required_text(
                    unit.payload, "expected_content_hash"
                ),
            )
        return MaintenanceExecutionResult(
            rows_fetched=result.rows_saved,
            rows_saved=result.rows_saved,
            summary_message=(
                f"板块分析每日事实 {trade_date.isoformat()} "
                f"{'幂等核验' if result.idempotent else '已发布'}：rows={result.rows_saved}"
            ),
            metadata={
                "trade_date": trade_date.isoformat(),
                "batch_id": str(result.batch_id) if result.batch_id else None,
                "plan_hash": result.plan_hash,
                "content_hash": result.content_hash,
                "idempotent": result.idempotent,
                "phase": "READBACK_COMPLETE",
            },
        )

    def _validate_replay_scope(
        self,
        payload: Mapping[str, Any],
        *,
        cancel_check,
    ) -> None:  # type: ignore[no-untyped-def]
        if cancel_check is not None:
            cancel_check()
        with self._session_factory() as session:
            scope = self._replay_planner.resolve_scope(
                session,
                start_date=self._required_date(payload, "replay_start_date"),
                end_date=self._required_date(payload, "replay_end_date"),
            )
            session.rollback()
        if cancel_check is not None:
            cancel_check()
        if canonical_json_hash(scope.open_trade_dates) != self._required_text(
            payload, "target_dates_hash"
        ):
            raise SectorAnalysisDailyFactsPlanDriftError(
                "历史刷新SSE交易日清单已偏离输入审计"
            )
        if scope.hierarchy_version != self._required_text(
            payload, "expected_hierarchy_version"
        ):
            raise SectorAnalysisDailyFactsPlanDriftError(
                "历史刷新层级版本已偏离输入审计"
            )

    @staticmethod
    def _validate_history_request(params: Mapping[str, Any]) -> None:
        forbidden = {
            key
            for key in ("execution_mode", "plan_task_run_id", "plan_hash")
            if params.get(key) not in (None, "")
        }
        if forbidden:
            raise ValueError(
                "sector-analysis history no longer accepts PLAN/APPLY parameters"
            )

    @staticmethod
    def _validate_history_unit_contract(payload: Mapping[str, Any]) -> None:
        if payload.get("audit_contract_version") != HISTORY_INPUT_AUDIT_CONTRACT_VERSION:
            raise SectorAnalysisDailyFactsPlanDriftError(
                "旧版历史PLAN或输入审计合同不可执行"
            )
        if payload.get("expected_formula_bundle_version") != FORMULA_BUNDLE_VERSION:
            raise SectorAnalysisDailyFactsPlanDriftError("历史刷新公式版本已漂移")
        if payload.get("expected_template_version") != TEMPLATE_VERSION:
            raise SectorAnalysisDailyFactsPlanDriftError("历史刷新模板版本已漂移")
        audit_hash = str(payload.get("audit_hash") or "")
        if len(audit_hash) != 64:
            raise SectorAnalysisDailyFactsPlanDriftError("历史刷新输入审计hash非法")

    @staticmethod
    def _update_apply_phase(
        context: MaintenanceTaskRunContext,
        payload: Mapping[str, Any],
        phase: str,
    ) -> None:
        unit_index = int(payload.get("unit_index") or 0)
        unit_total = int(payload.get("unit_total") or 0)
        trade_date = str(payload.get("trade_date") or "")
        context.run_context.update_progress(
            run_id=context.task_run_id,
            unit_done=max(unit_index - 1, 0),
            unit_failed=0,
            total=unit_total,
            message=f"APPLYING {trade_date} {phase}",
            ingestion_diagnostics={
                "maintenance_audit": {
                    "phase": "APPLYING",
                    "current_step": phase,
                    "last_checkpoint_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            current_object={
                "entity": {"type": "trade_date", "value": trade_date},
                "time": {"trade_date": trade_date},
                "attributes": {"phase": "APPLYING", "step": phase},
            },
        )

    @staticmethod
    def _raise_if_audit_canceled(context: MaintenanceInputAuditTaskRunContext) -> None:
        if context.is_cancel_requested():
            raise IngestionCanceledError("sector-analysis history audit cancellation requested")

    @staticmethod
    def _raise_if_execution_canceled(context: MaintenanceTaskRunContext) -> None:
        if context.run_context.is_cancel_requested(run_id=context.task_run_id):
            raise IngestionCanceledError("sector-analysis history APPLY cancellation requested")

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
