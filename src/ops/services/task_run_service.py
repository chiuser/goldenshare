from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition, get_dataset_definition_by_action_key
from src.ops.action_catalog import (
    WorkflowDefinition,
    get_maintenance_action,
    get_target_display_name,
    get_workflow_definition,
)
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.task_run import TaskRun


MONTHLY_LAST_DAY_POLICY = "monthly_last_day"
MONTHLY_WINDOW_CURRENT_MONTH_POLICY = "monthly_window_current_month"


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
        calendar_policy: str | None = None,
        scheduled_at: datetime | None = None,
        timezone_name: str | None = None,
    ) -> TaskRun:
        params = dict(params_json or {})
        context = self._context_from_schedule_target(
            target_type=target_type,
            target_key=target_key,
            params_json=params,
            trigger_source=trigger_source,
            requested_by_user_id=requested_by_user_id,
            schedule_id=schedule_id,
            calendar_policy=calendar_policy,
            scheduled_at=scheduled_at,
            timezone_name=timezone_name,
        )
        return self.create_task_run(session, context=context)

    def validate_schedule_target(
        self,
        *,
        target_type: str,
        target_key: str,
        params_json: dict[str, Any] | None,
        trigger_source: str = "schedule",
    ) -> None:
        context = self._context_from_schedule_target(
            target_type=target_type,
            target_key=target_key,
            params_json=dict(params_json or {}),
            trigger_source=trigger_source,
            requested_by_user_id=None,
            schedule_id=None,
        )
        self._validate_context(context)

    def create_task_run(self, session: Session, *, context: TaskRunCreateContext) -> TaskRun:
        self._validate_context(context)
        now = datetime.now(timezone.utc)
        title = self._resolve_title(context)
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
            raise WebAppError(status_code=404, code="not_found", message="任务记录不存在")
        context = self._context_from_retry(
            session=session,
            existing=existing,
            requested_by_user_id=requested_by_user_id,
        )
        return self.create_task_run(session, context=context)

    def request_cancel(self, session: Session, *, task_run_id: int, requested_by_user_id: int) -> TaskRun:
        task_run = session.scalar(select(TaskRun).where(TaskRun.id == task_run_id))
        if task_run is None:
            raise WebAppError(status_code=404, code="not_found", message="任务记录不存在")
        if task_run.status in {"success", "failed", "partial_success", "canceled"}:
            raise WebAppError(status_code=409, code="conflict", message="任务已经结束")
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
        calendar_policy: str | None = None,
        scheduled_at: datetime | None = None,
        timezone_name: str | None = None,
    ) -> TaskRunCreateContext:
        if target_type == "dataset_action":
            try:
                definition, action = get_dataset_definition_by_action_key(target_key)
            except KeyError as exc:
                raise WebAppError(status_code=422, code="validation_error", message="数据集维护目标不存在") from exc
            return TaskRunCreateContext(
                task_type="dataset_action",
                resource_key=definition.dataset_key,
                action=action,
                time_input=self._resolve_dataset_action_schedule_time_input(
                    definition=definition,
                    target_key=target_key,
                    params_json=params_json,
                    calendar_policy=calendar_policy,
                    scheduled_at=scheduled_at,
                    timezone_name=timezone_name,
                ),
                filters=self._extract_filters(params_json),
                request_payload=self._dataset_action_request_payload(params_json),
                trigger_source=trigger_source,
                requested_by_user_id=requested_by_user_id,
                schedule_id=schedule_id,
            )
        if target_type == "workflow":
            workflow = get_workflow_definition(target_key)
            if workflow is None:
                raise WebAppError(status_code=404, code="not_found", message="自动流程不存在")
            return TaskRunCreateContext(
                task_type="workflow",
                resource_key=None,
                action="maintain",
                time_input=self._resolve_schedule_time_input(
                    target_type=target_type,
                    target_key=target_key,
                    params_json=params_json,
                    workflow=workflow,
                    scheduled_at=scheduled_at,
                    timezone_name=timezone_name,
                ),
                filters=self._extract_filters(params_json),
                request_payload={**params_json, "target_type": target_type, "target_key": target_key},
                trigger_source=trigger_source,
                requested_by_user_id=requested_by_user_id,
                schedule_id=schedule_id,
            )
        if target_type == "maintenance_action":
            action = get_maintenance_action(target_key)
            if action is None:
                raise WebAppError(status_code=404, code="not_found", message="系统维护动作不存在")
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
        raise WebAppError(status_code=422, code="validation_error", message="不支持的任务类型")

    @classmethod
    def _resolve_dataset_action_schedule_time_input(
        cls,
        *,
        definition: DatasetDefinition,
        target_key: str,
        params_json: dict[str, Any],
        calendar_policy: str | None,
        scheduled_at: datetime | None,
        timezone_name: str | None,
    ) -> dict[str, Any]:
        time_input = cls._resolve_schedule_time_input(
            target_type="dataset_action",
            target_key=target_key,
            params_json=params_json,
        )
        normalized_policy = str(calendar_policy or "").strip() or None
        if normalized_policy is None:
            return time_input
        if normalized_policy not in {MONTHLY_LAST_DAY_POLICY, MONTHLY_WINDOW_CURRENT_MONTH_POLICY}:
            raise WebAppError(status_code=422, code="validation_error", message=f"不支持的日期策略：{normalized_policy}")
        if normalized_policy == MONTHLY_LAST_DAY_POLICY:
            if definition.date_model.bucket_rule != "month_last_calendar_day":
                raise WebAppError(status_code=422, code="validation_error", message="每月最后一天策略只支持自然月末数据集")
            if cls._has_fixed_trade_date(params_json):
                raise WebAppError(status_code=422, code="validation_error", message="每月最后一天策略不能与固定维护日期混用")
            if scheduled_at is None:
                raise WebAppError(status_code=422, code="validation_error", message="每月最后一天策略缺少计划触发时间")
            trade_date = cls._month_last_day_for_schedule(scheduled_at=scheduled_at, timezone_name=timezone_name)
            return {
                **dict(time_input or {}),
                "mode": "point",
                "trade_date": trade_date.isoformat(),
            }
        if not cls._supports_month_window_policy(definition):
            raise WebAppError(status_code=422, code="validation_error", message="自然月窗口策略只支持月窗口数据集")
        if cls._has_explicit_time_boundary(params_json):
            raise WebAppError(status_code=422, code="validation_error", message="自然月窗口策略不能与固定维护日期或窗口混用")
        if scheduled_at is None:
            raise WebAppError(status_code=422, code="validation_error", message="自然月窗口策略缺少计划触发时间")
        month_key = cls._month_key_for_schedule(scheduled_at=scheduled_at, timezone_name=timezone_name)
        return {
            **dict(time_input or {}),
            "mode": "range",
            "start_month": month_key,
            "end_month": month_key,
        }

    @staticmethod
    def _validate_context(context: TaskRunCreateContext) -> None:
        if context.task_type == "dataset_action":
            if not context.resource_key:
                raise WebAppError(status_code=422, code="validation_error", message="数据集任务缺少维护对象")
            try:
                definition = get_dataset_definition(context.resource_key)
            except KeyError as exc:
                raise WebAppError(status_code=404, code="not_found", message="数据集定义不存在") from exc
            action = definition.capabilities.get_action(context.action)
            if action is None:
                raise WebAppError(status_code=422, code="validation_error", message="数据集不支持该维护动作")
            return
        if context.task_type == "workflow":
            payload_target_key = str((context.request_payload or {}).get("target_key") or "")
            workflow = get_workflow_definition(payload_target_key) if payload_target_key else None
            if workflow is None:
                raise WebAppError(status_code=422, code="validation_error", message="自动流程任务缺少流程定义")
            TaskRunCommandService._validate_workflow_time_input(
                workflow=workflow,
                time_input=dict(context.time_input or {}),
                source=context.trigger_source,
            )
            return
        if context.task_type == "maintenance_action":
            payload_target_key = str((context.request_payload or {}).get("target_key") or "")
            if not payload_target_key or get_maintenance_action(payload_target_key) is None:
                raise WebAppError(status_code=422, code="validation_error", message="系统维护任务缺少维护动作")
            return
        raise WebAppError(status_code=422, code="validation_error", message="不支持的任务类型")

    @staticmethod
    def _resolve_title(context: TaskRunCreateContext) -> str:
        if context.resource_key:
            return get_dataset_definition(context.resource_key).display_name
        target_key = str((context.request_payload or {}).get("target_key") or "").strip()
        display_name = get_target_display_name(context.task_type, target_key) if target_key else None
        if display_name is not None:
            return display_name
        return context.action

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

    @classmethod
    def _resolve_schedule_time_input(
        cls,
        *,
        target_type: str,
        target_key: str,
        params_json: dict[str, Any],
        workflow: WorkflowDefinition | None = None,
        scheduled_at: datetime | None = None,
        timezone_name: str | None = None,
    ) -> dict[str, Any]:
        if cls._has_explicit_time_input(params_json):
            return cls._extract_time_input(params_json)
        if target_type == "workflow":
            resolved_workflow = workflow or get_workflow_definition(target_key)
            if resolved_workflow is None:
                raise WebAppError(status_code=404, code="not_found", message="自动流程不存在")
            return cls._default_workflow_time_input(
                resolved_workflow,
                scheduled_at=scheduled_at,
                timezone_name=timezone_name,
            )
        return {"mode": "none"}

    @staticmethod
    def _has_explicit_time_input(params_json: dict[str, Any]) -> bool:
        if isinstance(params_json.get("time_input"), dict):
            return True
        return any(
            params_json.get(key) not in (None, "")
            for key in ("trade_date", "ann_date", "month", "start_date", "end_date", "start_month", "end_month")
        )

    @staticmethod
    def _has_fixed_trade_date(params_json: dict[str, Any]) -> bool:
        if params_json.get("trade_date") not in (None, ""):
            return True
        time_input = params_json.get("time_input")
        return isinstance(time_input, dict) and time_input.get("trade_date") not in (None, "")

    @staticmethod
    def _has_explicit_time_boundary(params_json: dict[str, Any]) -> bool:
        time_keys = {"trade_date", "start_date", "end_date", "start_month", "end_month"}
        if any(params_json.get(key) not in (None, "") for key in time_keys):
            return True
        time_input = params_json.get("time_input")
        return isinstance(time_input, dict) and any(time_input.get(key) not in (None, "") for key in time_keys)

    @staticmethod
    def _supports_month_window_policy(definition: DatasetDefinition) -> bool:
        date_model = definition.date_model
        return (
            date_model.date_axis == "month_window"
            and date_model.bucket_rule == "month_window_has_data"
            and date_model.input_shape == "start_end_month_window"
        )

    @staticmethod
    def _month_last_day_for_schedule(*, scheduled_at: datetime, timezone_name: str | None) -> date:
        local_scheduled_at = TaskRunCommandService._local_scheduled_at(scheduled_at=scheduled_at, timezone_name=timezone_name)
        last_day = monthrange(local_scheduled_at.year, local_scheduled_at.month)[1]
        return date(local_scheduled_at.year, local_scheduled_at.month, last_day)

    @staticmethod
    def _month_key_for_schedule(*, scheduled_at: datetime, timezone_name: str | None) -> str:
        local_scheduled_at = TaskRunCommandService._local_scheduled_at(scheduled_at=scheduled_at, timezone_name=timezone_name)
        return f"{local_scheduled_at.year}{local_scheduled_at.month:02d}"

    @staticmethod
    def _natural_day_for_schedule(*, scheduled_at: datetime, timezone_name: str | None) -> date:
        local_scheduled_at = TaskRunCommandService._local_scheduled_at(scheduled_at=scheduled_at, timezone_name=timezone_name)
        return local_scheduled_at.date()

    @staticmethod
    def _local_scheduled_at(*, scheduled_at: datetime, timezone_name: str | None) -> datetime:
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        zone_name = str(timezone_name or "Asia/Shanghai").strip() or "Asia/Shanghai"
        try:
            zone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError as exc:
            raise WebAppError(status_code=422, code="validation_error", message="排程时区无效") from exc
        return scheduled_at.astimezone(zone)

    @staticmethod
    def _default_workflow_time_input(
        workflow: WorkflowDefinition,
        *,
        scheduled_at: datetime | None = None,
        timezone_name: str | None = None,
    ) -> dict[str, Any]:
        keys = {param.key for param in workflow.parameters}
        if not keys:
            return {"mode": "none"}
        if workflow.workflow_profile == "point_incremental" and "trade_date" in keys:
            if workflow.time_regime == "natural_day" and scheduled_at is not None:
                return {
                    "mode": "point",
                    "trade_date": TaskRunCommandService._natural_day_for_schedule(
                        scheduled_at=scheduled_at,
                        timezone_name=timezone_name,
                    ).isoformat(),
                }
            return {"mode": "point"}
        raise WebAppError(
            status_code=422,
            code="validation_error",
            message=f"自动流程 {workflow.display_name} 需要明确填写时间范围后才能用于自动任务",
        )

    @staticmethod
    def _validate_workflow_time_input(*, workflow: WorkflowDefinition, time_input: dict[str, Any], source: str) -> None:
        keys = {param.key for param in workflow.parameters}
        mode = str(time_input.get("mode") or "none").strip() or "none"
        if not keys:
            return
        if mode == "point":
            if "trade_date" not in keys:
                raise WebAppError(
                    status_code=422,
                    code="validation_error",
                    message=f"自动流程 {workflow.display_name} 不支持按单日触发",
                )
            return
        if mode == "range":
            if not {"start_date", "end_date"}.issubset(keys):
                raise WebAppError(
                    status_code=422,
                    code="validation_error",
                    message=f"自动流程 {workflow.display_name} 不支持按区间触发",
                )
            if source == "schedule":
                start_date = time_input.get("start_date")
                end_date = time_input.get("end_date")
                if start_date in (None, "") or end_date in (None, ""):
                    raise WebAppError(
                        status_code=422,
                        code="validation_error",
                        message=f"自动流程 {workflow.display_name} 的自动任务必须同时填写开始日期和结束日期",
                    )
            return
        raise WebAppError(
            status_code=422,
            code="validation_error",
            message=f"自动流程 {workflow.display_name} 缺少可执行的时间配置",
        )

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
        payload.pop("dataset_key", None)
        payload.pop("action", None)
        return payload

    def _context_from_retry(
        self,
        *,
        session: Session,
        existing: TaskRun,
        requested_by_user_id: int,
    ) -> TaskRunCreateContext:
        return TaskRunCreateContext(
            task_type=existing.task_type,
            resource_key=existing.resource_key,
            action=existing.action,
            time_input=dict(existing.time_input_json or {}),
            filters=dict(existing.filters_json or {}),
            request_payload=self._retry_request_payload(session, existing),
            trigger_source="retry",
            requested_by_user_id=requested_by_user_id,
            schedule_id=existing.schedule_id,
        )

    @staticmethod
    def _retry_request_payload(session: Session, existing: TaskRun) -> dict[str, Any]:
        request_payload = dict(existing.request_payload_json or {})
        if existing.task_type not in {"workflow", "maintenance_action"}:
            return request_payload
        if str(request_payload.get("target_key") or "").strip():
            return request_payload
        if existing.schedule_id is None:
            return request_payload
        schedule = session.get(OpsSchedule, existing.schedule_id)
        if schedule is None or schedule.target_type != existing.task_type:
            return request_payload
        return {
            **request_payload,
            "target_type": schedule.target_type,
            "target_key": schedule.target_key,
        }
