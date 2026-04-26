from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.app.models.app_user import AppUser
from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.schemas.task_run import (
    TaskRunActions,
    TaskRunInfo,
    TaskRunIssueDetailResponse,
    TaskRunIssueSummary,
    TaskRunListItem,
    TaskRunListResponse,
    TaskRunNodeItem,
    TaskRunProgress,
    TaskRunSummaryResponse,
    TaskRunTimeScope,
    TaskRunViewResponse,
)


class TaskRunQueryService:
    MAX_VIEW_NODES = 200

    def list_task_runs(
        self,
        session: Session,
        *,
        status: str | None = None,
        trigger_source: str | None = None,
        task_type: str | None = None,
        resource_key: str | None = None,
        schedule_id: int | None = None,
        page: int | None = None,
        limit: int = 20,
        offset: int | None = None,
    ) -> TaskRunListResponse:
        limit = max(1, min(limit, 200))
        effective_offset = max(0, offset if offset is not None else ((max(page or 1, 1) - 1) * limit))
        filters = self._build_filters(
            status=status,
            trigger_source=trigger_source,
            task_type=task_type,
            resource_key=resource_key,
            schedule_id=schedule_id,
        )
        count_stmt = select(func.count()).select_from(TaskRun)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = int(session.scalar(count_stmt) or 0)

        stmt = (
            select(TaskRun, AppUser.username, JobSchedule.display_name, TaskRunIssue.title)
            .outerjoin(AppUser, AppUser.id == TaskRun.requested_by_user_id)
            .outerjoin(JobSchedule, JobSchedule.id == TaskRun.schedule_id)
            .outerjoin(TaskRunIssue, TaskRunIssue.id == TaskRun.primary_issue_id)
            .order_by(desc(TaskRun.requested_at), desc(TaskRun.id))
            .limit(limit)
            .offset(effective_offset)
        )
        if filters:
            stmt = stmt.where(*filters)
        rows = session.execute(stmt).all()
        return TaskRunListResponse(
            total=total,
            items=[
                self._list_item(task_run, username, schedule_display_name, issue_title)
                for task_run, username, schedule_display_name, issue_title in rows
            ],
        )

    def get_summary(
        self,
        session: Session,
        *,
        status: str | None = None,
        trigger_source: str | None = None,
        task_type: str | None = None,
        resource_key: str | None = None,
        schedule_id: int | None = None,
    ) -> TaskRunSummaryResponse:
        filters = self._build_filters(
            status=status,
            trigger_source=trigger_source,
            task_type=task_type,
            resource_key=resource_key,
            schedule_id=schedule_id,
        )
        stmt = select(TaskRun.status, func.count()).select_from(TaskRun).group_by(TaskRun.status)
        if filters:
            stmt = stmt.where(*filters)
        counts = {status_key: int(count) for status_key, count in session.execute(stmt).all()}
        return TaskRunSummaryResponse(
            total=sum(counts.values()),
            queued=counts.get("queued", 0),
            running=counts.get("running", 0) + counts.get("canceling", 0),
            success=counts.get("success", 0),
            failed=counts.get("failed", 0) + counts.get("partial_success", 0),
            canceled=counts.get("canceled", 0),
        )

    def get_view(self, session: Session, task_run_id: int) -> TaskRunViewResponse:
        row = session.execute(
            select(TaskRun, AppUser.username, JobSchedule.display_name, TaskRunIssue)
            .outerjoin(AppUser, AppUser.id == TaskRun.requested_by_user_id)
            .outerjoin(JobSchedule, JobSchedule.id == TaskRun.schedule_id)
            .outerjoin(TaskRunIssue, TaskRunIssue.id == TaskRun.primary_issue_id)
            .where(TaskRun.id == task_run_id)
        ).one_or_none()
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="Task run does not exist")
        task_run, username, schedule_display_name, primary_issue = row
        node_total = int(
            session.scalar(select(func.count()).select_from(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id)) or 0
        )
        nodes = list(
            session.scalars(
                select(TaskRunNode)
                .where(TaskRunNode.task_run_id == task_run.id)
                .order_by(TaskRunNode.sequence_no.asc(), TaskRunNode.id.asc())
                .limit(self.MAX_VIEW_NODES)
            )
        )
        time_scope = self._time_scope(dict(task_run.time_input_json or {}))
        return TaskRunViewResponse(
            run=TaskRunInfo(
                id=task_run.id,
                task_type=task_run.task_type,
                resource_key=task_run.resource_key,
                action=task_run.action,
                title=task_run.title,
                trigger_source=task_run.trigger_source,
                status=task_run.status,
                status_reason_code=task_run.status_reason_code,
                requested_by_username=username,
                schedule_display_name=schedule_display_name,
                time_input=dict(task_run.time_input_json or {}),
                filters=dict(task_run.filters_json or {}),
                time_scope=time_scope,
                time_scope_label=time_scope.label if time_scope else None,
                requested_at=task_run.requested_at,
                queued_at=task_run.queued_at,
                started_at=task_run.started_at,
                ended_at=task_run.ended_at,
                cancel_requested_at=task_run.cancel_requested_at,
                canceled_at=task_run.canceled_at,
            ),
            progress=TaskRunProgress(
                unit_total=task_run.unit_total,
                unit_done=task_run.unit_done,
                unit_failed=task_run.unit_failed,
                progress_percent=task_run.progress_percent,
                rows_fetched=task_run.rows_fetched,
                rows_saved=task_run.rows_saved,
                rows_rejected=task_run.rows_rejected,
                current_context=dict(task_run.current_context_json or {}),
            ),
            primary_issue=self._issue_summary(primary_issue),
            nodes=[self._node_item(node) for node in nodes],
            node_total=node_total,
            nodes_truncated=node_total > len(nodes),
            actions=TaskRunActions(
                can_retry=task_run.status in {"failed", "partial_success", "canceled", "success"},
                can_cancel=task_run.status in {"queued", "running", "canceling"},
                can_copy_params=True,
            ),
        )

    def get_issue_detail(self, session: Session, *, task_run_id: int, issue_id: int) -> TaskRunIssueDetailResponse:
        issue = session.scalar(
            select(TaskRunIssue)
            .where(TaskRunIssue.task_run_id == task_run_id)
            .where(TaskRunIssue.id == issue_id)
        )
        if issue is None:
            raise WebAppError(status_code=404, code="not_found", message="Task run issue does not exist")
        return TaskRunIssueDetailResponse(
            id=issue.id,
            task_run_id=issue.task_run_id,
            node_id=issue.node_id,
            severity=issue.severity,
            code=issue.code,
            title=issue.title,
            operator_message=issue.operator_message,
            suggested_action=issue.suggested_action,
            technical_message=issue.technical_message,
            technical_payload=dict(issue.technical_payload_json or {}),
            source_phase=issue.source_phase,
            occurred_at=issue.occurred_at,
        )

    def _list_item(
        self,
        task_run: TaskRun,
        username: str | None,
        schedule_display_name: str | None,
        issue_title: str | None,
    ) -> TaskRunListItem:
        time_scope = self._time_scope(dict(task_run.time_input_json or {}))
        return TaskRunListItem(
            id=task_run.id,
            task_type=task_run.task_type,
            resource_key=task_run.resource_key,
            action=task_run.action,
            title=task_run.title,
            trigger_source=task_run.trigger_source,
            status=task_run.status,
            status_reason_code=task_run.status_reason_code,
            requested_by_username=username,
            requested_at=task_run.requested_at,
            started_at=task_run.started_at,
            ended_at=task_run.ended_at,
            time_scope=time_scope,
            time_scope_label=time_scope.label if time_scope else None,
            schedule_display_name=schedule_display_name,
            unit_total=task_run.unit_total,
            unit_done=task_run.unit_done,
            unit_failed=task_run.unit_failed,
            progress_percent=task_run.progress_percent,
            rows_fetched=task_run.rows_fetched,
            rows_saved=task_run.rows_saved,
            rows_rejected=task_run.rows_rejected,
            primary_issue_id=task_run.primary_issue_id,
            primary_issue_title=issue_title,
        )

    @staticmethod
    def _issue_summary(issue: TaskRunIssue | None) -> TaskRunIssueSummary | None:
        if issue is None:
            return None
        return TaskRunIssueSummary(
            id=issue.id,
            severity=issue.severity,
            code=issue.code,
            title=issue.title,
            operator_message=issue.operator_message,
            suggested_action=issue.suggested_action,
            has_technical_detail=bool(issue.technical_message or issue.technical_payload_json),
            occurred_at=issue.occurred_at,
        )

    @staticmethod
    def _node_item(node: TaskRunNode) -> TaskRunNodeItem:
        return TaskRunNodeItem(
            id=node.id,
            parent_node_id=node.parent_node_id,
            node_key=node.node_key,
            node_type=node.node_type,
            sequence_no=node.sequence_no,
            title=node.title,
            resource_key=node.resource_key,
            status=node.status,
            time_input=dict(node.time_input_json or {}),
            context=dict(node.context_json or {}),
            rows_fetched=node.rows_fetched,
            rows_saved=node.rows_saved,
            rows_rejected=node.rows_rejected,
            issue_id=node.issue_id,
            started_at=node.started_at,
            ended_at=node.ended_at,
            duration_ms=node.duration_ms,
        )

    @staticmethod
    def _time_scope(time_input: dict) -> TaskRunTimeScope | None:
        mode = str(time_input.get("mode") or "none")
        trade_date = TaskRunQueryService._text(time_input.get("trade_date") or time_input.get("ann_date"))
        if trade_date:
            return TaskRunTimeScope(kind="point", start=trade_date, end=trade_date, label=trade_date)
        start_date = TaskRunQueryService._text(time_input.get("start_date"))
        end_date = TaskRunQueryService._text(time_input.get("end_date"))
        if start_date or end_date:
            label = TaskRunQueryService._range_label(start_date, end_date)
            return TaskRunTimeScope(kind="range", start=start_date, end=end_date, label=label)
        month = TaskRunQueryService._text(time_input.get("month"))
        if month:
            return TaskRunTimeScope(kind="month", start=month, end=month, label=month)
        start_month = TaskRunQueryService._text(time_input.get("start_month"))
        end_month = TaskRunQueryService._text(time_input.get("end_month"))
        if start_month or end_month:
            label = TaskRunQueryService._range_label(start_month, end_month)
            return TaskRunTimeScope(kind="month_range", start=start_month, end=end_month, label=label)
        if mode == "none":
            return None
        return TaskRunTimeScope(kind=mode, start=None, end=None, label="系统自动判断")

    @staticmethod
    def _range_label(start: str | None, end: str | None) -> str:
        if start and end:
            return start if start == end else f"{start} ~ {end}"
        if start:
            return f"从 {start} 开始"
        return f"截至 {end}"

    @staticmethod
    def _text(value: object) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _build_filters(
        *,
        status: str | None = None,
        trigger_source: str | None = None,
        task_type: str | None = None,
        resource_key: str | None = None,
        schedule_id: int | None = None,
    ) -> list[object]:
        filters = []
        if status:
            filters.append(TaskRun.status == status)
        if trigger_source:
            filters.append(TaskRun.trigger_source == trigger_source)
        if task_type:
            filters.append(TaskRun.task_type == task_type)
        if resource_key:
            filters.append(TaskRun.resource_key == resource_key)
        if schedule_id is not None:
            filters.append(TaskRun.schedule_id == schedule_id)
        return filters
