from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, aliased

from src.app.models.app_user import AppUser
from src.foundation.datasets.source_registry import get_source_display_name
from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.action_catalog import get_target_display_name
from src.app.exceptions import WebAppError
from src.ops.dataset_labels import get_dataset_display_name
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
        target_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ScheduleListResponse:
        limit = max(1, min(limit, 200))
        filters = []
        if status:
            filters.append(OpsSchedule.status == status)
        if target_type:
            filters.append(OpsSchedule.target_type == target_type)

        count_stmt = select(func.count()).select_from(OpsSchedule)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        created_by = aliased(AppUser)
        updated_by = aliased(AppUser)
        stmt = (
            select(OpsSchedule, created_by.username, updated_by.username)
            .outerjoin(created_by, created_by.id == OpsSchedule.created_by_user_id)
            .outerjoin(updated_by, updated_by.id == OpsSchedule.updated_by_user_id)
            .order_by(desc(OpsSchedule.updated_at), desc(OpsSchedule.id))
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
            select(OpsSchedule, created_by.username, updated_by.username)
            .outerjoin(created_by, created_by.id == OpsSchedule.created_by_user_id)
            .outerjoin(updated_by, updated_by.id == OpsSchedule.updated_by_user_id)
            .where(OpsSchedule.id == schedule_id)
        )
        row = session.execute(stmt).one_or_none()
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="Schedule does not exist")
        schedule, created_by_username, updated_by_username = row
        return ScheduleDetailResponse(
            id=schedule.id,
            target_type=schedule.target_type,
            target_key=schedule.target_key,
            target_display_name=get_target_display_name(schedule.target_type, schedule.target_key),
            display_name=schedule.display_name,
            status=schedule.status,
            schedule_type=schedule.schedule_type,
            trigger_mode=schedule.trigger_mode,
            cron_expr=schedule.cron_expr,
            timezone=schedule.timezone,
            calendar_policy=schedule.calendar_policy,
            probe_config=self._probe_config_response(schedule.probe_config_json),
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
        schedule = session.scalar(select(OpsSchedule.id).where(OpsSchedule.id == schedule_id))
        if schedule is None:
            raise WebAppError(status_code=404, code="not_found", message="Schedule does not exist")

        changed_by = aliased(AppUser)
        stmt = (
            select(ConfigRevision, changed_by.username)
            .outerjoin(changed_by, changed_by.id == ConfigRevision.changed_by_user_id)
            .where(ConfigRevision.object_type == "schedule")
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
    def _list_item(*, schedule: OpsSchedule, created_by_username: str | None, updated_by_username: str | None) -> ScheduleListItem:
        return ScheduleListItem(
            id=schedule.id,
            target_type=schedule.target_type,
            target_key=schedule.target_key,
            target_display_name=get_target_display_name(schedule.target_type, schedule.target_key),
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

    @staticmethod
    def _probe_config_response(probe_config_json: dict | None) -> dict | None:
        if not probe_config_json:
            return None
        payload = dict(probe_config_json)
        payload["source_display_name"] = get_source_display_name(payload.get("source_key"))
        payload["workflow_dataset_targets"] = [
            {
                "dataset_key": dataset_key,
                "dataset_display_name": get_dataset_display_name(dataset_key),
            }
            for dataset_key in _normalize_dataset_keys(payload.get("workflow_dataset_keys"))
        ]
        return payload


def _normalize_dataset_keys(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
