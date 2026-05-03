from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.schedule_probe_binding_service import ScheduleProbeBindingService
from src.ops.services.schedule_planner import compute_next_run_at, ensure_schedule_type, ensure_timezone, normalize_schedule_datetime
from src.ops.services.task_run_service import TaskRunCommandService
from src.ops.action_catalog import (
    action_is_schedulable,
    get_action_display_name,
    get_maintenance_action,
    get_workflow_definition,
)
from src.app.exceptions import WebAppError
from src.foundation.datasets.registry import get_dataset_definition_by_action_key


MONTHLY_LAST_DAY_POLICY = "monthly_last_day"


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
                explicit_next_run = compute_next_run_at(
                    schedule_type=schedule.schedule_type,
                    timezone_name=schedule.timezone,
                    cron_expr=schedule.cron_expr,
                    after=datetime.now(timezone.utc),
                    calendar_policy=schedule.calendar_policy,
                )
            schedule.next_run_at = explicit_next_run
        elif {"schedule_type", "cron_expr", "timezone", "calendar_policy"} & changed_fields and schedule.status == "active":
            schedule.next_run_at = self._resolve_next_run_at(
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
                schedule.next_run_at = compute_next_run_at(
                    schedule_type=schedule.schedule_type,
                    timezone_name=schedule.timezone,
                    cron_expr=schedule.cron_expr,
                    after=current_time,
                    calendar_policy=schedule.calendar_policy,
                )
            session.commit()
            task_runs.append(task_run)
        return task_runs

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
        schedule_type: str,
        cron_expr: str | None,
        timezone_name: str,
        next_run_at: datetime | None,
        calendar_policy: str | None,
    ) -> datetime | None:
        normalized = normalize_schedule_datetime(next_run_at, field_name="next_run_at")
        if normalized is not None:
            return normalized
        if schedule_type == "once":
            raise WebAppError(status_code=422, code="validation_error", message="单次排程必须填写下次运行时间")
        return compute_next_run_at(
            schedule_type=schedule_type,
            timezone_name=timezone_name,
            cron_expr=cron_expr,
            after=datetime.now(timezone.utc),
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
        if normalized != MONTHLY_LAST_DAY_POLICY:
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
        calendar_policy: str | None,
        params_json: dict,
    ) -> None:
        if calendar_policy is None:
            return
        if calendar_policy == MONTHLY_LAST_DAY_POLICY:
            if schedule_type != "cron":
                raise WebAppError(status_code=422, code="validation_error", message="每月最后一天策略只支持周期执行")
            if target_type != "dataset_action":
                raise WebAppError(status_code=422, code="validation_error", message="每月最后一天策略只支持数据集维护任务")
            try:
                definition, _action = get_dataset_definition_by_action_key(target_key)
            except KeyError as exc:
                raise WebAppError(status_code=422, code="validation_error", message="数据集维护动作不存在") from exc
            if definition.date_model.bucket_rule != "month_last_calendar_day":
                raise WebAppError(
                    status_code=422,
                    code="validation_error",
                    message="每月最后一天策略只支持自然月末数据集",
                )
            if OperationsScheduleService._has_fixed_trade_date(params_json):
                raise WebAppError(
                    status_code=422,
                    code="validation_error",
                    message="每月最后一天策略不能与固定维护日期混用",
                )
            return
        raise WebAppError(status_code=422, code="validation_error", message=f"不支持的日期策略：{calendar_policy}")

    @staticmethod
    def _has_fixed_trade_date(params_json: dict) -> bool:
        if params_json.get("trade_date") not in (None, ""):
            return True
        time_input = params_json.get("time_input")
        return isinstance(time_input, dict) and time_input.get("trade_date") not in (None, "")
