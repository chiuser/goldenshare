from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.operations.runtime.dispatcher import DispatchOutcome, OperationsDispatcher
from src.operations.services.dataset_status_snapshot_service import DatasetStatusSnapshotService
from src.platform.exceptions import WebAppError


class OperationsWorker:
    def __init__(self, dispatcher: OperationsDispatcher | None = None) -> None:
        self.dispatcher = dispatcher or OperationsDispatcher()

    def run_next(self, session: Session) -> JobExecution | None:
        execution = session.scalar(
            select(JobExecution)
            .where(JobExecution.status == "queued")
            .order_by(JobExecution.requested_at.asc(), JobExecution.id.asc())
            .limit(1)
        )
        if execution is None:
            return None
        return self.run_execution(session, execution.id)

    def run_execution(self, session: Session, execution_id: int) -> JobExecution:
        execution = session.get(JobExecution, execution_id)
        if execution is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        if execution.status != "queued":
            raise WebAppError(status_code=409, code="conflict", message="Only queued executions can start immediately")
        if execution.cancel_requested_at is not None:
            execution.status = "canceled"
            execution.canceled_at = datetime.now(timezone.utc)
            session.add(
                JobExecutionEvent(
                    execution_id=execution.id,
                    event_type="canceled",
                    level="INFO",
                    message="Execution canceled before start",
                    payload_json={},
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            session.refresh(execution)
            return execution

        execution.status = "running"
        execution.started_at = datetime.now(timezone.utc)
        execution.progress_message = "系统已经开始处理这次任务。"
        execution.last_progress_at = execution.started_at
        session.add(
            JobExecutionEvent(
                execution_id=execution.id,
                event_type="started",
                level="INFO",
                message="Execution started",
                payload_json={},
                occurred_at=execution.started_at,
            )
        )
        session.commit()

        try:
            try:
                outcome = self.dispatcher.dispatch(session, execution)
            except Exception as exc:
                outcome = DispatchOutcome(
                    status="failed",
                    error_code="dispatcher_error",
                    error_message=str(exc),
                    summary_message=str(exc),
                )
            return self._finalize_execution(session, execution.id, outcome)
        except Exception as exc:
            return self._emergency_fail_execution(session, execution.id, f"worker_finalize_error: {exc}")

    def _finalize_execution(self, session: Session, execution_id: int, outcome: DispatchOutcome) -> JobExecution:
        execution = session.get(JobExecution, execution_id)
        assert execution is not None
        last_progress_message = execution.progress_message
        execution.status = outcome.status
        execution.ended_at = datetime.now(timezone.utc)
        execution.rows_fetched = outcome.rows_fetched
        execution.rows_written = outcome.rows_written
        execution.summary_message = outcome.summary_message
        execution.error_code = outcome.error_code
        execution.error_message = outcome.error_message
        if execution.cancel_requested_at is not None and outcome.status in {"success", "partial_success"}:
            outcome.status = "canceled"
            outcome.summary_message = outcome.summary_message or "任务已收到停止请求，已在当前处理单元后停止。"
            execution.summary_message = outcome.summary_message
            execution.error_code = None
            execution.error_message = None
        if outcome.status == "success" and execution.progress_total is not None:
            execution.progress_current = execution.progress_total
            execution.progress_percent = 100
        if outcome.status == "canceled":
            execution.canceled_at = execution.canceled_at or execution.ended_at
        if outcome.status == "failed":
            # Preserve the latest business progress for troubleshooting.
            execution.progress_message = last_progress_message or outcome.summary_message
        else:
            execution.progress_message = outcome.summary_message or execution.progress_message
        execution.last_progress_at = execution.ended_at
        final_event_type = "succeeded"
        level = "INFO"
        if outcome.status == "failed":
            final_event_type = "failed"
            level = "ERROR"
        elif outcome.status == "partial_success":
            final_event_type = "partial_success"
            level = "WARNING"
        elif outcome.status == "canceled":
            final_event_type = "canceled"
        session.add(
            JobExecutionEvent(
                execution_id=execution.id,
                event_type=final_event_type,
                level=level,
                message=outcome.summary_message,
                payload_json={},
                occurred_at=execution.ended_at,
            )
        )
        session.commit()
        DatasetStatusSnapshotService().refresh_for_execution(
            session,
            spec_type=execution.spec_type,
            spec_key=execution.spec_key,
        )
        session.refresh(execution)
        return execution

    def _emergency_fail_execution(self, session: Session, execution_id: int, message: str) -> JobExecution:
        execution = session.get(JobExecution, execution_id)
        if execution is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        last_progress_message = execution.progress_message
        execution.status = "failed"
        execution.ended_at = datetime.now(timezone.utc)
        execution.summary_message = message
        execution.error_code = execution.error_code or "worker_finalize_error"
        execution.error_message = message
        execution.last_progress_at = execution.ended_at
        execution.progress_message = last_progress_message or message
        session.add(
            JobExecutionEvent(
                execution_id=execution.id,
                event_type="failed",
                level="ERROR",
                message=message,
                payload_json={},
                occurred_at=execution.ended_at,
            )
        )
        session.commit()
        session.refresh(execution)
        return execution
