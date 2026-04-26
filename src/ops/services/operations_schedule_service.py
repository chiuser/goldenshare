from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.schedule_probe_binding_service import ScheduleProbeBindingService
from src.ops.services.schedule_planner import compute_next_run_at, ensure_schedule_type, ensure_timezone, normalize_schedule_datetime
from src.ops.services.task_run_service import TaskRunCommandService
from src.ops.action_catalog import (
    get_maintenance_action,
    get_schedule_display_name,
    schedule_target_is_schedulable,
)
from src.app.exceptions import WebAppError
from src.foundation.datasets.registry import get_dataset_definition_by_action_key


class OperationsScheduleService:
    def __init__(self) -> None:
        self.task_run_service = TaskRunCommandService()
        self.probe_binding_service = ScheduleProbeBindingService()

    def create_schedule(
        self,
        session: Session,
        *,
        spec_type: str,
        spec_key: str,
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
    ) -> JobSchedule:
        self._validate_spec(spec_type, spec_key)
        ensure_schedule_type(schedule_type)
        ensure_timezone(timezone_name)
        trigger_mode = self._normalize_trigger_mode(trigger_mode)
        normalized_next_run_at = self._resolve_next_run_at(
            schedule_type=schedule_type,
            cron_expr=cron_expr,
            timezone_name=timezone_name,
            next_run_at=next_run_at,
        )

        schedule = JobSchedule(
            spec_type=spec_type,
            spec_key=spec_key,
            display_name=display_name.strip() or self._fallback_display_name(spec_type, spec_key),
            status="active",
            schedule_type=schedule_type,
            trigger_mode=trigger_mode,
            cron_expr=cron_expr,
            timezone=timezone_name,
            calendar_policy=calendar_policy,
            probe_config_json=dict(probe_config_json or {}),
            params_json=dict(params_json or {}),
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
    ) -> JobSchedule:
        schedule = session.scalar(select(JobSchedule).where(JobSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="Schedule does not exist")

        before = self._snapshot(schedule)
        changed_fields = set(changes)

        if "spec_type" in changed_fields or "spec_key" in changed_fields:
            spec_type = changes.get("spec_type", schedule.spec_type)
            spec_key = changes.get("spec_key", schedule.spec_key)
            self._validate_spec(spec_type, spec_key)
            schedule.spec_type = spec_type
            schedule.spec_key = spec_key
            if "display_name" not in changed_fields and schedule.display_name == self._fallback_display_name(before["spec_type"], before["spec_key"]):
                schedule.display_name = self._fallback_display_name(spec_type, spec_key)

        if "display_name" in changed_fields:
            display_name = str(changes["display_name"]).strip()
            if not display_name:
                raise WebAppError(status_code=422, code="validation_error", message="display_name cannot be empty")
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
            schedule.calendar_policy = changes["calendar_policy"]
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
                )
            schedule.next_run_at = explicit_next_run
        elif {"schedule_type", "cron_expr", "timezone"} & changed_fields and schedule.status == "active":
            schedule.next_run_at = self._resolve_next_run_at(
                schedule_type=schedule.schedule_type,
                cron_expr=schedule.cron_expr,
                timezone_name=schedule.timezone,
                next_run_at=None if schedule.schedule_type == "cron" else schedule.next_run_at,
            )

        if schedule.schedule_type == "once" and schedule.status == "active" and schedule.next_run_at is None:
            raise WebAppError(status_code=422, code="validation_error", message="next_run_at is required for once schedules")

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

    def pause_schedule(self, session: Session, *, schedule_id: int, updated_by_user_id: int) -> JobSchedule:
        schedule = session.scalar(select(JobSchedule).where(JobSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="Schedule does not exist")
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

    def resume_schedule(self, session: Session, *, schedule_id: int, updated_by_user_id: int) -> JobSchedule:
        schedule = session.scalar(select(JobSchedule).where(JobSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="Schedule does not exist")
        if schedule.status == "active":
            session.refresh(schedule)
            return schedule

        before = self._snapshot(schedule)
        if schedule.schedule_type == "once":
            if schedule.next_run_at is None:
                raise WebAppError(
                    status_code=409,
                    code="conflict",
                    message="One-shot schedule requires next_run_at before it can be resumed",
                )
        else:
            schedule.next_run_at = self._resolve_next_run_at(
                schedule_type=schedule.schedule_type,
                cron_expr=schedule.cron_expr,
                timezone_name=schedule.timezone,
                next_run_at=self._stored_datetime(schedule.next_run_at),
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
        schedule = session.scalar(select(JobSchedule).where(JobSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="Schedule does not exist")

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
            select(JobSchedule)
            .where(JobSchedule.status == "active")
            .where(JobSchedule.trigger_mode != "probe")
            .where(JobSchedule.next_run_at.is_not(None))
            .where(JobSchedule.next_run_at <= current_time)
            .order_by(JobSchedule.next_run_at.asc(), JobSchedule.id.asc())
            .limit(limit)
        )
        schedules = list(session.scalars(stmt))
        task_runs: list[TaskRun] = []
        for schedule in schedules:
            task_run = self.task_run_service.create_from_spec(
                session,
                spec_type=schedule.spec_type,
                spec_key=schedule.spec_key,
                params_json=dict(schedule.params_json or {}),
                trigger_source="scheduled",
                requested_by_user_id=None,
                schedule_id=schedule.id,
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
                )
            session.commit()
            task_runs.append(task_run)
        return task_runs

    @staticmethod
    def _snapshot(schedule: JobSchedule) -> dict:
        return {
            "id": schedule.id,
            "spec_type": schedule.spec_type,
            "spec_key": schedule.spec_key,
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
                object_type="job_schedule",
                object_id=object_id,
                action=action,
                before_json=before_json,
                after_json=after_json,
                changed_by_user_id=changed_by_user_id,
                changed_at=datetime.now(timezone.utc),
            )
        )

    @staticmethod
    def _fallback_display_name(spec_type: str, spec_key: str) -> str:
        return get_schedule_display_name(spec_type, spec_key) or spec_key

    @staticmethod
    def _validate_spec(spec_type: str, spec_key: str) -> None:
        if spec_type == "dataset_action":
            try:
                get_dataset_definition_by_action_key(spec_key)
            except KeyError as exc:
                raise WebAppError(status_code=422, code="validation_error", message="Dataset action does not exist") from exc
            if not schedule_target_is_schedulable(spec_type, spec_key):
                raise WebAppError(status_code=422, code="validation_error", message="Selected target does not support scheduling")
            return
        display_name = get_schedule_display_name(spec_type, spec_key)
        if display_name is None:
            if spec_type == "job":
                raise WebAppError(status_code=404, code="not_found", message="Maintenance action does not exist")
            if spec_type == "workflow":
                raise WebAppError(status_code=404, code="not_found", message="Workflow does not exist")
            raise WebAppError(status_code=422, code="validation_error", message="Unsupported spec_type")
        if spec_type == "job":
            action = get_maintenance_action(spec_key)
            if action is None:
                raise WebAppError(status_code=422, code="validation_error", message="Unsupported maintenance action")
        if not schedule_target_is_schedulable(spec_type, spec_key):
            raise WebAppError(status_code=422, code="validation_error", message="Selected target does not support scheduling")

    def _resolve_next_run_at(
        self,
        *,
        schedule_type: str,
        cron_expr: str | None,
        timezone_name: str,
        next_run_at: datetime | None,
    ) -> datetime | None:
        normalized = normalize_schedule_datetime(next_run_at, field_name="next_run_at")
        if normalized is not None:
            return normalized
        if schedule_type == "once":
            raise WebAppError(status_code=422, code="validation_error", message="next_run_at is required for once schedules")
        return compute_next_run_at(
            schedule_type=schedule_type,
            timezone_name=timezone_name,
            cron_expr=cron_expr,
            after=datetime.now(timezone.utc),
        )

    @staticmethod
    def _normalize_trigger_mode(value: str | None) -> str:
        mode = str(value or "schedule").strip().lower()
        if mode not in {"schedule", "probe", "schedule_probe_fallback"}:
            raise WebAppError(status_code=422, code="validation_error", message=f"Unsupported trigger_mode: {mode}")
        return mode

    @staticmethod
    def _stored_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
