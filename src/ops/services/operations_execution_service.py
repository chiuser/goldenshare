from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.ops.specs import get_job_spec, get_workflow_spec
from src.platform.exceptions import WebAppError


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    dataset_key: str | None = None
    source_key: str | None = None
    stage: str | None = None
    policy_version: int | None = None
    run_scope: str | None = None


class OperationsExecutionService:
    def create_execution(
        self,
        session: Session,
        *,
        spec_type: str,
        spec_key: str,
        params_json: dict | None,
        trigger_source: str,
        requested_by_user_id: int | None,
        schedule_id: int | None = None,
        context: ExecutionContext | None = None,
    ) -> JobExecution:
        self._validate_spec(spec_type, spec_key)
        resolved_context = context or self._resolve_execution_context(
            spec_type=spec_type,
            spec_key=spec_key,
            params_json=params_json or {},
        )
        now = datetime.now(timezone.utc)
        execution = JobExecution(
            schedule_id=schedule_id,
            spec_type=spec_type,
            spec_key=spec_key,
            dataset_key=resolved_context.dataset_key,
            source_key=resolved_context.source_key,
            stage=resolved_context.stage,
            policy_version=resolved_context.policy_version,
            run_scope=resolved_context.run_scope,
            trigger_source=trigger_source,
            status="queued",
            requested_by_user_id=requested_by_user_id,
            requested_at=now,
            queued_at=now,
            params_json=params_json or {},
        )
        session.add(execution)
        session.flush()
        session.add_all(
            [
                JobExecutionEvent(
                    execution_id=execution.id,
                    event_type="created",
                    level="INFO",
                    message="Execution created",
                    payload_json={
                        "trigger_source": trigger_source,
                        "dataset_key": resolved_context.dataset_key,
                        "source_key": resolved_context.source_key,
                        "stage": resolved_context.stage,
                        "policy_version": resolved_context.policy_version,
                        "run_scope": resolved_context.run_scope,
                    },
                    occurred_at=now,
                ),
                JobExecutionEvent(
                    execution_id=execution.id,
                    event_type="queued",
                    level="INFO",
                    message="Execution queued",
                    payload_json={},
                    occurred_at=now,
                ),
            ]
        )
        session.commit()
        session.refresh(execution)
        return execution

    def retry_execution(self, session: Session, *, execution_id: int, requested_by_user_id: int) -> JobExecution:
        existing = session.scalar(select(JobExecution).where(JobExecution.id == execution_id))
        if existing is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        return self.create_execution(
            session,
            spec_type=existing.spec_type,
            spec_key=existing.spec_key,
            params_json=dict(existing.params_json or {}),
            trigger_source="retry",
            requested_by_user_id=requested_by_user_id,
            schedule_id=existing.schedule_id,
            context=ExecutionContext(
                dataset_key=existing.dataset_key,
                source_key=existing.source_key,
                stage=existing.stage,
                policy_version=existing.policy_version,
                run_scope=existing.run_scope,
            ),
        )

    def request_cancel(self, session: Session, *, execution_id: int, requested_by_user_id: int) -> JobExecution:
        execution = session.scalar(select(JobExecution).where(JobExecution.id == execution_id))
        if execution is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        if execution.status in {"success", "failed", "canceled"}:
            raise WebAppError(status_code=409, code="conflict", message="Execution is already finished")
        if execution.cancel_requested_at is not None:
            session.refresh(execution)
            return execution

        now = datetime.now(timezone.utc)
        execution.cancel_requested_at = now
        execution.last_progress_at = now
        execution.progress_message = "已收到停止请求，正在结束当前处理。"
        if execution.status == "queued":
            execution.status = "canceled"
            execution.canceled_at = now
            execution.ended_at = now
            execution.summary_message = "任务在开始前已停止。"
        else:
            execution.status = "canceling"
        session.add(
            JobExecutionEvent(
                execution_id=execution.id,
                event_type="cancel_requested",
                level="INFO",
                message="Cancel requested",
                payload_json={"requested_by_user_id": requested_by_user_id},
                occurred_at=now,
            )
        )
        if execution.status == "canceled":
            session.add(
                JobExecutionEvent(
                    execution_id=execution.id,
                    event_type="canceled",
                    level="INFO",
                    message="Execution canceled before start",
                    payload_json={"requested_by_user_id": requested_by_user_id},
                    occurred_at=now,
                )
            )
        session.commit()
        session.refresh(execution)
        return execution

    @staticmethod
    def _validate_spec(spec_type: str, spec_key: str) -> None:
        if spec_type == "job":
            if get_job_spec(spec_key) is None:
                raise WebAppError(status_code=404, code="not_found", message="Job spec does not exist")
            return
        if spec_type == "workflow":
            if get_workflow_spec(spec_key) is None:
                raise WebAppError(status_code=404, code="not_found", message="Workflow spec does not exist")
            return
        raise WebAppError(status_code=422, code="validation_error", message="Unsupported spec_type")

    @staticmethod
    def _resolve_execution_context(*, spec_type: str, spec_key: str, params_json: dict[str, Any]) -> ExecutionContext:
        dataset_key = OperationsExecutionService._resolve_dataset_key(spec_type=spec_type, spec_key=spec_key)
        source_key = str(params_json.get("source_key") or "").strip() or None
        stage = str(params_json.get("stage") or "").strip().lower() or None
        policy_version = OperationsExecutionService._to_optional_int(params_json.get("policy_version"))
        run_scope = str(params_json.get("run_scope") or "").strip() or None
        if run_scope is None:
            run_scope = OperationsExecutionService._derive_run_scope(spec_type=spec_type, spec_key=spec_key, params_json=params_json)
        return ExecutionContext(
            dataset_key=dataset_key,
            source_key=source_key,
            stage=stage,
            policy_version=policy_version,
            run_scope=run_scope,
        )

    @staticmethod
    def _resolve_dataset_key(*, spec_type: str, spec_key: str) -> str | None:
        if spec_type == "job":
            if "." in spec_key:
                return spec_key.split(".", 1)[1]
            return spec_key
        if spec_type != "workflow":
            return None
        workflow_spec = get_workflow_spec(spec_key)
        if workflow_spec is None:
            return None
        datasets = {
            step.job_key.split(".", 1)[1]
            for step in workflow_spec.steps
            if "." in step.job_key
        }
        if len(datasets) == 1:
            return next(iter(datasets))
        return None

    @staticmethod
    def _derive_run_scope(*, spec_type: str, spec_key: str, params_json: dict[str, Any]) -> str:
        if spec_type == "workflow":
            return "workflow"
        if any(params_json.get(key) for key in ("start_date", "end_date", "start_month", "end_month")):
            return "range"
        if any(params_json.get(key) for key in ("trade_date", "month")):
            return "single"
        if spec_key.startswith("sync_history."):
            return "full"
        return "single"

    @staticmethod
    def _to_optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
