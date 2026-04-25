from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.app.models.app_user import AppUser
from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.models.ops.job_execution_step import JobExecutionStep
from src.ops.models.ops.sync_run_log import SyncRunLog
from src.ops.specs import get_dataset_freshness_spec, get_ops_spec_display_name, get_workflow_spec
from src.app.exceptions import WebAppError
from src.ops.schemas.execution import (
    ExecutionDetailResponse,
    ExecutionEventItem,
    ExecutionEventsResponse,
    ExecutionLogItem,
    ExecutionLogsResponse,
    ExecutionListItem,
    ExecutionListResponse,
    ExecutionSummaryResponse,
    ExecutionStepItem,
    ExecutionStepsResponse,
    ExecutionTimeScope,
)
from src.utils import truncate_text


class ExecutionQueryService:
    MAX_DETAIL_ERROR_MESSAGE_LENGTH = 12_000
    MAX_DETAIL_SUMMARY_LENGTH = 4_000
    MAX_EVENT_MESSAGE_LENGTH = 4_000
    MAX_STEP_MESSAGE_LENGTH = 2_000
    MAX_LOG_MESSAGE_LENGTH = 4_000
    MAX_PROGRESS_MESSAGE_LENGTH = 1_000

    def list_executions(
        self,
        session: Session,
        *,
        status: str | None = None,
        trigger_source: str | None = None,
        spec_type: str | None = None,
        spec_key: str | None = None,
        dataset_key: str | None = None,
        source_key: str | None = None,
        stage: str | None = None,
        run_scope: str | None = None,
        schedule_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ExecutionListResponse:
        limit = max(1, min(limit, 200))
        filters = self._build_filters(
            status=status,
            trigger_source=trigger_source,
            spec_type=spec_type,
            spec_key=spec_key,
            dataset_key=dataset_key,
            source_key=source_key,
            stage=stage,
            run_scope=run_scope,
            schedule_id=schedule_id,
        )

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

    def get_execution_summary(
        self,
        session: Session,
        *,
        status: str | None = None,
        trigger_source: str | None = None,
        spec_type: str | None = None,
        spec_key: str | None = None,
        dataset_key: str | None = None,
        source_key: str | None = None,
        stage: str | None = None,
        run_scope: str | None = None,
        schedule_id: int | None = None,
    ) -> ExecutionSummaryResponse:
        filters = self._build_filters(
            status=status,
            trigger_source=trigger_source,
            spec_type=spec_type,
            spec_key=spec_key,
            dataset_key=dataset_key,
            source_key=source_key,
            stage=stage,
            run_scope=run_scope,
            schedule_id=schedule_id,
        )

        summary_stmt = select(JobExecution.status, func.count()).select_from(JobExecution).group_by(JobExecution.status)
        if filters:
            summary_stmt = summary_stmt.where(*filters)
        rows = session.execute(summary_stmt).all()

        status_counts = {status_key: count for status_key, count in rows}
        total = sum(status_counts.values())
        return ExecutionSummaryResponse(
            total=total,
            queued=status_counts.get("queued", 0),
            running=status_counts.get("running", 0) + status_counts.get("canceling", 0),
            success=status_counts.get("success", 0),
            failed=status_counts.get("failed", 0) + status_counts.get("partial_success", 0),
            canceled=status_counts.get("canceled", 0),
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
        display_context = self._build_display_context(execution)

        return ExecutionDetailResponse(
            id=execution.id,
            schedule_id=execution.schedule_id,
            spec_type=execution.spec_type,
            spec_key=execution.spec_key,
            dataset_key=execution.dataset_key,
            source_key=execution.source_key,
            stage=execution.stage,
            policy_version=execution.policy_version,
            run_scope=execution.run_scope,
            run_profile=execution.run_profile,
            workflow_profile=execution.workflow_profile,
            correlation_id=execution.correlation_id,
            rerun_id=execution.rerun_id,
            resume_from_step_key=execution.resume_from_step_key,
            status_reason_code=execution.status_reason_code,
            spec_display_name=get_ops_spec_display_name(execution.spec_type, execution.spec_key),
            resource_key=display_context["resource_key"],
            resource_display_name=display_context["resource_display_name"],
            action_display_name=display_context["action_display_name"],
            time_scope=display_context["time_scope"],
            time_scope_label=display_context["time_scope_label"],
            schedule_display_name=schedule_display_name,
            trigger_source=execution.trigger_source,
            status=execution.status,
            requested_by_username=username,
            requested_at=execution.requested_at,
            queued_at=execution.queued_at,
            started_at=execution.started_at,
            ended_at=execution.ended_at,
            params_json=execution.params_json,
            summary_message=self._clip(execution.summary_message, self.MAX_DETAIL_SUMMARY_LENGTH),
            rows_fetched=execution.rows_fetched,
            rows_written=execution.rows_written,
            progress_current=execution.progress_current,
            progress_total=execution.progress_total,
            progress_percent=execution.progress_percent,
            progress_message=self._clip(execution.progress_message, self.MAX_PROGRESS_MESSAGE_LENGTH),
            last_progress_at=execution.last_progress_at,
            cancel_requested_at=execution.cancel_requested_at,
            canceled_at=execution.canceled_at,
            error_code=execution.error_code,
            error_message=self._clip(execution.error_message, self.MAX_DETAIL_ERROR_MESSAGE_LENGTH),
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
                    message=self._clip(log.message, self.MAX_LOG_MESSAGE_LENGTH),
                )
                for log in logs
            ],
        )

    def _list_item(self, execution: JobExecution, username: str | None, schedule_display_name: str | None) -> ExecutionListItem:
        display_context = self._build_display_context(execution)
        return ExecutionListItem(
            id=execution.id,
            spec_type=execution.spec_type,
            spec_key=execution.spec_key,
            dataset_key=execution.dataset_key,
            source_key=execution.source_key,
            stage=execution.stage,
            policy_version=execution.policy_version,
            run_scope=execution.run_scope,
            run_profile=execution.run_profile,
            workflow_profile=execution.workflow_profile,
            correlation_id=execution.correlation_id,
            rerun_id=execution.rerun_id,
            resume_from_step_key=execution.resume_from_step_key,
            status_reason_code=execution.status_reason_code,
            spec_display_name=get_ops_spec_display_name(execution.spec_type, execution.spec_key),
            resource_key=display_context["resource_key"],
            resource_display_name=display_context["resource_display_name"],
            action_display_name=display_context["action_display_name"],
            time_scope=display_context["time_scope"],
            time_scope_label=display_context["time_scope_label"],
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
            progress_message=self._clip(execution.progress_message, self.MAX_PROGRESS_MESSAGE_LENGTH),
            last_progress_at=execution.last_progress_at,
            summary_message=self._clip(execution.summary_message, self.MAX_DETAIL_SUMMARY_LENGTH),
            error_code=execution.error_code,
        )

    def _build_display_context(self, execution: JobExecution) -> dict[str, object]:
        resource_key = self._resolve_resource_key(execution)
        resource_display_name = self._resolve_resource_display_name(resource_key)
        spec_display_name = get_ops_spec_display_name(execution.spec_type, execution.spec_key)
        time_scope = self._build_time_scope(dict(execution.params_json or {}), resource_key=resource_key)
        return {
            "resource_key": resource_key,
            "resource_display_name": resource_display_name,
            "action_display_name": f"维护{resource_display_name}" if resource_display_name else spec_display_name,
            "time_scope": time_scope,
            "time_scope_label": time_scope.label if time_scope else None,
        }

    @staticmethod
    def _resolve_resource_key(execution: JobExecution) -> str | None:
        if execution.dataset_key:
            return execution.dataset_key
        if execution.spec_type == "job" and "." in execution.spec_key:
            return execution.spec_key.split(".", 1)[1]
        return None

    @staticmethod
    def _resolve_resource_display_name(resource_key: str | None) -> str | None:
        if not resource_key:
            return None
        spec = get_dataset_freshness_spec(resource_key)
        return spec.display_name if spec is not None else None

    @staticmethod
    def _build_time_scope(params_json: dict, *, resource_key: str | None) -> ExecutionTimeScope | None:
        def text_value(key: str) -> str | None:
            value = params_json.get(key)
            if value is None:
                return None
            text = str(value).strip()
            return text or None

        trade_date = text_value("trade_date")
        if trade_date:
            return ExecutionTimeScope(kind="point", start=trade_date, end=trade_date, label=trade_date)

        start_date = text_value("start_date")
        end_date = text_value("end_date")
        if start_date or end_date:
            if start_date and end_date:
                label = start_date if start_date == end_date else f"{start_date} ~ {end_date}"
            elif start_date:
                label = f"从 {start_date} 开始"
            else:
                label = f"截至 {end_date}"
            return ExecutionTimeScope(kind="range", start=start_date, end=end_date, label=label)

        month = text_value("month")
        if month:
            return ExecutionTimeScope(kind="month", start=month, end=month, label=month)

        start_month = text_value("start_month")
        end_month = text_value("end_month")
        if start_month or end_month:
            if start_month and end_month:
                label = start_month if start_month == end_month else f"{start_month} ~ {end_month}"
            elif start_month:
                label = f"从 {start_month} 开始"
            else:
                label = f"截至 {end_month}"
            return ExecutionTimeScope(kind="month_range", start=start_month, end=end_month, label=label)

        for key, label_prefix in (
            ("ann_date", "公告日期"),
            ("date", "处理日期"),
            ("cal_date", "日历日期"),
        ):
            value = text_value(key)
            if value:
                return ExecutionTimeScope(kind="point", start=value, end=value, label=f"{label_prefix}：{value}")

        freshness_spec = get_dataset_freshness_spec(resource_key) if resource_key else None
        if freshness_spec is not None and freshness_spec.observed_date_column:
            return ExecutionTimeScope(kind="auto", start=None, end=None, label="系统自动判断")

        return None

    @staticmethod
    def _build_filters(
        *,
        status: str | None = None,
        trigger_source: str | None = None,
        spec_type: str | None = None,
        spec_key: str | None = None,
        dataset_key: str | None = None,
        source_key: str | None = None,
        stage: str | None = None,
        run_scope: str | None = None,
        schedule_id: int | None = None,
    ) -> list[object]:
        filters = []
        if status:
            filters.append(JobExecution.status == status)
        if trigger_source:
            filters.append(JobExecution.trigger_source == trigger_source)
        if spec_type:
            filters.append(JobExecution.spec_type == spec_type)
        if spec_key:
            filters.append(JobExecution.spec_key == spec_key)
        if dataset_key:
            filters.append(JobExecution.dataset_key == dataset_key)
        if source_key:
            filters.append(JobExecution.source_key == source_key)
        if stage:
            filters.append(JobExecution.stage == stage)
        if run_scope:
            filters.append(JobExecution.run_scope == run_scope)
        if schedule_id is not None:
            filters.append(JobExecution.schedule_id == schedule_id)
        return filters

    def _step_item(self, step: JobExecutionStep) -> ExecutionStepItem:
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
            message=self._clip(step.message, self.MAX_STEP_MESSAGE_LENGTH),
            failure_policy_effective=step.failure_policy_effective,
            depends_on_step_keys_json=list(step.depends_on_step_keys_json or []),
            blocked_by_step_key=step.blocked_by_step_key,
            skip_reason_code=step.skip_reason_code,
            unit_total=step.unit_total,
            unit_done=step.unit_done,
            unit_failed=step.unit_failed,
        )

    def _event_item(self, event: JobExecutionEvent) -> ExecutionEventItem:
        return ExecutionEventItem(
            id=event.id,
            step_id=event.step_id,
            event_type=event.event_type,
            level=event.level,
            message=self._clip(event.message, self.MAX_EVENT_MESSAGE_LENGTH),
            payload_json=event.payload_json,
            occurred_at=event.occurred_at,
            event_id=event.event_id,
            event_version=event.event_version,
            correlation_id=event.correlation_id,
            unit_id=event.unit_id,
            producer=event.producer,
            dedupe_key=event.dedupe_key,
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
                    failure_policy_effective=workflow_step.failure_policy_override,
                    depends_on_step_keys_json=list(workflow_step.depends_on),
                    blocked_by_step_key=None,
                    skip_reason_code=None,
                    unit_total=0,
                    unit_done=0,
                    unit_failed=0,
                )
            )
        return items

    @staticmethod
    def _clip(value: str | None, max_length: int) -> str | None:
        return truncate_text(value, max_length)
