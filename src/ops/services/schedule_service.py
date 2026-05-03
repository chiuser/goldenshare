from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.ops.services.operations_schedule_service import OperationsScheduleService
from src.ops.services.schedule_planner import preview_schedule_runs
from src.app.auth.domain import AuthenticatedUser


class OpsScheduleCommandService:
    def __init__(self) -> None:
        self.schedule_service = OperationsScheduleService()

    def create_schedule(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        target_type: str,
        target_key: str,
        display_name: str,
        schedule_type: str,
        trigger_mode: str,
        cron_expr: str | None,
        timezone_name: str,
        calendar_policy: str | None,
        probe_config_json: dict,
        params_json: dict,
        retry_policy_json: dict,
        concurrency_policy_json: dict,
        next_run_at,
    ) -> int:
        schedule = self.schedule_service.create_schedule(
            session,
            target_type=target_type,
            target_key=target_key,
            display_name=display_name,
            schedule_type=schedule_type,
            trigger_mode=trigger_mode,
            cron_expr=cron_expr,
            timezone_name=timezone_name,
            calendar_policy=calendar_policy,
            probe_config_json=probe_config_json,
            params_json=params_json,
            retry_policy_json=retry_policy_json,
            concurrency_policy_json=concurrency_policy_json,
            next_run_at=next_run_at,
            created_by_user_id=user.id,
        )
        return schedule.id

    def update_schedule(self, session: Session, *, user: AuthenticatedUser, schedule_id: int, changes: dict) -> int:
        schedule = self.schedule_service.update_schedule(
            session,
            schedule_id=schedule_id,
            changes=changes,
            updated_by_user_id=user.id,
        )
        return schedule.id

    def pause_schedule(self, session: Session, *, user: AuthenticatedUser, schedule_id: int) -> int:
        schedule = self.schedule_service.pause_schedule(session, schedule_id=schedule_id, updated_by_user_id=user.id)
        return schedule.id

    def resume_schedule(self, session: Session, *, user: AuthenticatedUser, schedule_id: int) -> int:
        schedule = self.schedule_service.resume_schedule(session, schedule_id=schedule_id, updated_by_user_id=user.id)
        return schedule.id

    def delete_schedule(self, session: Session, *, user: AuthenticatedUser, schedule_id: int) -> int:
        return self.schedule_service.delete_schedule(session, schedule_id=schedule_id, deleted_by_user_id=user.id)

    def preview_schedule(
        self,
        *,
        schedule_type: str,
        cron_expr: str | None,
        timezone_name: str,
        next_run_at: datetime | None,
        calendar_policy: str | None,
        count: int,
    ) -> list[datetime]:
        return preview_schedule_runs(
            schedule_type=schedule_type,
            cron_expr=cron_expr,
            timezone_name=timezone_name,
            next_run_at=next_run_at,
            calendar_policy=calendar_policy,
            count=count,
        )
