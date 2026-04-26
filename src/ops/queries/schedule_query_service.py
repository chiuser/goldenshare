from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, aliased

from src.app.models.app_user import AppUser
from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.specs import get_ops_spec_display_name, get_ops_spec_target_display_name
from src.app.exceptions import WebAppError
from src.ops.schemas.schedule import (
    ScheduleDetailResponse,
    ScheduleListItem,
    ScheduleListResponse,
    ScheduleRevisionItem,
    ScheduleRevisionListResponse,
)


class ScheduleQueryService:
    def list_schedules(
        self,
        session: Session,
        *,
        status: str | None = None,
        spec_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ScheduleListResponse:
        limit = max(1, min(limit, 200))
        filters = []
        if status:
            filters.append(JobSchedule.status == status)
        if spec_type:
            filters.append(JobSchedule.spec_type == spec_type)

        count_stmt = select(func.count()).select_from(JobSchedule)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        created_by = aliased(AppUser)
        updated_by = aliased(AppUser)
        stmt = (
            select(JobSchedule, created_by.username, updated_by.username)
            .outerjoin(created_by, created_by.id == JobSchedule.created_by_user_id)
            .outerjoin(updated_by, updated_by.id == JobSchedule.updated_by_user_id)
            .order_by(desc(JobSchedule.updated_at), desc(JobSchedule.id))
            .limit(limit)
            .offset(offset)
        )
        if filters:
            stmt = stmt.where(*filters)

        rows = session.execute(stmt).all()
        return ScheduleListResponse(
            total=total,
            items=[
                self._list_item(
                    schedule=schedule,
                    created_by_username=created_by_username,
                    updated_by_username=updated_by_username,
                )
                for schedule, created_by_username, updated_by_username in rows
            ],
        )

    def get_schedule_detail(self, session: Session, schedule_id: int) -> ScheduleDetailResponse:
        created_by = aliased(AppUser)
        updated_by = aliased(AppUser)
        stmt = (
            select(JobSchedule, created_by.username, updated_by.username)
            .outerjoin(created_by, created_by.id == JobSchedule.created_by_user_id)
            .outerjoin(updated_by, updated_by.id == JobSchedule.updated_by_user_id)
            .where(JobSchedule.id == schedule_id)
        )
        row = session.execute(stmt).one_or_none()
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="Schedule does not exist")
        schedule, created_by_username, updated_by_username = row
        return ScheduleDetailResponse(
            id=schedule.id,
            spec_type=schedule.spec_type,
            spec_key=schedule.spec_key,
            spec_display_name=get_ops_spec_display_name(schedule.spec_type, schedule.spec_key),
            target_display_name=get_ops_spec_target_display_name(schedule.spec_type, schedule.spec_key),
            display_name=schedule.display_name,
            status=schedule.status,
            schedule_type=schedule.schedule_type,
            trigger_mode=schedule.trigger_mode,
            cron_expr=schedule.cron_expr,
            timezone=schedule.timezone,
            calendar_policy=schedule.calendar_policy,
            probe_config=dict(schedule.probe_config_json or {}),
            params_json=dict(schedule.params_json or {}),
            retry_policy_json=dict(schedule.retry_policy_json or {}),
            concurrency_policy_json=dict(schedule.concurrency_policy_json or {}),
            next_run_at=schedule.next_run_at,
            last_triggered_at=schedule.last_triggered_at,
            created_by_username=created_by_username,
            updated_by_username=updated_by_username,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
        )

    def list_schedule_revisions(self, session: Session, schedule_id: int) -> ScheduleRevisionListResponse:
        schedule = session.scalar(select(JobSchedule.id).where(JobSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="Schedule does not exist")

        changed_by = aliased(AppUser)
        stmt = (
            select(ConfigRevision, changed_by.username)
            .outerjoin(changed_by, changed_by.id == ConfigRevision.changed_by_user_id)
            .where(ConfigRevision.object_type == "job_schedule")
            .where(ConfigRevision.object_id == str(schedule_id))
            .order_by(desc(ConfigRevision.changed_at), desc(ConfigRevision.id))
        )
        rows = session.execute(stmt).all()
        return ScheduleRevisionListResponse(
            total=len(rows),
            items=[
                ScheduleRevisionItem(
                    id=revision.id,
                    object_type=revision.object_type,
                    object_id=revision.object_id,
                    action=revision.action,
                    before_json=revision.before_json,
                    after_json=revision.after_json,
                    changed_by_username=username,
                    changed_at=revision.changed_at,
                )
                for revision, username in rows
            ],
        )

    @staticmethod
    def _list_item(*, schedule: JobSchedule, created_by_username: str | None, updated_by_username: str | None) -> ScheduleListItem:
        return ScheduleListItem(
            id=schedule.id,
            spec_type=schedule.spec_type,
            spec_key=schedule.spec_key,
            spec_display_name=get_ops_spec_display_name(schedule.spec_type, schedule.spec_key),
            target_display_name=get_ops_spec_target_display_name(schedule.spec_type, schedule.spec_key),
            display_name=schedule.display_name,
            status=schedule.status,
            schedule_type=schedule.schedule_type,
            trigger_mode=schedule.trigger_mode,
            cron_expr=schedule.cron_expr,
            timezone=schedule.timezone,
            calendar_policy=schedule.calendar_policy,
            next_run_at=schedule.next_run_at,
            last_triggered_at=schedule.last_triggered_at,
            created_by_username=created_by_username,
            updated_by_username=updated_by_username,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
        )
