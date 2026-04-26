from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.runtime.task_run_dispatcher import TaskRunDispatchOutcome, TaskRunDispatcher
from src.ops.services.operations_dataset_status_snapshot_service import DatasetStatusSnapshotService
from src.utils import truncate_text


class OperationsWorker:
    MAX_TECHNICAL_MESSAGE_LENGTH = 32_000

    def __init__(self, dispatcher: TaskRunDispatcher | None = None) -> None:
        self.dispatcher = dispatcher or TaskRunDispatcher()

    def run_next(self, session: Session) -> TaskRun | None:
        canceled = self._cancel_next_queued_task_run(session)
        if canceled is not None:
            return canceled

        while True:
            task_run_id = session.scalar(
                select(TaskRun.id)
                .where(TaskRun.status == "queued")
                .where(TaskRun.cancel_requested_at.is_(None))
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
            raise WebAppError(status_code=404, code="not_found", message="Task run does not exist")
        if task_run.status != "queued":
            raise WebAppError(status_code=409, code="conflict", message="Only queued task runs can start immediately")
        if task_run.cancel_requested_at is not None:
            canceled = self._cancel_queued_task_run(session, task_run.id)
            if canceled is None:
                raise WebAppError(status_code=409, code="conflict", message="Task run status changed before canceling")
            return canceled
        if not self._claim_task_run(session, task_run.id):
            raise WebAppError(status_code=409, code="conflict", message="Task run status changed before start")
        return self._run_started_task_run(session, task_run.id)

    def _cancel_next_queued_task_run(self, session: Session) -> TaskRun | None:
        task_run_id = session.scalar(
            select(TaskRun.id)
            .where(TaskRun.status == "queued")
            .where(TaskRun.cancel_requested_at.is_not(None))
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
            raise WebAppError(status_code=404, code="not_found", message="Task run does not exist")
        try:
            try:
                outcome = self.dispatcher.dispatch(session, task_run)
            except Exception as exc:
                issue = self._record_worker_issue(session, task_run_id=task_run.id, message=str(exc))
                outcome = TaskRunDispatchOutcome(
                    status="failed",
                    summary_message=issue.operator_message,
                    issue_id=issue.id,
                    status_reason_code=issue.code,
                )
            return self._finalize_task_run(session, task_run.id, outcome)
        except Exception as exc:
            issue = self._record_worker_issue(session, task_run_id=task_run.id, message=f"worker_finalize_error: {exc}")
            return self._finalize_task_run(
                session,
                task_run.id,
                TaskRunDispatchOutcome(status="failed", issue_id=issue.id, status_reason_code=issue.code),
            )

    def _finalize_task_run(self, session: Session, task_run_id: int, outcome: TaskRunDispatchOutcome) -> TaskRun:
        task_run = session.get(TaskRun, task_run_id)
        if task_run is None:
            raise WebAppError(status_code=404, code="not_found", message="Task run does not exist")
        now = datetime.now(timezone.utc)
        final_status = outcome.status
        if task_run.cancel_requested_at is not None and final_status in {"success", "partial_success"}:
            final_status = "canceled"
        task_run.status = final_status
        task_run.status_reason_code = outcome.status_reason_code
        task_run.ended_at = now
        task_run.rows_fetched = int(outcome.rows_fetched or task_run.rows_fetched or 0)
        task_run.rows_saved = int(outcome.rows_saved or task_run.rows_saved or 0)
        task_run.rows_rejected = int(outcome.rows_rejected or task_run.rows_rejected or 0)
        task_run.primary_issue_id = outcome.issue_id or task_run.primary_issue_id
        task_run.current_object_json = {}
        if final_status == "success":
            task_run.unit_done = task_run.unit_total or task_run.unit_done
            task_run.progress_percent = 100
        if final_status == "canceled":
            task_run.canceled_at = task_run.canceled_at or now
        session.commit()
        refresh_error = self._refresh_snapshot_for_task_run(session, task_run)
        if refresh_error is not None:
            self._record_snapshot_refresh_failure(session, task_run.id, refresh_error)
        session.refresh(task_run)
        return task_run

    def _record_worker_issue(self, session: Session, *, task_run_id: int, message: str) -> TaskRunIssue:
        task_run = session.get(TaskRun, task_run_id)
        if task_run is None:
            raise WebAppError(status_code=404, code="not_found", message="Task run does not exist")
        issue = TaskRunIssue(
            task_run_id=task_run_id,
            node_id=task_run.current_node_id,
            severity="error",
            code="worker_error",
            title="任务运行器异常",
            operator_message="任务运行器在收尾时发生异常，需要开发核验任务状态。",
            suggested_action="不要重复提交大范围任务，先确认业务数据和任务状态。",
            technical_message=truncate_text(message, self.MAX_TECHNICAL_MESSAGE_LENGTH),
            technical_payload_json={"source_phase": "worker_finalize", "task_run_id": task_run_id},
            object_json=dict(task_run.current_object_json or {}),
            source_phase="worker_finalize",
            fingerprint=f"{task_run_id}:worker_error",
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(issue)
        session.flush()
        task_run.primary_issue_id = issue.id
        session.commit()
        return issue

    def _record_snapshot_refresh_failure(self, session: Session, task_run_id: int, error_message: str) -> None:
        task_run = session.get(TaskRun, task_run_id)
        if task_run is None:
            return
        issue = TaskRunIssue(
            task_run_id=task_run_id,
            node_id=None,
            severity="warning",
            code="dataset_snapshot_refresh_failed",
            title="数据状态刷新失败",
            operator_message="任务已结束，但数据状态快照刷新失败。",
            suggested_action="可以先查看业务数据；数据状态页可能暂时没有刷新。",
            technical_message=truncate_text(error_message, self.MAX_TECHNICAL_MESSAGE_LENGTH),
            technical_payload_json={"source_phase": "snapshot_refresh", "task_run_id": task_run_id},
            object_json=dict(task_run.current_object_json or {}),
            source_phase="snapshot_refresh",
            fingerprint=f"{task_run_id}:dataset_snapshot_refresh_failed",
            occurred_at=datetime.now(timezone.utc),
        )
        try:
            session.add(issue)
            session.commit()
        except Exception:
            session.rollback()

    @staticmethod
    def _refresh_snapshot_for_task_run(session: Session, task_run: TaskRun) -> str | None:
        if task_run.task_type != "dataset_action" or not task_run.resource_key:
            return None
        bind = session.get_bind()
        if bind is None:
            return "Database bind is unavailable for snapshot refresh."
        try:
            with Session(bind=bind, autoflush=False, autocommit=False, future=True) as snapshot_session:
                refreshed = DatasetStatusSnapshotService().refresh_for_execution(
                    snapshot_session,
                    spec_type="dataset_action",
                    spec_key=f"{task_run.resource_key}.maintain",
                    strict=True,
                )
            if refreshed <= 0:
                return f"Snapshot refresh returned 0 rows for dataset_action:{task_run.resource_key}.maintain."
            return None
        except Exception as exc:
            return str(exc)
