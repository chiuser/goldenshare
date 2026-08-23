from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.foundation.config.settings import get_settings
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition, get_dataset_definition_by_action_key
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionError
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.action_catalog import (
    WorkflowDefinition,
    get_maintenance_action,
    get_target_display_name,
    get_workflow_definition,
)
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.task_run import TaskRun
from src.ops.contracts.external_task import ExternalTaskDefinition
from src.ops.services.dataset_schedule_time_policy_resolver import DatasetScheduleTimePolicyResolver
from src.ops.services.ingestion_error_presentation import present_ingestion_error
from src.ops.services.news_stock_linking_service import (
    DEFAULT_OVERLAP_SECONDS,
    NEWS_STOCK_LINKING_ACTION_KEY,
    NEWS_STOCK_RULE_VERSION,
)


NEWS_STOCK_LINKING_ADVISORY_LOCK_KEY = 8_491_716_203


MONTHLY_LAST_DAY_POLICY = "monthly_last_day"
MONTHLY_LAST_TRADING_DAY_POLICY = "monthly_last_trading_day"
MONTHLY_WINDOW_CURRENT_MONTH_POLICY = "monthly_window_current_month"
TRIGGER_DAY_SINGLE_RANGE_POLICY = "trigger_day_single_range"
TRIGGER_DAY_POINT_POLICY = "trigger_day_point"
LATEST_COMPLETED_CALENDAR_QUARTER_POLICY = "latest_completed_calendar_quarter"
SINCE_LAST_SUCCESS_DAY_RANGE_POLICY = "since_last_success_day_range"


class ScheduleWindowAlreadyCovered(RuntimeError):
    """The successful cursor already covers the generated target end date."""


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
    def __init__(
        self,
        *,
        external_task_definitions: dict[str, ExternalTaskDefinition] | None = None,
    ) -> None:
        self._external_task_definitions = dict(external_task_definitions or {})
        if any(key != definition.task_type for key, definition in self._external_task_definitions.items()):
            raise ValueError("external task definition key must match task_type")

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
        context = self.build_schedule_task_context(
            session=session,
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

    def build_schedule_task_context(
        self,
        session: Session | None,
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
    ) -> TaskRunCreateContext:
        return self._context_from_schedule_target(
            session=session,
            target_type=target_type,
            target_key=target_key,
            params_json=dict(params_json or {}),
            trigger_source=trigger_source,
            requested_by_user_id=requested_by_user_id,
            schedule_id=schedule_id,
            calendar_policy=calendar_policy,
            scheduled_at=scheduled_at,
            timezone_name=timezone_name,
        )

    def validate_schedule_target(
        self,
        *,
        target_type: str,
        target_key: str,
        params_json: dict[str, Any] | None,
        trigger_source: str = "schedule",
    ) -> None:
        context = self._context_from_schedule_target(
            session=None,
            target_type=target_type,
            target_key=target_key,
            params_json=dict(params_json or {}),
            trigger_source=trigger_source,
            requested_by_user_id=None,
            schedule_id=None,
        )
        self._validate_context(context)

    def create_task_run(self, session: Session, *, context: TaskRunCreateContext) -> TaskRun:
        task_run = self.stage_task_run(session, context=context)
        session.commit()
        session.refresh(task_run)
        return task_run

    def stage_task_run(self, session: Session, *, context: TaskRunCreateContext) -> TaskRun:
        """Build and flush a TaskRun in the caller's transaction without committing."""
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
        request_payload = self._freeze_news_stock_linking_payload(session, request_payload)
        self._ensure_news_stock_linking_not_running(session, request_payload)
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
        session.flush()
        return task_run

    @staticmethod
    def _freeze_news_stock_linking_payload(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
        target_key = str(payload.get("target_key") or "").strip()
        if payload.get("task_type") != "maintenance_action" or target_key != NEWS_STOCK_LINKING_ACTION_KEY:
            return payload

        requested_mode = str(payload.get("mode") or "incremental").strip().lower()
        if requested_mode not in {"full", "incremental"}:
            raise WebAppError(status_code=422, code="validation_error", message="新闻关联执行模式必须是 full 或 incremental")

        window_end = datetime.now(timezone.utc)
        overlap_seconds = DEFAULT_OVERLAP_SECONDS if requested_mode == "incremental" else 0
        window_start: datetime | None = None
        mode = requested_mode
        if requested_mode == "incremental":
            previous_payload = next(
                (
                    candidate
                    for candidate in session.scalars(
                        select(TaskRun.request_payload_json)
                        .where(TaskRun.task_type == "maintenance_action")
                        .where(TaskRun.status == "success")
                        .order_by(TaskRun.ended_at.desc(), TaskRun.id.desc())
                    )
                    if isinstance(candidate, dict) and candidate.get("target_key") == NEWS_STOCK_LINKING_ACTION_KEY
                ),
                None,
            )
            previous_end = None
            if isinstance(previous_payload, dict) and previous_payload.get("target_key") == NEWS_STOCK_LINKING_ACTION_KEY:
                raw_previous_end = previous_payload.get("window_end")
                if raw_previous_end not in (None, ""):
                    try:
                        previous_end = datetime.fromisoformat(str(raw_previous_end).replace("Z", "+00:00"))
                    except ValueError as exc:
                        raise WebAppError(
                            status_code=422,
                            code="validation_error",
                            message="新闻关联成功游标的 window_end 无法解析",
                        ) from exc
            if previous_end is None:
                mode = "full"
                overlap_seconds = 0
            else:
                if previous_end.tzinfo is None:
                    previous_end = previous_end.replace(tzinfo=timezone.utc)
                window_start = previous_end - timedelta(seconds=overlap_seconds)

        return {
            **payload,
            "target_key": NEWS_STOCK_LINKING_ACTION_KEY,
            "mode": mode,
            "window_start": window_start.isoformat() if window_start else None,
            "window_end": window_end.isoformat(),
            "overlap_seconds": overlap_seconds,
            "rule_version": str(payload.get("rule_version") or NEWS_STOCK_RULE_VERSION),
            "news_scope": "all",
        }

    @staticmethod
    def _ensure_news_stock_linking_not_running(session: Session, payload: dict[str, Any]) -> None:
        if payload.get("task_type") != "maintenance_action" or payload.get("target_key") != NEWS_STOCK_LINKING_ACTION_KEY:
            return
        if session.get_bind().dialect.name == "postgresql":
            session.execute(select(func.pg_advisory_xact_lock(NEWS_STOCK_LINKING_ADVISORY_LOCK_KEY)))
        active_runs = session.scalars(
            select(TaskRun)
            .where(TaskRun.task_type == "maintenance_action")
            .where(TaskRun.status.in_(("queued", "running", "canceling")))
        ).all()
        if any((run.request_payload_json or {}).get("target_key") == NEWS_STOCK_LINKING_ACTION_KEY for run in active_runs):
            raise WebAppError(status_code=409, code="conflict", message="新闻关联维护任务已有 queued/running/canceling 任务")

    @staticmethod
    def preflight_dataset_context(session: Session, *, context: TaskRunCreateContext) -> None:
        if context.task_type != "dataset_action" or context.resource_key is None:
            return
        time_input = dict(context.time_input or {})
        request = DatasetActionRequest(
            dataset_key=context.resource_key,
            action=context.action,
            time_input=DatasetTimeInput(
                mode=str(time_input.get("mode") or "none").strip() or "none",
                trade_date=TaskRunCommandService._optional_date(time_input.get("trade_date")),
                ann_date=TaskRunCommandService._optional_date(time_input.get("ann_date")),
                start_date=TaskRunCommandService._optional_date(time_input.get("start_date")),
                end_date=TaskRunCommandService._optional_date(time_input.get("end_date")),
                month=TaskRunCommandService._optional_text(time_input.get("month")),
                start_month=TaskRunCommandService._optional_text(time_input.get("start_month")),
                end_month=TaskRunCommandService._optional_text(time_input.get("end_month")),
                date_field=TaskRunCommandService._optional_text(time_input.get("date_field")),
            ),
            filters=dict(context.filters or {}),
            trigger_source=context.trigger_source,
            requested_by_user_id=context.requested_by_user_id,
        )
        DatasetActionResolver(session).build_plan(request)

    def validate_schedule_execution(
        self,
        session: Session,
        *,
        target_type: str,
        target_key: str,
        params_json: dict[str, Any],
        schedule_id: int | None,
        calendar_policy: str | None,
        scheduled_at: datetime,
        timezone_name: str,
    ) -> None:
        try:
            context = self.build_schedule_task_context(
                session,
                target_type=target_type,
                target_key=target_key,
                params_json=params_json,
                trigger_source="schedule",
                requested_by_user_id=None,
                schedule_id=schedule_id,
                calendar_policy=calendar_policy,
                scheduled_at=scheduled_at,
                timezone_name=timezone_name,
            )
        except ScheduleWindowAlreadyCovered:
            return
        try:
            self.preflight_dataset_context(session, context=context)
        except IngestionError as exc:
            presentation = present_ingestion_error(exc.structured_error)
            raise WebAppError(
                status_code=422,
                code=exc.structured_error.error_code,
                message=presentation.operator_message,
            ) from exc

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
        session: Session | None,
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
                    session=session,
                    definition=definition,
                    target_key=target_key,
                    params_json=params_json,
                    calendar_policy=calendar_policy,
                    scheduled_at=scheduled_at,
                    timezone_name=timezone_name,
                    schedule_id=schedule_id,
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

    def _resolve_dataset_action_schedule_time_input(
        self,
        *,
        session: Session | None,
        definition: DatasetDefinition,
        target_key: str,
        params_json: dict[str, Any],
        calendar_policy: str | None,
        scheduled_at: datetime | None,
        timezone_name: str | None,
        schedule_id: int | None = None,
    ) -> dict[str, Any]:
        time_input = self._resolve_schedule_time_input(
            target_type="dataset_action",
            target_key=target_key,
            params_json=params_json,
        )
        normalized_policy = str(calendar_policy or "").strip() or None
        if normalized_policy is None:
            return time_input
        if normalized_policy not in {
            MONTHLY_LAST_DAY_POLICY,
            MONTHLY_LAST_TRADING_DAY_POLICY,
            MONTHLY_WINDOW_CURRENT_MONTH_POLICY,
            TRIGGER_DAY_SINGLE_RANGE_POLICY,
            TRIGGER_DAY_POINT_POLICY,
            LATEST_COMPLETED_CALENDAR_QUARTER_POLICY,
            SINCE_LAST_SUCCESS_DAY_RANGE_POLICY,
        }:
            raise WebAppError(status_code=422, code="validation_error", message=f"不支持的日期策略：{normalized_policy}")
        policy_rule = DatasetScheduleTimePolicyResolver().rule_for_policy(
            definition=definition,
            action="maintain",
            policy=normalized_policy,
        )
        if policy_rule is None:
            raise WebAppError(status_code=422, code="validation_error", message="数据集 Definition 未声明该日期策略")
        if normalized_policy == MONTHLY_LAST_DAY_POLICY:
            if definition.date_model.bucket_rule != "month_last_calendar_day":
                raise WebAppError(status_code=422, code="validation_error", message="每月最后一天策略只支持自然月末数据集")
            if self._has_fixed_trade_date(params_json):
                raise WebAppError(status_code=422, code="validation_error", message="每月最后一天策略不能与固定维护日期混用")
            if scheduled_at is None:
                raise WebAppError(status_code=422, code="validation_error", message="每月最后一天策略缺少计划触发时间")
            trade_date = self._month_last_day_for_schedule(scheduled_at=scheduled_at, timezone_name=timezone_name)
            return {
                **dict(time_input or {}),
                "mode": "point",
                "trade_date": trade_date.isoformat(),
            }
        if normalized_policy == MONTHLY_LAST_TRADING_DAY_POLICY:
            if definition.date_model.bucket_rule != "month_last_open_day":
                raise WebAppError(status_code=422, code="validation_error", message="每月最后交易日策略只支持交易日月末数据集")
            if self._has_fixed_trade_date(params_json):
                raise WebAppError(status_code=422, code="validation_error", message="每月最后交易日策略不能与固定维护日期混用")
            if scheduled_at is None:
                raise WebAppError(status_code=422, code="validation_error", message="每月最后交易日策略缺少计划触发时间")
            if session is None:
                raise WebAppError(status_code=422, code="validation_error", message="每月最后交易日策略缺少数据库会话")
            trade_date = self._month_last_open_day_for_schedule(
                session=session,
                scheduled_at=scheduled_at,
                timezone_name=timezone_name,
            )
            return {
                **dict(time_input or {}),
                "mode": "point",
                "trade_date": trade_date.isoformat(),
            }
        if normalized_policy == TRIGGER_DAY_SINGLE_RANGE_POLICY:
            if self._has_declared_time_input(params_json, definition=definition):
                raise WebAppError(
                    status_code=422,
                    code="validation_error",
                    message="触发日单日区间策略不能与固定维护日期或窗口混用",
                )
            if scheduled_at is None:
                raise WebAppError(status_code=422, code="validation_error", message="触发日单日区间策略缺少计划触发时间")
            trigger_date = self._natural_day_for_schedule(
                scheduled_at=scheduled_at,
                timezone_name=timezone_name,
            )
            return {
                **dict(time_input or {}),
                "mode": "range",
                "start_date": trigger_date.isoformat(),
                "end_date": trigger_date.isoformat(),
            }
        if normalized_policy == TRIGGER_DAY_POINT_POLICY:
            if self._has_declared_time_input(params_json, definition=definition):
                raise WebAppError(status_code=422, code="validation_error", message="触发日单日策略不能与固定维护日期或窗口混用")
            if scheduled_at is None:
                raise WebAppError(status_code=422, code="validation_error", message="触发日单日策略缺少计划触发时间")
            trigger_date = self._natural_day_for_schedule(
                scheduled_at=scheduled_at,
                timezone_name=timezone_name,
            )
            generated_field = policy_rule.generated_time_field
            if generated_field not in {"trade_date", "ann_date"}:
                raise WebAppError(status_code=422, code="validation_error", message="数据集 Definition 的触发日字段声明非法")
            generated_time_input = {
                **dict(time_input or {}),
                "mode": "point",
                generated_field: trigger_date.isoformat(),
            }
            if generated_field != "trade_date":
                generated_time_input["date_field"] = generated_field
            return generated_time_input
        if normalized_policy == LATEST_COMPLETED_CALENDAR_QUARTER_POLICY:
            if self._has_declared_time_input(params_json, definition=definition):
                raise WebAppError(status_code=422, code="validation_error", message="最近已完成季度策略不能与固定报告期混用")
            if scheduled_at is None:
                raise WebAppError(status_code=422, code="validation_error", message="最近已完成季度策略缺少计划触发时间")
            period = self._latest_completed_quarter_for_schedule(
                scheduled_at=scheduled_at,
                timezone_name=timezone_name,
            )
            return {**dict(time_input or {}), "mode": "point", "trade_date": period.isoformat()}
        if normalized_policy == SINCE_LAST_SUCCESS_DAY_RANGE_POLICY:
            if self._has_declared_time_input(params_json, definition=definition):
                raise WebAppError(
                    status_code=422,
                    code="validation_error",
                    message="成功游标日区间策略不能与固定维护日期或窗口混用",
                )
            if scheduled_at is None:
                raise WebAppError(status_code=422, code="validation_error", message="成功游标日区间策略缺少计划触发时间")
            policy_params = params_json.get("schedule_policy_params")
            if not isinstance(policy_params, dict):
                raise WebAppError(status_code=422, code="validation_error", message="成功游标日区间策略缺少参数")
            initial_start_date = self._optional_date(policy_params.get("initial_start_date"))
            if initial_start_date is None:
                raise WebAppError(status_code=422, code="validation_error", message="成功游标日区间策略缺少首次覆盖开始日期")
            target_end = self._natural_day_for_schedule(
                scheduled_at=scheduled_at,
                timezone_name=timezone_name,
            ) - timedelta(days=1)
            last_success_end = self._last_successful_schedule_end_date(
                session=session,
                schedule_id=schedule_id,
                resource_key=definition.dataset_key,
                action="maintain",
            )
            cursor_start = last_success_end + timedelta(days=1) if last_success_end is not None else initial_start_date
            start_date = max(initial_start_date, cursor_start)
            if start_date > target_end:
                raise ScheduleWindowAlreadyCovered(
                    f"schedule {schedule_id or 'new'} already covers {target_end.isoformat()}"
                )
            return {
                **dict(time_input or {}),
                "mode": "range",
                "start_date": start_date.isoformat(),
                "end_date": target_end.isoformat(),
            }
        if not self._supports_month_window_policy(definition):
            raise WebAppError(status_code=422, code="validation_error", message="自然月窗口策略只支持月窗口数据集")
        if self._has_explicit_time_boundary(params_json):
            raise WebAppError(status_code=422, code="validation_error", message="自然月窗口策略不能与固定维护日期或窗口混用")
        if scheduled_at is None:
            raise WebAppError(status_code=422, code="validation_error", message="自然月窗口策略缺少计划触发时间")
        month_key = self._month_key_for_schedule(scheduled_at=scheduled_at, timezone_name=timezone_name)
        return {
            **dict(time_input or {}),
            "mode": "range",
            "start_month": month_key,
            "end_month": month_key,
        }

    def _validate_context(self, context: TaskRunCreateContext) -> None:
        external = self._external_task_definitions.get(context.task_type)
        if external is not None:
            external.validate_context(context)
            return
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
            TaskRunCommandService._validate_dataset_time_input_fields(
                definition=definition,
                time_input=dict(context.time_input or {}),
            )
            TaskRunCommandService._validate_required_dataset_filters(definition, context.filters)
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

    def _resolve_title(self, context: TaskRunCreateContext) -> str:
        external = self._external_task_definitions.get(context.task_type)
        if external is not None:
            return external.resolve_title(context)
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
    def _has_declared_time_input(params_json: dict[str, Any], *, definition: DatasetDefinition) -> bool:
        time_keys = {
            "trade_date",
            "ann_date",
            "month",
            "start_date",
            "end_date",
            "start_month",
            "end_month",
            *(field.name for field in definition.input_model.time_fields),
        }
        if any(params_json.get(key) not in (None, "") for key in time_keys):
            return True
        time_input = params_json.get("time_input")
        return isinstance(time_input, dict) and any(time_input.get(key) not in (None, "") for key in time_keys)

    @staticmethod
    def _validate_dataset_time_input_fields(
        *,
        definition: DatasetDefinition,
        time_input: dict[str, Any],
    ) -> None:
        declared_fields = {field.name for field in definition.input_model.time_fields}
        if definition.date_model.date_axis in {"month_key", "month_window"}:
            declared_fields.update({"month", "start_month", "end_month"})
        if definition.date_model.date_axis == "week_key":
            declared_fields.update({"week", "start_week", "end_week"})
        supplied_fields = {
            key
            for key, value in time_input.items()
            if key not in {"mode", "date_field"} and value not in (None, "")
        }
        undeclared_fields = sorted(supplied_fields - declared_fields)
        if undeclared_fields:
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message=f"{definition.display_name} 不支持时间字段：{'、'.join(undeclared_fields)}",
            )

    @staticmethod
    def _month_last_day_for_schedule(*, scheduled_at: datetime, timezone_name: str | None) -> date:
        local_scheduled_at = TaskRunCommandService._local_scheduled_at(scheduled_at=scheduled_at, timezone_name=timezone_name)
        last_day = monthrange(local_scheduled_at.year, local_scheduled_at.month)[1]
        return date(local_scheduled_at.year, local_scheduled_at.month, last_day)

    @staticmethod
    def _month_last_open_day_for_schedule(
        *,
        session: Session,
        scheduled_at: datetime,
        timezone_name: str | None,
    ) -> date:
        local_scheduled_at = TaskRunCommandService._local_scheduled_at(scheduled_at=scheduled_at, timezone_name=timezone_name)
        return TaskRunCommandService._resolve_month_last_open_day(
            session=session,
            year=local_scheduled_at.year,
            month=local_scheduled_at.month,
        )

    @staticmethod
    def _resolve_month_last_open_day(*, session: Session, year: int, month: int) -> date:
        month_end_day = monthrange(year, month)[1]
        month_start = date(year, month, 1)
        month_end = date(year, month, month_end_day)
        exchange = get_settings().default_exchange
        stmt = (
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == exchange,
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date >= month_start,
                TradeCalendar.trade_date <= month_end,
            )
            .order_by(desc(TradeCalendar.trade_date))
            .limit(1)
        )
        resolved = session.scalar(stmt)
        if resolved is None:
            raise WebAppError(status_code=422, code="validation_error", message=f"{year}-{month:02d} 未找到开市交易日")
        return resolved

    @staticmethod
    def _month_key_for_schedule(*, scheduled_at: datetime, timezone_name: str | None) -> str:
        local_scheduled_at = TaskRunCommandService._local_scheduled_at(scheduled_at=scheduled_at, timezone_name=timezone_name)
        return f"{local_scheduled_at.year}{local_scheduled_at.month:02d}"

    @staticmethod
    def _natural_day_for_schedule(*, scheduled_at: datetime, timezone_name: str | None) -> date:
        local_scheduled_at = TaskRunCommandService._local_scheduled_at(scheduled_at=scheduled_at, timezone_name=timezone_name)
        return local_scheduled_at.date()

    @staticmethod
    def _last_successful_schedule_end_date(
        *,
        session: Session | None,
        schedule_id: int | None,
        resource_key: str,
        action: str,
    ) -> date | None:
        if session is None or schedule_id is None:
            return None
        values = session.scalars(
            select(TaskRun.time_input_json)
            .where(TaskRun.schedule_id == schedule_id)
            .where(TaskRun.resource_key == resource_key)
            .where(TaskRun.action == action)
            .where(TaskRun.status == "success")
        ).all()
        resolved: list[date] = []
        for value in values:
            if not isinstance(value, dict):
                continue
            end_date = TaskRunCommandService._optional_date(value.get("end_date"))
            if end_date is not None:
                resolved.append(end_date)
        return max(resolved) if resolved else None

    @staticmethod
    def _optional_date(value: Any) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise WebAppError(status_code=422, code="validation_error", message="日期必须是 YYYY-MM-DD") from exc

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _latest_completed_quarter_for_schedule(*, scheduled_at: datetime, timezone_name: str | None) -> date:
        trigger_date = TaskRunCommandService._natural_day_for_schedule(
            scheduled_at=scheduled_at,
            timezone_name=timezone_name,
        )
        candidates = [
            date(year, month, day)
            for year in (trigger_date.year - 1, trigger_date.year)
            for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))
            if date(year, month, day) < trigger_date
        ]
        return max(candidates)

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
            "schedule_policy_params",
        }
        return {key: value for key, value in params_json.items() if key not in reserved}

    @staticmethod
    def _validate_required_dataset_filters(definition: DatasetDefinition, filters: dict[str, Any]) -> None:
        missing: list[str] = []
        for field in definition.input_model.filters:
            if not field.required:
                continue
            value = filters.get(field.name, field.default)
            if value in (None, "", []):
                missing.append(field.display_label)
        if missing:
            joined = "、".join(missing)
            raise WebAppError(status_code=422, code="validation_error", message=f"{definition.display_name} 缺少必填参数：{joined}")

    @staticmethod
    def _dataset_action_request_payload(params_json: dict[str, Any]) -> dict[str, Any]:
        payload = dict(params_json or {})
        payload.pop("target_type", None)
        payload.pop("target_key", None)
        payload.pop("dataset_key", None)
        payload.pop("action", None)
        payload.pop("schedule_policy_params", None)
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
