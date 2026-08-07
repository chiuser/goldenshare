from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.schedule_probe_binding_service import ScheduleProbeBindingService
from src.ops.services.schedule_planner import (
    compute_next_run_at,
    ensure_schedule_type,
    ensure_timezone,
    normalize_schedule_datetime,
    preview_schedule_runs,
)
from src.ops.services.task_run_service import TaskRunCommandService
from src.ops.action_catalog import (
    action_is_schedulable,
    get_action_display_name,
    get_maintenance_action,
    get_workflow_definition,
)
from src.app.exceptions import WebAppError
from src.foundation.datasets.registry import get_dataset_definition_by_action_key
from src.ops.services.dataset_schedule_time_policy_resolver import DatasetScheduleTimePolicyResolver


MONTHLY_LAST_DAY_POLICY = "monthly_last_day"
MONTHLY_LAST_TRADING_DAY_POLICY = "monthly_last_trading_day"
MONTHLY_WINDOW_CURRENT_MONTH_POLICY = "monthly_window_current_month"
TRIGGER_DAY_SINGLE_RANGE_POLICY = "trigger_day_single_range"
TRIGGER_DAY_POINT_POLICY = "trigger_day_point"
MIN_INTRADAY_INTERVAL_MINUTES = 3
SUPPORTED_CALENDAR_POLICIES = {
    MONTHLY_LAST_DAY_POLICY,
    MONTHLY_LAST_TRADING_DAY_POLICY,
    MONTHLY_WINDOW_CURRENT_MONTH_POLICY,
    TRIGGER_DAY_SINGLE_RANGE_POLICY,
    TRIGGER_DAY_POINT_POLICY,
}
FALLBACK_PROBE_EFFECTIVE_TASK_STATUSES = ("queued", "running", "canceling", "success", "partial_success")


class OperationsScheduleService:
    def __init__(self) -> None:
        self.task_run_service = TaskRunCommandService()
        self.probe_binding_service = ScheduleProbeBindingService()

    def create_schedule(
        self,
        session: Session,
        *,
        target_type: str,
        target_key: str,
        display_name: str,
        schedule_type: str,
        trigger_mode: str,
        cron_expr: str | None,
        timezone_name: str,
        calendar_policy: str | None,
        probe_config_json: dict | None,
        params_json: dict | None,
        retry_policy_json: dict | None,
        concurrency_policy_json: dict | None,
        next_run_at: datetime | None,
        created_by_user_id: int,
    ) -> OpsSchedule:
        self._validate_target(target_type, target_key)
        normalized_params = dict(params_json or {})
        ensure_schedule_type(schedule_type)
        ensure_timezone(timezone_name)
        normalized_calendar_policy = self._normalize_calendar_policy(calendar_policy)
        self._validate_calendar_policy(
            target_type=target_type,
            target_key=target_key,
            schedule_type=schedule_type,
            cron_expr=cron_expr,
            calendar_policy=normalized_calendar_policy,
            params_json=normalized_params,
        )
        self.task_run_service.validate_schedule_target(
            target_type=target_type,
            target_key=target_key,
            params_json=normalized_params,
        )
        trigger_mode = self._normalize_trigger_mode(trigger_mode)
        normalized_next_run_at = self._resolve_next_run_at(
            session=session,
            schedule_type=schedule_type,
            cron_expr=cron_expr,
            timezone_name=timezone_name,
            next_run_at=next_run_at,
            calendar_policy=normalized_calendar_policy,
        )

        schedule = OpsSchedule(
            target_type=target_type,
            target_key=target_key,
            display_name=display_name.strip() or self._default_display_name(target_type, target_key),
            status="active",
            schedule_type=schedule_type,
            trigger_mode=trigger_mode,
            cron_expr=cron_expr,
            timezone=timezone_name,
            calendar_policy=normalized_calendar_policy,
            probe_config_json=dict(probe_config_json or {}),
            params_json=normalized_params,
            retry_policy_json=dict(retry_policy_json or {}),
            concurrency_policy_json=dict(concurrency_policy_json or {}),
            next_run_at=normalized_next_run_at,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=created_by_user_id,
        )
        session.add(schedule)
        session.flush()
        self.probe_binding_service.sync_for_schedule(session, schedule=schedule, actor_user_id=created_by_user_id)
        self._record_revision(
            session,
            object_id=str(schedule.id),
            action="created",
            before_json=None,
            after_json=self._snapshot(schedule),
            changed_by_user_id=created_by_user_id,
        )
        session.commit()
        session.refresh(schedule)
        return schedule

    def update_schedule(
        self,
        session: Session,
        *,
        schedule_id: int,
        changes: dict,
        updated_by_user_id: int,
    ) -> OpsSchedule:
        schedule = session.scalar(select(OpsSchedule).where(OpsSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="自动任务不存在")

        before = self._snapshot(schedule)
        changed_fields = set(changes)

        if "target_type" in changed_fields or "target_key" in changed_fields:
            target_type = changes.get("target_type", schedule.target_type)
            target_key = changes.get("target_key", schedule.target_key)
            self._validate_target(target_type, target_key)
            schedule.target_type = target_type
            schedule.target_key = target_key
            if "display_name" not in changed_fields and schedule.display_name == self._default_display_name(before["target_type"], before["target_key"]):
                schedule.display_name = self._default_display_name(target_type, target_key)

        if "display_name" in changed_fields:
            display_name = str(changes["display_name"]).strip()
            if not display_name:
                raise WebAppError(status_code=422, code="validation_error", message="自动任务名称不能为空")
            schedule.display_name = display_name

        if "schedule_type" in changed_fields:
            ensure_schedule_type(changes["schedule_type"])
            schedule.schedule_type = changes["schedule_type"]
        if "trigger_mode" in changed_fields:
            schedule.trigger_mode = self._normalize_trigger_mode(changes["trigger_mode"])
        if "cron_expr" in changed_fields:
            schedule.cron_expr = changes["cron_expr"]
        if "timezone" in changed_fields:
            ensure_timezone(changes["timezone"])
            schedule.timezone = changes["timezone"]
        if "calendar_policy" in changed_fields:
            schedule.calendar_policy = self._normalize_calendar_policy(changes["calendar_policy"])
        if "probe_config" in changed_fields:
            schedule.probe_config_json = dict(changes["probe_config"] or {})
        if "params_json" in changed_fields:
            schedule.params_json = dict(changes["params_json"] or {})
        if "retry_policy_json" in changed_fields:
            schedule.retry_policy_json = dict(changes["retry_policy_json"] or {})
        if "concurrency_policy_json" in changed_fields:
            schedule.concurrency_policy_json = dict(changes["concurrency_policy_json"] or {})

        if "next_run_at" in changed_fields:
            explicit_next_run = normalize_schedule_datetime(changes["next_run_at"], field_name="next_run_at")
            if explicit_next_run is None and schedule.status == "active" and schedule.schedule_type != "once":
                explicit_next_run = self._resolve_next_run_at(
                    session=session,
                    schedule_type=schedule.schedule_type,
                    cron_expr=schedule.cron_expr,
                    timezone_name=schedule.timezone,
                    next_run_at=None,
                    calendar_policy=schedule.calendar_policy,
                )
            schedule.next_run_at = explicit_next_run
        elif {"schedule_type", "cron_expr", "timezone", "calendar_policy"} & changed_fields and schedule.status == "active":
            schedule.next_run_at = self._resolve_next_run_at(
                session=session,
                schedule_type=schedule.schedule_type,
                cron_expr=schedule.cron_expr,
                timezone_name=schedule.timezone,
                next_run_at=None if schedule.schedule_type == "cron" else schedule.next_run_at,
                calendar_policy=schedule.calendar_policy,
            )

        if schedule.schedule_type == "once" and schedule.status == "active" and schedule.next_run_at is None:
            raise WebAppError(status_code=422, code="validation_error", message="单次排程必须填写下次运行时间")

        schedule.calendar_policy = self._normalize_calendar_policy(schedule.calendar_policy)
        self._validate_calendar_policy(
            target_type=schedule.target_type,
            target_key=schedule.target_key,
            schedule_type=schedule.schedule_type,
            cron_expr=schedule.cron_expr,
            calendar_policy=schedule.calendar_policy,
            params_json=dict(schedule.params_json or {}),
        )
        self.task_run_service.validate_schedule_target(
            target_type=schedule.target_type,
            target_key=schedule.target_key,
            params_json=dict(schedule.params_json or {}),
        )

        schedule.updated_by_user_id = updated_by_user_id
        self.probe_binding_service.sync_for_schedule(session, schedule=schedule, actor_user_id=updated_by_user_id)
        after = self._snapshot(schedule)
        if before == after:
            session.commit()
            session.refresh(schedule)
            return schedule

        self._record_revision(
            session,
            object_id=str(schedule.id),
            action="updated",
            before_json=before,
            after_json=after,
            changed_by_user_id=updated_by_user_id,
        )
        session.commit()
        session.refresh(schedule)
        return schedule

    def pause_schedule(self, session: Session, *, schedule_id: int, updated_by_user_id: int) -> OpsSchedule:
        schedule = session.scalar(select(OpsSchedule).where(OpsSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="自动任务不存在")
        if schedule.status == "paused":
            session.refresh(schedule)
            return schedule

        before = self._snapshot(schedule)
        schedule.status = "paused"
        schedule.updated_by_user_id = updated_by_user_id
        self.probe_binding_service.sync_for_schedule(session, schedule=schedule, actor_user_id=updated_by_user_id)
        self._record_revision(
            session,
            object_id=str(schedule.id),
            action="paused",
            before_json=before,
            after_json=self._snapshot(schedule),
            changed_by_user_id=updated_by_user_id,
        )
        session.commit()
        session.refresh(schedule)
        return schedule

    def resume_schedule(self, session: Session, *, schedule_id: int, updated_by_user_id: int) -> OpsSchedule:
        schedule = session.scalar(select(OpsSchedule).where(OpsSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="自动任务不存在")
        if schedule.status == "active":
            session.refresh(schedule)
            return schedule

        schedule.calendar_policy = self._normalize_calendar_policy(schedule.calendar_policy)
        self._validate_calendar_policy(
            target_type=schedule.target_type,
            target_key=schedule.target_key,
            schedule_type=schedule.schedule_type,
            cron_expr=schedule.cron_expr,
            calendar_policy=schedule.calendar_policy,
            params_json=dict(schedule.params_json or {}),
        )
        self.task_run_service.validate_schedule_target(
            target_type=schedule.target_type,
            target_key=schedule.target_key,
            params_json=dict(schedule.params_json or {}),
        )
        before = self._snapshot(schedule)
        if schedule.schedule_type == "once":
            if schedule.next_run_at is None:
                raise WebAppError(
                    status_code=409,
                    code="conflict",
                    message="单次排程恢复前必须填写下次运行时间",
                )
        else:
            schedule.next_run_at = self._resolve_next_run_at(
                session=session,
                schedule_type=schedule.schedule_type,
                cron_expr=schedule.cron_expr,
                timezone_name=schedule.timezone,
                next_run_at=self._stored_datetime(schedule.next_run_at),
                calendar_policy=schedule.calendar_policy,
            )
        schedule.status = "active"
        schedule.updated_by_user_id = updated_by_user_id
        self.probe_binding_service.sync_for_schedule(session, schedule=schedule, actor_user_id=updated_by_user_id)
        self._record_revision(
            session,
            object_id=str(schedule.id),
            action="resumed",
            before_json=before,
            after_json=self._snapshot(schedule),
            changed_by_user_id=updated_by_user_id,
        )
        session.commit()
        session.refresh(schedule)
        return schedule

    def delete_schedule(self, session: Session, *, schedule_id: int, deleted_by_user_id: int) -> int:
        schedule = session.scalar(select(OpsSchedule).where(OpsSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="自动任务不存在")

        before = self._snapshot(schedule)
        if schedule.status == "active":
            schedule.status = "paused"
            schedule.updated_by_user_id = deleted_by_user_id
            self._record_revision(
                session,
                object_id=str(schedule.id),
                action="paused",
                before_json=before,
                after_json=self._snapshot(schedule),
                changed_by_user_id=deleted_by_user_id,
            )
            before = self._snapshot(schedule)
        self._record_revision(
            session,
            object_id=str(schedule.id),
            action="deleted",
            before_json=before,
            after_json=None,
            changed_by_user_id=deleted_by_user_id,
        )
        session.execute(delete(ProbeRule).where(ProbeRule.schedule_id == schedule.id))
        session.delete(schedule)
        session.commit()
        return schedule_id

    def enqueue_due_schedules(self, session: Session, *, now: datetime | None = None, limit: int = 100) -> list[TaskRun]:
        current_time = now or datetime.now(timezone.utc)
        stmt = (
            select(OpsSchedule)
            .where(OpsSchedule.status == "active")
            .where(OpsSchedule.trigger_mode != "probe")
            .where(OpsSchedule.next_run_at.is_not(None))
            .where(OpsSchedule.next_run_at <= current_time)
            .order_by(OpsSchedule.next_run_at.asc(), OpsSchedule.id.asc())
            .limit(limit)
        )
        schedules = list(session.scalars(stmt))
        task_runs: list[TaskRun] = []
        for schedule in schedules:
            self._validate_calendar_policy(
                target_type=schedule.target_type,
                target_key=schedule.target_key,
                schedule_type=schedule.schedule_type,
                cron_expr=schedule.cron_expr,
                calendar_policy=self._normalize_calendar_policy(schedule.calendar_policy),
                params_json=dict(schedule.params_json or {}),
            )
            if schedule.trigger_mode == "schedule_probe_fallback" and self._has_effective_probe_task_for_schedule_day(
                session,
                schedule=schedule,
                current_time=current_time,
            ):
                self._advance_schedule_after_skipped_due_run(session, schedule=schedule, current_time=current_time)
                continue
            scheduled_at = self._stored_datetime(schedule.next_run_at) or current_time
            task_run = self.task_run_service.create_from_schedule_target(
                session,
                target_type=schedule.target_type,
                target_key=schedule.target_key,
                params_json=dict(schedule.params_json or {}),
                trigger_source="scheduled",
                requested_by_user_id=None,
                schedule_id=schedule.id,
                calendar_policy=schedule.calendar_policy,
                scheduled_at=scheduled_at,
                timezone_name=schedule.timezone,
            )
            schedule.last_triggered_at = current_time
            if schedule.schedule_type == "once":
                schedule.status = "paused"
                schedule.next_run_at = None
            else:
                schedule.next_run_at = self._resolve_next_run_at(
                    session=session,
                    schedule_type=schedule.schedule_type,
                    cron_expr=schedule.cron_expr,
                    timezone_name=schedule.timezone,
                    next_run_at=None,
                    calendar_policy=schedule.calendar_policy,
                    after=current_time,
                )
            session.commit()
            task_runs.append(task_run)
        return task_runs

    def _has_effective_probe_task_for_schedule_day(
        self,
        session: Session,
        *,
        schedule: OpsSchedule,
        current_time: datetime,
    ) -> bool:
        if schedule.id is None:
            return False
        schedule_tz = ensure_timezone(schedule.timezone)
        normalized_now = current_time if current_time.tzinfo is not None else current_time.replace(tzinfo=timezone.utc)
        local_day = normalized_now.astimezone(schedule_tz).date()
        local_start = datetime.combine(local_day, time.min, tzinfo=schedule_tz)
        local_end = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=schedule_tz)
        stmt = (
            select(TaskRun.id)
            .where(TaskRun.schedule_id == schedule.id)
            .where(TaskRun.trigger_source == "probe")
            .where(TaskRun.status.in_(FALLBACK_PROBE_EFFECTIVE_TASK_STATUSES))
            .where(TaskRun.requested_at >= local_start.astimezone(timezone.utc))
            .where(TaskRun.requested_at < local_end.astimezone(timezone.utc))
            .limit(1)
        )
        return session.scalar(stmt) is not None

    def _advance_schedule_after_skipped_due_run(
        self,
        session: Session,
        *,
        schedule: OpsSchedule,
        current_time: datetime,
    ) -> None:
        if schedule.schedule_type == "once":
            schedule.status = "paused"
            schedule.next_run_at = None
        else:
            schedule.next_run_at = self._resolve_next_run_at(
                session=session,
                schedule_type=schedule.schedule_type,
                cron_expr=schedule.cron_expr,
                timezone_name=schedule.timezone,
                next_run_at=None,
                calendar_policy=schedule.calendar_policy,
                after=current_time,
            )
        session.commit()

    def preview_schedule(
        self,
        session: Session,
        *,
        schedule_type: str,
        cron_expr: str | None,
        timezone_name: str,
        next_run_at: datetime | None,
        calendar_policy: str | None,
        count: int,
    ) -> list[datetime]:
        normalized_policy = self._normalize_calendar_policy(calendar_policy)
        if normalized_policy == MONTHLY_LAST_TRADING_DAY_POLICY:
            if schedule_type != "cron":
                raise WebAppError(status_code=422, code="validation_error", message="每月最后交易日策略只支持周期执行")
            runs: list[datetime] = []
            cursor = datetime.now(timezone.utc)
            for _ in range(max(1, min(count, 10))):
                next_occurrence = self._next_monthly_last_trading_day_occurrence(
                    session=session,
                    cron_expr=cron_expr,
                    timezone_name=timezone_name,
                    after=cursor,
                )
                runs.append(next_occurrence)
                cursor = next_occurrence.replace(second=0, microsecond=0) + timedelta(minutes=1)
            return runs
        return preview_schedule_runs(
            schedule_type=schedule_type,
            cron_expr=cron_expr,
            timezone_name=timezone_name,
            next_run_at=next_run_at,
            calendar_policy=calendar_policy,
            count=count,
        )

    @staticmethod
    def _snapshot(schedule: OpsSchedule) -> dict:
        return {
            "id": schedule.id,
            "target_type": schedule.target_type,
            "target_key": schedule.target_key,
            "display_name": schedule.display_name,
            "status": schedule.status,
            "schedule_type": schedule.schedule_type,
            "trigger_mode": schedule.trigger_mode,
            "cron_expr": schedule.cron_expr,
            "timezone": schedule.timezone,
            "calendar_policy": schedule.calendar_policy,
            "probe_config": dict(schedule.probe_config_json or {}),
            "params_json": dict(schedule.params_json or {}),
            "retry_policy_json": dict(schedule.retry_policy_json or {}),
            "concurrency_policy_json": dict(schedule.concurrency_policy_json or {}),
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
            "last_triggered_at": schedule.last_triggered_at.isoformat() if schedule.last_triggered_at else None,
        }

    @staticmethod
    def _record_revision(
        session: Session,
        *,
        object_id: str,
        action: str,
        before_json: dict | None,
        after_json: dict | None,
        changed_by_user_id: int,
    ) -> None:
        session.add(
            ConfigRevision(
                object_type="schedule",
                object_id=object_id,
                action=action,
                before_json=before_json,
                after_json=after_json,
                changed_by_user_id=changed_by_user_id,
                changed_at=datetime.now(timezone.utc),
            )
        )

    @staticmethod
    def _default_display_name(target_type: str, target_key: str) -> str:
        display_name = get_action_display_name(target_type, target_key)
        if display_name is None:
            raise WebAppError(status_code=422, code="validation_error", message="自动任务目标缺少显示名称")
        return display_name

    @staticmethod
    def _validate_target(target_type: str, target_key: str) -> None:
        if target_type == "dataset_action":
            try:
                get_dataset_definition_by_action_key(target_key)
            except KeyError as exc:
                raise WebAppError(status_code=422, code="validation_error", message="数据集维护动作不存在") from exc
            if not action_is_schedulable(target_type, target_key):
                raise WebAppError(status_code=422, code="validation_error", message="所选目标不支持自动任务")
            return
        if target_type == "maintenance_action":
            action = get_maintenance_action(target_key)
            if action is None:
                raise WebAppError(status_code=422, code="validation_error", message="系统维护动作不存在")
        elif target_type == "workflow":
            if get_workflow_definition(target_key) is None:
                raise WebAppError(status_code=404, code="not_found", message="自动流程不存在")
        else:
            raise WebAppError(status_code=422, code="validation_error", message="不支持的自动任务目标类型")
        if not action_is_schedulable(target_type, target_key):
            raise WebAppError(status_code=422, code="validation_error", message="所选目标不支持自动任务")

    def _resolve_next_run_at(
        self,
        *,
        session: Session,
        schedule_type: str,
        cron_expr: str | None,
        timezone_name: str,
        next_run_at: datetime | None,
        calendar_policy: str | None,
        after: datetime | None = None,
    ) -> datetime | None:
        normalized = normalize_schedule_datetime(next_run_at, field_name="next_run_at")
        if normalized is not None:
            return normalized
        if schedule_type == "once":
            raise WebAppError(status_code=422, code="validation_error", message="单次排程必须填写下次运行时间")
        effective_after = after or datetime.now(timezone.utc)
        if calendar_policy == MONTHLY_LAST_TRADING_DAY_POLICY:
            return self._next_monthly_last_trading_day_occurrence(
                session=session,
                cron_expr=cron_expr,
                timezone_name=timezone_name,
                after=effective_after,
            )
        return compute_next_run_at(
            schedule_type=schedule_type,
            timezone_name=timezone_name,
            cron_expr=cron_expr,
            after=effective_after,
            calendar_policy=calendar_policy,
        )

    @staticmethod
    def _normalize_trigger_mode(value: str | None) -> str:
        mode = str(value or "schedule").strip().lower()
        if mode not in {"schedule", "probe", "schedule_probe_fallback"}:
            raise WebAppError(status_code=422, code="validation_error", message=f"不支持的触发方式：{mode}")
        return mode

    @staticmethod
    def _stored_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _normalize_calendar_policy(value: str | None) -> str | None:
        normalized = str(value or "").strip() or None
        if normalized is None:
            return None
        if normalized not in SUPPORTED_CALENDAR_POLICIES:
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message=f"不支持的日期策略：{normalized}",
            )
        return normalized

    @staticmethod
    def _validate_calendar_policy(
        *,
        target_type: str,
        target_key: str,
        schedule_type: str,
        cron_expr: str | None,
        calendar_policy: str | None,
        params_json: dict,
    ) -> None:
        if target_type != "dataset_action":
            if calendar_policy is None:
                return
            raise WebAppError(status_code=422, code="validation_error", message="日期策略只支持数据集维护任务")
        try:
            definition, action = get_dataset_definition_by_action_key(target_key)
        except KeyError as exc:
            raise WebAppError(status_code=422, code="validation_error", message="数据集维护动作不存在") from exc

        resolver = DatasetScheduleTimePolicyResolver()
        required_rule = resolver.required_policy_for_schedule(
            definition=definition,
            action=action,
            schedule_type=schedule_type,
            cron_expr=cron_expr,
        )
        if required_rule is not None and calendar_policy != required_rule.policy:
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message=f"该数据集周期任务必须使用系统声明的日期策略：{required_rule.policy}",
            )
        if calendar_policy is None:
            return
        rule = resolver.rule_for_policy(definition=definition, action=action, policy=calendar_policy)
        if rule is None:
            unsupported_messages = {
                MONTHLY_LAST_DAY_POLICY: "每月最后一天策略只支持自然月末数据集",
                MONTHLY_LAST_TRADING_DAY_POLICY: "每月最后交易日策略只支持交易日月末数据集",
                MONTHLY_WINDOW_CURRENT_MONTH_POLICY: "自然月窗口策略只支持月窗口数据集",
                TRIGGER_DAY_SINGLE_RANGE_POLICY: "触发日单日区间策略只支持自然日公告区间且仅支持区间维护的数据集",
                TRIGGER_DAY_POINT_POLICY: "触发日单日策略未由该数据集 Definition 声明",
            }
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message=unsupported_messages.get(calendar_policy, f"不支持的日期策略：{calendar_policy}"),
            )
        if schedule_type not in rule.schedule_types:
            labels = {
                MONTHLY_LAST_DAY_POLICY: "每月最后一天",
                MONTHLY_LAST_TRADING_DAY_POLICY: "每月最后交易日",
                MONTHLY_WINDOW_CURRENT_MONTH_POLICY: "自然月窗口",
                TRIGGER_DAY_SINGLE_RANGE_POLICY: "触发日单日区间",
                TRIGGER_DAY_POINT_POLICY: "触发日单日",
            }
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message=f"{labels[calendar_policy]}策略只支持周期执行",
            )
        repeat_mode = resolver.classify_cron_repeat_mode(cron_expr) if schedule_type == "cron" else None
        if rule.declared_by_action and repeat_mode not in rule.cron_repeat_modes:
            raise WebAppError(status_code=422, code="validation_error", message="当前周期类型不支持该数据集声明的日期策略")
        if rule.explicit_time_input == "forbidden" and (
            OperationsScheduleService._has_declared_time_input(
                params_json,
                definition=definition,
            )
        ):
            conflict_messages = {
                MONTHLY_LAST_DAY_POLICY: "每月最后一天策略不能与固定维护日期混用",
                MONTHLY_LAST_TRADING_DAY_POLICY: "每月最后交易日策略不能与固定维护日期混用",
                MONTHLY_WINDOW_CURRENT_MONTH_POLICY: "自然月窗口策略不能与固定维护日期或窗口混用",
                TRIGGER_DAY_SINGLE_RANGE_POLICY: "触发日单日区间策略不能与固定维护日期或窗口混用",
                TRIGGER_DAY_POINT_POLICY: "触发日单日策略不能与固定维护日期或窗口混用",
            }
            raise WebAppError(status_code=422, code="validation_error", message=conflict_messages[calendar_policy])
        if calendar_policy == TRIGGER_DAY_POINT_POLICY and repeat_mode == "intraday_interval":
            OperationsScheduleService._validate_intraday_interval_cron(cron_expr)

    @staticmethod
    def _validate_intraday_interval_cron(cron_expr: str | None) -> int:
        parts = str(cron_expr or "").split()
        if len(parts) != 5:
            raise WebAppError(status_code=422, code="validation_error", message="日内高频策略必须使用 */N * * * * 周期表达式")
        minute_expr, hour_expr, day_of_month_expr, month_expr, day_of_week_expr = parts
        if not (
            minute_expr.startswith("*/")
            and hour_expr == "*"
            and day_of_month_expr == "*"
            and month_expr == "*"
            and day_of_week_expr == "*"
        ):
            raise WebAppError(status_code=422, code="validation_error", message="日内高频策略必须使用 */N * * * * 周期表达式")
        interval_raw = minute_expr[2:]
        if not interval_raw.isdigit():
            raise WebAppError(status_code=422, code="validation_error", message="日内高频策略必须使用 */N * * * * 周期表达式")
        interval_minutes = int(interval_raw)
        if interval_minutes < MIN_INTRADAY_INTERVAL_MINUTES:
            raise WebAppError(status_code=422, code="validation_error", message="日内高频策略最小间隔为 3 分钟")
        return interval_minutes

    def _next_monthly_last_trading_day_occurrence(
        self,
        *,
        session: Session,
        cron_expr: str | None,
        timezone_name: str,
        after: datetime,
    ) -> datetime:
        if after.tzinfo is None:
            raise WebAppError(status_code=422, code="validation_error", message="排程计算时间必须包含时区信息")
        if not cron_expr:
            raise WebAppError(status_code=422, code="validation_error", message="周期排程必须填写周期表达式")
        zone = ensure_timezone(timezone_name)
        local_after = after.astimezone(zone)
        hour, minute = self._single_time_from_cron_expr(cron_expr)
        year = local_after.year
        month = local_after.month

        for _ in range(120):
            month_last_open_day = TaskRunCommandService._resolve_month_last_open_day(session=session, year=year, month=month)
            candidate = datetime(
                month_last_open_day.year,
                month_last_open_day.month,
                month_last_open_day.day,
                hour,
                minute,
                tzinfo=zone,
            )
            if candidate > local_after:
                return candidate.astimezone(timezone.utc)
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
        raise WebAppError(status_code=422, code="validation_error", message="无法在未来 120 个月内计算出下一次月末交易日运行时间")

    @staticmethod
    def _single_time_from_cron_expr(cron_expr: str) -> tuple[int, int]:
        parts = cron_expr.split()
        if len(parts) != 5:
            raise WebAppError(status_code=422, code="validation_error", message="周期表达式必须包含 5 段")
        minute_expr, hour_expr = parts[0], parts[1]
        if (not minute_expr.isdigit()) or (not hour_expr.isdigit()):
            raise WebAppError(status_code=422, code="validation_error", message="每月最后交易日策略必须使用单一执行时间")
        minute = int(minute_expr)
        hour = int(hour_expr)
        if minute < 0 or minute > 59 or hour < 0 or hour > 23:
            raise WebAppError(status_code=422, code="validation_error", message="每月最后交易日策略必须使用单一执行时间")
        return hour, minute

    @staticmethod
    def _has_fixed_trade_date(params_json: dict) -> bool:
        if params_json.get("trade_date") not in (None, ""):
            return True
        time_input = params_json.get("time_input")
        return isinstance(time_input, dict) and time_input.get("trade_date") not in (None, "")

    @staticmethod
    def _has_declared_time_input(params_json: dict, *, definition) -> bool:  # type: ignore[no-untyped-def]
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
