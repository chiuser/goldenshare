from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.platform.models.app.app_user import AppUser
from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.models.ops.job_execution_step import JobExecutionStep
from src.ops.models.ops.sync_run_log import SyncRunLog
from src.operations.specs import get_ops_spec_display_name, get_workflow_spec
from src.platform.exceptions import WebAppError
from src.ops.schemas.execution import (
    ExecutionDetailResponse,
    ExecutionEventItem,
    ExecutionEventsResponse,
    ExecutionLogItem,
    ExecutionLogsResponse,
    ExecutionListItem,
    ExecutionListResponse,
    ExecutionStepItem,
    ExecutionStepsResponse,
)


class ExecutionQueryService:
    def list_executions(
        self,
        session: Session,
        *,
        status: str | None = None,
        trigger_source: str | None = None,
        spec_type: str | None = None,
        spec_key: str | None = None,
        schedule_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ExecutionListResponse:
        limit = max(1, min(limit, 200))
        filters = []
        if status:
            filters.append(JobExecution.status == status)
        if trigger_source:
            filters.append(JobExecution.trigger_source == trigger_source)
        if spec_type:
            filters.append(JobExecution.spec_type == spec_type)
        if spec_key:
            filters.append(JobExecution.spec_key == spec_key)
        if schedule_id is not None:
            filters.append(JobExecution.schedule_id == schedule_id)

        count_stmt = select(func.count()).select_from(JobExecution)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = session.scalar(count_stmt) or 0

        stmt = (
            select(JobExecution, AppUser.username, JobSchedule.display_name)
            .outerjoin(AppUser, AppUser.id == JobExecution.requested_by_user_id)
            .outerjoin(JobSchedule, JobSchedule.id == JobExecution.schedule_id)
            .order_by(desc(JobExecution.requested_at), desc(JobExecution.id))
            .limit(limit)
            .offset(offset)
        )
        if filters:
            stmt = stmt.where(*filters)

        rows = session.execute(stmt).all()
        return ExecutionListResponse(
            total=total,
            items=[self._list_item(execution, username, schedule_display_name) for execution, username, schedule_display_name in rows],
        )

    def get_execution_detail(self, session: Session, execution_id: int) -> ExecutionDetailResponse:
        stmt = (
            select(JobExecution, AppUser.username, JobSchedule.display_name)
            .outerjoin(AppUser, AppUser.id == JobExecution.requested_by_user_id)
            .outerjoin(JobSchedule, JobSchedule.id == JobExecution.schedule_id)
            .where(JobExecution.id == execution_id)
        )
        row = session.execute(stmt).one_or_none()
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        execution, username, schedule_display_name = row

        steps = self._build_step_items(session, execution)
        events = self._load_events(session, execution_id)

        return ExecutionDetailResponse(
            id=execution.id,
            schedule_id=execution.schedule_id,
            spec_type=execution.spec_type,
            spec_key=execution.spec_key,
            spec_display_name=get_ops_spec_display_name(execution.spec_type, execution.spec_key),
            schedule_display_name=schedule_display_name,
            trigger_source=execution.trigger_source,
            status=execution.status,
            requested_by_username=username,
            requested_at=execution.requested_at,
            queued_at=execution.queued_at,
            started_at=execution.started_at,
            ended_at=execution.ended_at,
            params_json=execution.params_json,
            summary_message=execution.summary_message,
            rows_fetched=execution.rows_fetched,
            rows_written=execution.rows_written,
            progress_current=execution.progress_current,
            progress_total=execution.progress_total,
            progress_percent=execution.progress_percent,
            progress_message=execution.progress_message,
            last_progress_at=execution.last_progress_at,
            cancel_requested_at=execution.cancel_requested_at,
            canceled_at=execution.canceled_at,
            error_code=execution.error_code,
            error_message=execution.error_message,
            steps=steps,
            events=[self._event_item(event) for event in events],
        )

    def get_execution_steps(self, session: Session, execution_id: int) -> ExecutionStepsResponse:
        execution = self._load_execution(session, execution_id)
        return ExecutionStepsResponse(
            execution_id=execution_id,
            items=self._build_step_items(session, execution),
        )

    def get_execution_events(self, session: Session, execution_id: int) -> ExecutionEventsResponse:
        self._ensure_execution_exists(session, execution_id)
        return ExecutionEventsResponse(
            execution_id=execution_id,
            items=[self._event_item(event) for event in self._load_events(session, execution_id)],
        )

    def get_execution_logs(self, session: Session, execution_id: int) -> ExecutionLogsResponse:
        self._ensure_execution_exists(session, execution_id)
        logs = list(
            session.scalars(
                select(SyncRunLog)
                .where(SyncRunLog.execution_id == execution_id)
                .order_by(SyncRunLog.started_at.asc(), SyncRunLog.id.asc())
            )
        )
        return ExecutionLogsResponse(
            execution_id=execution_id,
            items=[
                ExecutionLogItem(
                    id=log.id,
                    execution_id=log.execution_id,
                    job_name=log.job_name,
                    run_type=log.run_type,
                    status=log.status,
                    started_at=log.started_at,
                    ended_at=log.ended_at,
                    rows_fetched=log.rows_fetched,
                    rows_written=log.rows_written,
                    message=log.message,
                )
                for log in logs
            ],
        )

    @staticmethod
    def _list_item(execution: JobExecution, username: str | None, schedule_display_name: str | None) -> ExecutionListItem:
        return ExecutionListItem(
            id=execution.id,
            spec_type=execution.spec_type,
            spec_key=execution.spec_key,
            spec_display_name=get_ops_spec_display_name(execution.spec_type, execution.spec_key),
            schedule_display_name=schedule_display_name,
            trigger_source=execution.trigger_source,
            status=execution.status,
            requested_by_username=username,
            requested_at=execution.requested_at,
            started_at=execution.started_at,
            ended_at=execution.ended_at,
            rows_fetched=execution.rows_fetched,
            rows_written=execution.rows_written,
            progress_current=execution.progress_current,
            progress_total=execution.progress_total,
            progress_percent=execution.progress_percent,
            progress_message=execution.progress_message,
            last_progress_at=execution.last_progress_at,
            summary_message=execution.summary_message,
            error_code=execution.error_code,
        )

    @staticmethod
    def _step_item(step: JobExecutionStep) -> ExecutionStepItem:
        return ExecutionStepItem(
            id=step.id,
            step_key=step.step_key,
            display_name=step.display_name,
            sequence_no=step.sequence_no,
            unit_kind=step.unit_kind,
            unit_value=step.unit_value,
            status=step.status,
            started_at=step.started_at,
            ended_at=step.ended_at,
            rows_fetched=step.rows_fetched,
            rows_written=step.rows_written,
            message=step.message,
        )

    @staticmethod
    def _event_item(event: JobExecutionEvent) -> ExecutionEventItem:
        return ExecutionEventItem(
            id=event.id,
            step_id=event.step_id,
            event_type=event.event_type,
            level=event.level,
            message=event.message,
            payload_json=event.payload_json,
            occurred_at=event.occurred_at,
        )

    @staticmethod
    def _ensure_execution_exists(session: Session, execution_id: int) -> None:
        exists = session.scalar(select(JobExecution.id).where(JobExecution.id == execution_id))
        if exists is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")

    @staticmethod
    def _load_execution(session: Session, execution_id: int) -> JobExecution:
        execution = session.get(JobExecution, execution_id)
        if execution is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        return execution

    @staticmethod
    def _load_steps(session: Session, execution_id: int) -> list[JobExecutionStep]:
        return list(
            session.scalars(
                select(JobExecutionStep)
                .where(JobExecutionStep.execution_id == execution_id)
                .order_by(JobExecutionStep.sequence_no.asc(), JobExecutionStep.id.asc())
            )
        )

    @staticmethod
    def _load_events(session: Session, execution_id: int) -> list[JobExecutionEvent]:
        return list(
            session.scalars(
                select(JobExecutionEvent)
                .where(JobExecutionEvent.execution_id == execution_id)
                .order_by(JobExecutionEvent.occurred_at.asc(), JobExecutionEvent.id.asc())
            )
        )

    def _build_step_items(self, session: Session, execution: JobExecution) -> list[ExecutionStepItem]:
        actual_steps = self._load_steps(session, execution.id)
        actual_items = [self._step_item(step) for step in actual_steps]
        if execution.spec_type != "workflow":
            return actual_items

        workflow_spec = get_workflow_spec(execution.spec_key)
        if workflow_spec is None:
            return actual_items

        by_step_key = {item.step_key: item for item in actual_items}
        items: list[ExecutionStepItem] = []
        for sequence_no, workflow_step in enumerate(workflow_spec.steps, start=1):
            existing = by_step_key.get(workflow_step.step_key)
            if existing is not None:
                items.append(existing)
                continue
            items.append(
                ExecutionStepItem(
                    id=-sequence_no,
                    step_key=workflow_step.step_key,
                    display_name=workflow_step.display_name,
                    sequence_no=sequence_no,
                    unit_kind=None,
                    unit_value=None,
                    status="pending",
                    started_at=None,
                    ended_at=None,
                    rows_fetched=0,
                    rows_written=0,
                    message=None,
                )
            )
        return items
