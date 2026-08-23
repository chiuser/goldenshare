from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.runtime.task_run_dispatcher import TaskRunDispatchOutcome, TaskRunDispatcher
from src.ops.runtime.worker_lane import WorkerLane, lane_matches_values, lane_task_filter
from src.utils import truncate_text


class OperationsWorker:
    MAX_TECHNICAL_MESSAGE_LENGTH = 32_000

    def __init__(
        self,
        dispatcher: TaskRunDispatcher | None = None,
        *,
        lane: WorkerLane = WorkerLane.GENERAL,
    ) -> None:
        self.dispatcher = dispatcher or TaskRunDispatcher()
        self.lane = lane

    def run_next(self, session: Session) -> TaskRun | None:
        canceled = self._cancel_next_queued_task_run(session)
        if canceled is not None:
            return canceled

        while True:
            task_run_id = session.scalar(
                select(TaskRun.id)
                .where(TaskRun.status == "queued")
                .where(TaskRun.cancel_requested_at.is_(None))
                .where(lane_task_filter(self.lane))
                .order_by(TaskRun.requested_at.asc(), TaskRun.id.asc())
                .limit(1)
            )
            if task_run_id is None:
                return None
            if not self._claim_task_run(session, task_run_id):
                continue
            return self._run_started_task_run(session, task_run_id)

    def run_task_run(self, session: Session, task_run_id: int) -> TaskRun:
        task_run = session.get(TaskRun, task_run_id)
        if task_run is None:
            raise WebAppError(status_code=404, code="not_found", message="任务记录不存在")
        if task_run.status != "queued":
            raise WebAppError(status_code=409, code="conflict", message="只能启动排队中的任务")
        if not lane_matches_values(
            self.lane,
            task_type=task_run.task_type,
            resource_key=task_run.resource_key,
        ):
            raise WebAppError(
                status_code=409,
                code="worker_lane_mismatch",
                message="任务不属于当前 worker 执行车道",
            )
        if task_run.cancel_requested_at is not None:
            canceled = self._cancel_queued_task_run(session, task_run.id)
            if canceled is None:
                raise WebAppError(status_code=409, code="conflict", message="任务状态已变化，无法停止")
            return canceled
        if not self._claim_task_run(session, task_run.id):
            raise WebAppError(status_code=409, code="conflict", message="任务状态已变化，无法启动")
        return self._run_started_task_run(session, task_run.id)

    def _cancel_next_queued_task_run(self, session: Session) -> TaskRun | None:
        task_run_id = session.scalar(
            select(TaskRun.id)
            .where(TaskRun.status == "queued")
            .where(TaskRun.cancel_requested_at.is_not(None))
            .where(lane_task_filter(self.lane))
            .order_by(TaskRun.requested_at.asc(), TaskRun.id.asc())
            .limit(1)
        )
        if task_run_id is None:
            return None
        return self._cancel_queued_task_run(session, task_run_id)

    def _cancel_queued_task_run(self, session: Session, task_run_id: int) -> TaskRun | None:
        canceled_at = datetime.now(timezone.utc)
        result = session.execute(
            update(TaskRun)
            .where(TaskRun.id == task_run_id)
            .where(TaskRun.status == "queued")
            .where(TaskRun.cancel_requested_at.is_not(None))
            .where(lane_task_filter(self.lane))
            .values(
                status="canceled",
                canceled_at=canceled_at,
                ended_at=canceled_at,
                status_reason_code="canceled_before_start",
            )
        )
        if result.rowcount != 1:
            session.rollback()
            return None
        session.commit()
        task_run = session.get(TaskRun, task_run_id)
        if task_run is None:
            return None
        session.refresh(task_run)
        return task_run

    def _claim_task_run(self, session: Session, task_run_id: int) -> bool:
        started_at = datetime.now(timezone.utc)
        result = session.execute(
            update(TaskRun)
            .where(TaskRun.id == task_run_id)
            .where(TaskRun.status == "queued")
            .where(TaskRun.cancel_requested_at.is_(None))
            .where(lane_task_filter(self.lane))
            .values(
                status="running",
                started_at=started_at,
            )
        )
        if result.rowcount != 1:
            session.rollback()
            return False
        session.commit()
        return True

    def _run_started_task_run(self, session: Session, task_run_id: int) -> TaskRun:
        task_run = session.get(TaskRun, task_run_id)
        if task_run is None:
            raise WebAppError(status_code=404, code="not_found", message="任务记录不存在")
        try:
            try:
                outcome = self.dispatcher.dispatch(session, task_run)
            except Exception as exc:
                session.rollback()
                issue = self._record_worker_issue(
                    session,
                    task_run_id=task_run.id,
                    code="dispatcher_error",
                    source_phase="worker_dispatch",
                    title="任务调度异常",
                    operator_message="任务进入执行调度时发生异常，需要开发核验调度链路。",
                    suggested_action="先查看技术诊断并确认任务尚未开始写入，再决定是否重新提交。",
                    message=str(exc),
                )
                outcome = TaskRunDispatchOutcome(
                    status="failed",
                    summary_message=issue.operator_message,
                    issue_id=issue.id,
                    status_reason_code=issue.code,
                )
            return self._finalize_task_run(session, task_run.id, outcome)
        except Exception as exc:
            session.rollback()
            issue = self._record_worker_issue(
                session,
                task_run_id=task_run.id,
                code="worker_finalize_error",
                source_phase="worker_finalize",
                title="任务收尾异常",
                operator_message="任务写入最终状态时发生异常，需要开发核验任务终态。",
                suggested_action="不要重复提交任务，先核验业务数据和任务最终状态。",
                message=str(exc),
            )
            return self._finalize_task_run(
                session,
                task_run.id,
                TaskRunDispatchOutcome(status="failed", issue_id=issue.id, status_reason_code=issue.code),
            )

    def _finalize_task_run(self, session: Session, task_run_id: int, outcome: TaskRunDispatchOutcome) -> TaskRun:
        task_run = session.get(TaskRun, task_run_id)
        if task_run is None:
            raise WebAppError(status_code=404, code="not_found", message="任务记录不存在")
        now = datetime.now(timezone.utc)
        final_status = outcome.status
        if task_run.cancel_requested_at is not None and final_status in {"success", "partial_success"}:
            final_status = "canceled"
        task_run.status = final_status
        task_run.status_reason_code = outcome.status_reason_code
        task_run.ended_at = now
        task_run.rows_fetched = int(outcome.rows_fetched)
        task_run.rows_saved = int(outcome.rows_saved)
        task_run.rows_rejected = int(outcome.rows_rejected)
        task_run.rows_deduplicated = int(outcome.rows_deduplicated)
        task_run.ingestion_diagnostics_json = dict(outcome.ingestion_diagnostics or {})
        task_run.rejected_reason_counts_json = dict(outcome.rejected_reason_counts or task_run.rejected_reason_counts_json or {})
        task_run.rejected_reason_samples_json = dict(outcome.rejected_reason_samples or task_run.rejected_reason_samples_json or {})
        task_run.primary_issue_id = outcome.issue_id or task_run.primary_issue_id
        task_run.current_object_json = {}
        if final_status == "success":
            task_run.unit_done = task_run.unit_total or task_run.unit_done
            task_run.progress_percent = 100
        if final_status == "canceled":
            task_run.canceled_at = task_run.canceled_at or now
        session.commit()
        session.refresh(task_run)
        return task_run

    def _record_worker_issue(
        self,
        session: Session,
        *,
        task_run_id: int,
        code: str,
        source_phase: str,
        title: str,
        operator_message: str,
        suggested_action: str,
        message: str,
    ) -> TaskRunIssue:
        task_run = session.get(TaskRun, task_run_id)
        if task_run is None:
            raise WebAppError(status_code=404, code="not_found", message="任务记录不存在")
        issue = TaskRunIssue(
            task_run_id=task_run_id,
            node_id=task_run.current_node_id,
            severity="error",
            code=code,
            title=title,
            operator_message=operator_message,
            suggested_action=suggested_action,
            technical_message=truncate_text(message, self.MAX_TECHNICAL_MESSAGE_LENGTH),
            technical_payload_json={"source_phase": source_phase, "task_run_id": task_run_id},
            object_json=dict(task_run.current_object_json or {}),
            source_phase=source_phase,
            fingerprint=f"{task_run_id}:{code}",
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(issue)
        session.flush()
        task_run.primary_issue_id = issue.id
        session.commit()
        return issue
