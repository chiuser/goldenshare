from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.dataset_date_completeness_schedule import DatasetDateCompletenessSchedule
from src.ops.schemas.date_completeness import (
    DateCompletenessScheduleItem,
    DateCompletenessScheduleListResponse,
)


class DateCompletenessScheduleQueryService:
    def list_schedules(
        self,
        session: Session,
        *,
        status: str | None = None,
        dataset_key: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DateCompletenessScheduleListResponse:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters = self._filters(status=status, dataset_key=dataset_key)

        count_stmt = select(func.count()).select_from(DatasetDateCompletenessSchedule)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = int(session.scalar(count_stmt) or 0)

        stmt = (
            select(DatasetDateCompletenessSchedule, DatasetDateCompletenessRun)
            .outerjoin(DatasetDateCompletenessRun, DatasetDateCompletenessRun.id == DatasetDateCompletenessSchedule.last_run_id)
            .order_by(desc(DatasetDateCompletenessSchedule.updated_at), desc(DatasetDateCompletenessSchedule.id))
            .limit(limit)
            .offset(offset)
        )
        if filters:
            stmt = stmt.where(*filters)
        rows = session.execute(stmt).all()
        return DateCompletenessScheduleListResponse(
            total=total,
            items=[self._item(schedule, last_run) for schedule, last_run in rows],
        )

    def get_schedule(self, session: Session, schedule_id: int) -> DateCompletenessScheduleItem:
        row = session.execute(
            select(DatasetDateCompletenessSchedule, DatasetDateCompletenessRun)
            .outerjoin(DatasetDateCompletenessRun, DatasetDateCompletenessRun.id == DatasetDateCompletenessSchedule.last_run_id)
            .where(DatasetDateCompletenessSchedule.id == schedule_id)
        ).one_or_none()
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="日期完整性自动审计不存在")
        schedule, last_run = row
        return self._item(schedule, last_run)

    @staticmethod
    def _filters(*, status: str | None, dataset_key: str | None) -> list:
        filters = []
        if status:
            filters.append(DatasetDateCompletenessSchedule.status == status)
        if dataset_key:
            filters.append(DatasetDateCompletenessSchedule.dataset_key == dataset_key)
        return filters

    @staticmethod
    def _item(
        schedule: DatasetDateCompletenessSchedule,
        last_run: DatasetDateCompletenessRun | None,
    ) -> DateCompletenessScheduleItem:
        return DateCompletenessScheduleItem(
            id=schedule.id,
            dataset_key=schedule.dataset_key,
            display_name=schedule.display_name,
            status=schedule.status,
            window_mode=schedule.window_mode,
            start_date=schedule.start_date,
            end_date=schedule.end_date,
            lookback_count=schedule.lookback_count,
            lookback_unit=schedule.lookback_unit,
            calendar_scope=schedule.calendar_scope,
            calendar_exchange=schedule.calendar_exchange,
            cron_expr=schedule.cron_expr,
            timezone=schedule.timezone,
            next_run_at=schedule.next_run_at,
            last_run_id=schedule.last_run_id,
            last_run_status=last_run.run_status if last_run else None,
            last_result_status=last_run.result_status if last_run else None,
            last_run_finished_at=last_run.finished_at if last_run else None,
            created_by_user_id=schedule.created_by_user_id,
            updated_by_user_id=schedule.updated_by_user_id,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
        )
