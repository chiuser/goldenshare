from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.ops.specs import get_job_spec, get_workflow_spec
from src.app.exceptions import WebAppError
from src.foundation.datasets.registry import get_dataset_definition


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    dataset_key: str | None = None
    source_key: str | None = None
    stage: str | None = None
    policy_version: int | None = None
    run_scope: str | None = None
    run_profile: str | None = None
    workflow_profile: str | None = None
    failure_policy_default: str | None = None
    resume_from_step_key: str | None = None


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
            run_profile=resolved_context.run_profile or self._derive_run_profile(spec_type=spec_type, params_json=params_json or {}),
            workflow_profile=resolved_context.workflow_profile,
            failure_policy_default=resolved_context.failure_policy_default or "fail_fast",
            correlation_id=str((params_json or {}).get("correlation_id") or uuid4().hex),
            rerun_id=self._to_optional_text((params_json or {}).get("rerun_id")),
            resume_from_step_key=resolved_context.resume_from_step_key,
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
                        "run_profile": resolved_context.run_profile,
                        "workflow_profile": resolved_context.workflow_profile,
                    },
                    occurred_at=now,
                    correlation_id=execution.correlation_id,
                    producer="service",
                    dedupe_key=f"{execution.id}:created:{int(now.timestamp())}",
                ),
                JobExecutionEvent(
                    execution_id=execution.id,
                    event_type="queued",
                    level="INFO",
                    message="Execution queued",
                    payload_json={},
                    occurred_at=now,
                    correlation_id=execution.correlation_id,
                    producer="service",
                    dedupe_key=f"{execution.id}:queued:{int(now.timestamp())}",
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
                run_profile=existing.run_profile,
                workflow_profile=existing.workflow_profile,
                failure_policy_default=existing.failure_policy_default,
                resume_from_step_key=existing.resume_from_step_key,
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
                correlation_id=execution.correlation_id,
                producer="service",
                dedupe_key=f"{execution.id}:cancel_requested:{int(now.timestamp())}",
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
                    correlation_id=execution.correlation_id,
                    producer="service",
                    dedupe_key=f"{execution.id}:canceled:{int(now.timestamp())}",
                )
            )
        session.commit()
        session.refresh(execution)
        return execution

    @staticmethod
    def _validate_spec(spec_type: str, spec_key: str) -> None:
        if spec_type == "dataset_action":
            if not spec_key.endswith(".maintain"):
                raise WebAppError(status_code=422, code="validation_error", message="Dataset action spec_key must end with .maintain")
            dataset_key = spec_key.rsplit(".", 1)[0]
            if not dataset_key:
                raise WebAppError(status_code=422, code="validation_error", message="Dataset action spec_key is invalid")
            try:
                get_dataset_definition(dataset_key)
            except KeyError as exc:
                raise WebAppError(status_code=404, code="not_found", message="Dataset definition does not exist") from exc
            return
        if spec_type == "job":
            job_spec = get_job_spec(spec_key)
            if job_spec is None:
                raise WebAppError(status_code=404, code="not_found", message="Job spec does not exist")
            if job_spec.category != "maintenance":
                raise WebAppError(status_code=422, code="validation_error", message="Legacy job specs are no longer accepted; use dataset_action")
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
        resume_from_step_key = str(params_json.get("resume_from_step_key") or "").strip() or None
        if run_scope is None:
            run_scope = OperationsExecutionService._derive_run_scope(spec_type=spec_type, spec_key=spec_key, params_json=params_json)
        run_profile = OperationsExecutionService._derive_run_profile(spec_type=spec_type, params_json=params_json)
        workflow_profile = None
        failure_policy_default = str(params_json.get("failure_policy_default") or "").strip() or None
        if spec_type == "workflow":
            workflow_spec = get_workflow_spec(spec_key)
            if workflow_spec is not None:
                workflow_profile = workflow_spec.workflow_profile
                if failure_policy_default is None:
                    failure_policy_default = workflow_spec.failure_policy_default
        return ExecutionContext(
            dataset_key=dataset_key,
            source_key=source_key,
            stage=stage,
            policy_version=policy_version,
            run_scope=run_scope,
            run_profile=run_profile,
            workflow_profile=workflow_profile,
            failure_policy_default=failure_policy_default,
            resume_from_step_key=resume_from_step_key,
        )

    @staticmethod
    def _resolve_dataset_key(*, spec_type: str, spec_key: str) -> str | None:
        if spec_type == "dataset_action":
            if not spec_key.endswith(".maintain"):
                return None
            dataset_key = spec_key.rsplit(".", 1)[0]
            return dataset_key or None
        if spec_type == "job":
            if "." in spec_key:
                return spec_key.split(".", 1)[1]
            return spec_key
        if spec_type != "workflow":
            return None
        workflow_spec = get_workflow_spec(spec_key)
        if workflow_spec is None:
            return None
        datasets: set[str] = set()
        for step in workflow_spec.steps:
            if step.dataset_key:
                datasets.add(step.dataset_key)
                continue
            if "." in step.job_key:
                datasets.add(step.job_key.split(".", 1)[1])
        if len(datasets) == 1:
            return next(iter(datasets))
        return None

    @staticmethod
    def _derive_run_scope(*, spec_type: str, spec_key: str, params_json: dict[str, Any]) -> str:
        if spec_type == "dataset_action":
            time_input = params_json.get("time_input") or {}
            mode = str(time_input.get("mode") or "").strip()
            if not mode:
                if any(params_json.get(key) for key in ("start_date", "end_date", "start_month", "end_month")):
                    mode = "range"
                elif any(params_json.get(key) for key in ("trade_date", "month")):
                    mode = "point"
            if mode == "range":
                return "range"
            if mode == "none":
                return "full"
            return "single"
        if spec_type == "workflow":
            return "workflow"
        if any(params_json.get(key) for key in ("start_date", "end_date", "start_month", "end_month")):
            return "range"
        if any(params_json.get(key) for key in ("trade_date", "month")):
            return "single"
        return "single"

    @staticmethod
    def _derive_run_profile(*, spec_type: str, params_json: dict[str, Any]) -> str:
        explicit = str(params_json.get("run_profile") or "").strip()
        if explicit in {"point_incremental", "range_rebuild", "snapshot_refresh"}:
            return explicit
        if spec_type == "dataset_action":
            time_input = params_json.get("time_input") or {}
            mode = str(time_input.get("mode") or "").strip()
            if not mode:
                if any(params_json.get(key) for key in ("start_date", "end_date", "start_month", "end_month")):
                    mode = "range"
                elif any(params_json.get(key) for key in ("trade_date", "month")):
                    mode = "point"
            if mode == "range":
                return "range_rebuild"
            if mode == "none":
                return "snapshot_refresh"
            return "point_incremental"
        if spec_type == "workflow":
            return "snapshot_refresh"
        if any(params_json.get(key) for key in ("start_date", "end_date", "start_month", "end_month")):
            return "range_rebuild"
        return "point_incremental"

    @staticmethod
    def _to_optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
