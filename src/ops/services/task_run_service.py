from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.foundation.datasets.registry import get_dataset_definition, get_dataset_definition_by_action_key
from src.ops.action_catalog import get_maintenance_action, get_workflow_definition
from src.ops.models.ops.task_run import TaskRun


@dataclass(frozen=True, slots=True)
class TaskRunCreateContext:
    task_type: str
    resource_key: str | None
    action: str
    time_input: dict[str, Any]
    filters: dict[str, Any]
    request_payload: dict[str, Any]
    trigger_source: str
    requested_by_user_id: int | None
    schedule_id: int | None = None


class TaskRunCommandService:
    def create_manual_task_run(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        task_type: str,
        resource_key: str | None,
        action: str,
        time_input: dict[str, Any],
        filters: dict[str, Any],
        request_payload: dict[str, Any] | None = None,
    ) -> int:
        task_run = self.create_task_run(
            session,
            context=TaskRunCreateContext(
                task_type=task_type,
                resource_key=resource_key,
                action=action,
                time_input=time_input,
                filters=filters,
                request_payload=request_payload or {},
                trigger_source="manual",
                requested_by_user_id=user.id,
            ),
        )
        return task_run.id

    def create_from_schedule_target(
        self,
        session: Session,
        *,
        target_type: str,
        target_key: str,
        params_json: dict[str, Any] | None,
        trigger_source: str,
        requested_by_user_id: int | None,
        schedule_id: int | None = None,
    ) -> TaskRun:
        params = dict(params_json or {})
        context = self._context_from_schedule_target(
            target_type=target_type,
            target_key=target_key,
            params_json=params,
            trigger_source=trigger_source,
            requested_by_user_id=requested_by_user_id,
            schedule_id=schedule_id,
        )
        return self.create_task_run(session, context=context)

    def create_task_run(self, session: Session, *, context: TaskRunCreateContext) -> TaskRun:
        self._validate_context(context)
        now = datetime.now(timezone.utc)
        title = self._resolve_title(task_type=context.task_type, resource_key=context.resource_key, action=context.action)
        request_payload = {
            **dict(context.request_payload or {}),
            "task_type": context.task_type,
            "resource_key": context.resource_key,
            "action": context.action,
            "time_input": dict(context.time_input or {}),
            "filters": dict(context.filters or {}),
        }
        task_run = TaskRun(
            task_type=context.task_type,
            resource_key=context.resource_key,
            action=context.action,
            title=title,
            trigger_source=context.trigger_source,
            requested_by_user_id=context.requested_by_user_id,
            schedule_id=context.schedule_id,
            status="queued",
            time_input_json=dict(context.time_input or {}),
            filters_json=dict(context.filters or {}),
            request_payload_json=request_payload,
            requested_at=now,
            queued_at=now,
        )
        session.add(task_run)
        session.commit()
        session.refresh(task_run)
        return task_run

    def retry_task_run(self, session: Session, *, task_run_id: int, requested_by_user_id: int) -> TaskRun:
        existing = session.scalar(select(TaskRun).where(TaskRun.id == task_run_id))
        if existing is None:
            raise WebAppError(status_code=404, code="not_found", message="Task run does not exist")
        return self.create_task_run(
            session,
            context=TaskRunCreateContext(
                task_type=existing.task_type,
                resource_key=existing.resource_key,
                action=existing.action,
                time_input=dict(existing.time_input_json or {}),
                filters=dict(existing.filters_json or {}),
                request_payload=dict(existing.request_payload_json or {}),
                trigger_source="retry",
                requested_by_user_id=requested_by_user_id,
                schedule_id=existing.schedule_id,
            ),
        )

    def request_cancel(self, session: Session, *, task_run_id: int, requested_by_user_id: int) -> TaskRun:
        task_run = session.scalar(select(TaskRun).where(TaskRun.id == task_run_id))
        if task_run is None:
            raise WebAppError(status_code=404, code="not_found", message="Task run does not exist")
        if task_run.status in {"success", "failed", "partial_success", "canceled"}:
            raise WebAppError(status_code=409, code="conflict", message="Task run is already finished")
        if task_run.cancel_requested_at is not None:
            session.refresh(task_run)
            return task_run

        now = datetime.now(timezone.utc)
        task_run.cancel_requested_at = now
        if task_run.status == "queued":
            task_run.status = "canceled"
            task_run.canceled_at = now
            task_run.ended_at = now
            task_run.status_reason_code = "canceled_before_start"
        else:
            task_run.status = "canceling"
            task_run.status_reason_code = "cancel_requested"
        session.commit()
        session.refresh(task_run)
        return task_run

    def _context_from_schedule_target(
        self,
        *,
        target_type: str,
        target_key: str,
        params_json: dict[str, Any],
        trigger_source: str,
        requested_by_user_id: int | None,
        schedule_id: int | None,
    ) -> TaskRunCreateContext:
        if target_type == "dataset_action":
            try:
                definition, action = get_dataset_definition_by_action_key(target_key)
            except KeyError as exc:
                raise WebAppError(status_code=422, code="validation_error", message="Invalid dataset action target_key") from exc
            resource_key = str(params_json.get("dataset_key") or definition.dataset_key).strip()
            return TaskRunCreateContext(
                task_type="dataset_action",
                resource_key=resource_key,
                action=str(params_json.get("action") or action).strip() or action,
                time_input=self._extract_time_input(params_json),
                filters=self._extract_filters(params_json),
                request_payload=self._dataset_action_request_payload(params_json),
                trigger_source=trigger_source,
                requested_by_user_id=requested_by_user_id,
                schedule_id=schedule_id,
            )
        if target_type == "workflow":
            if get_workflow_definition(target_key) is None:
                raise WebAppError(status_code=404, code="not_found", message="Workflow does not exist")
            return TaskRunCreateContext(
                task_type="workflow",
                resource_key=None,
                action="maintain",
                time_input=self._extract_time_input(params_json),
                filters=self._extract_filters(params_json),
                request_payload={**params_json, "target_type": target_type, "target_key": target_key},
                trigger_source=trigger_source,
                requested_by_user_id=requested_by_user_id,
                schedule_id=schedule_id,
            )
        if target_type == "maintenance_action":
            action = get_maintenance_action(target_key)
            if action is None:
                raise WebAppError(status_code=404, code="not_found", message="Maintenance action does not exist")
            return TaskRunCreateContext(
                task_type="maintenance_action",
                resource_key=None,
                action="maintain",
                time_input=self._extract_time_input(params_json),
                filters=self._extract_filters(params_json),
                request_payload={**params_json, "target_type": target_type, "target_key": target_key},
                trigger_source=trigger_source,
                requested_by_user_id=requested_by_user_id,
                schedule_id=schedule_id,
            )
        raise WebAppError(status_code=422, code="validation_error", message="Unsupported task type")

    @staticmethod
    def _validate_context(context: TaskRunCreateContext) -> None:
        if context.task_type == "dataset_action":
            if not context.resource_key:
                raise WebAppError(status_code=422, code="validation_error", message="resource_key is required")
            try:
                definition = get_dataset_definition(context.resource_key)
            except KeyError as exc:
                raise WebAppError(status_code=404, code="not_found", message="Dataset definition does not exist") from exc
            action = definition.capabilities.get_action(context.action)
            if action is None:
                raise WebAppError(status_code=422, code="validation_error", message="Dataset action is not supported")
            return
        if context.task_type == "workflow":
            payload_target_key = str((context.request_payload or {}).get("target_key") or "")
            if not payload_target_key or get_workflow_definition(payload_target_key) is None:
                raise WebAppError(status_code=422, code="validation_error", message="Workflow is required")
            return
        if context.task_type == "maintenance_action":
            payload_target_key = str((context.request_payload or {}).get("target_key") or "")
            if not payload_target_key or get_maintenance_action(payload_target_key) is None:
                raise WebAppError(status_code=422, code="validation_error", message="Maintenance action is required")
            return
        raise WebAppError(status_code=422, code="validation_error", message="Unsupported task_type")

    @staticmethod
    def _resolve_title(*, task_type: str, resource_key: str | None, action: str) -> str:
        if resource_key:
            return get_dataset_definition(resource_key).display_name
        if task_type == "workflow":
            return "工作流维护"
        if task_type == "maintenance_action":
            return "系统维护"
        return action

    @staticmethod
    def _extract_time_input(params_json: dict[str, Any]) -> dict[str, Any]:
        explicit = params_json.get("time_input")
        if isinstance(explicit, dict):
            return dict(explicit)
        if params_json.get("trade_date") not in (None, ""):
            return {"mode": "point", "trade_date": params_json["trade_date"]}
        if params_json.get("ann_date") not in (None, ""):
            return {
                "mode": "point",
                "trade_date": params_json["ann_date"],
                "ann_date": params_json["ann_date"],
                "date_field": "ann_date",
            }
        if params_json.get("month") not in (None, ""):
            return {"mode": "point", "month": params_json["month"]}
        if params_json.get("start_date") not in (None, "") or params_json.get("end_date") not in (None, ""):
            return {
                "mode": "range",
                "start_date": params_json.get("start_date"),
                "end_date": params_json.get("end_date"),
            }
        if params_json.get("start_month") not in (None, "") or params_json.get("end_month") not in (None, ""):
            return {
                "mode": "range",
                "start_month": params_json.get("start_month"),
                "end_month": params_json.get("end_month"),
            }
        return {"mode": "none"}

    @staticmethod
    def _extract_filters(params_json: dict[str, Any]) -> dict[str, Any]:
        explicit = params_json.get("filters")
        if isinstance(explicit, dict):
            return dict(explicit)
        reserved = {
            "action",
            "dataset_key",
            "time_input",
            "trade_date",
            "start_date",
            "end_date",
            "month",
            "start_month",
            "end_month",
            "ann_date",
            "date_field",
            "target_type",
            "target_key",
            "correlation_id",
            "rerun_id",
            "run_profile",
            "run_scope",
            "source_key",
            "stage",
            "policy_version",
            "resume_from_step_key",
            "failure_policy_default",
        }
        return {key: value for key, value in params_json.items() if key not in reserved}

    @staticmethod
    def _dataset_action_request_payload(params_json: dict[str, Any]) -> dict[str, Any]:
        payload = dict(params_json or {})
        payload.pop("target_type", None)
        payload.pop("target_key", None)
        return payload
