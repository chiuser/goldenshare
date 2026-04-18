from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.ops.runtime.dispatcher import DispatchOutcome, OperationsDispatcher
from src.ops.services.operations_dataset_status_snapshot_service import DatasetStatusSnapshotService
from src.platform.exceptions import WebAppError
from src.utils import truncate_text


class OperationsWorker:
    MAX_EXECUTION_ERROR_MESSAGE_LENGTH = 16_000
    MAX_EXECUTION_SUMMARY_LENGTH = 8_000
    MAX_PROGRESS_MESSAGE_LENGTH = 1_000

    def __init__(self, dispatcher: OperationsDispatcher | None = None) -> None:
        self.dispatcher = dispatcher or OperationsDispatcher()

    def run_next(self, session: Session) -> JobExecution | None:
        canceled = self._cancel_next_queued_execution(session)
        if canceled is not None:
            return canceled

        while True:
            execution_id = session.scalar(
                select(JobExecution.id)
                .where(JobExecution.status == "queued")
                .where(JobExecution.cancel_requested_at.is_(None))
                .order_by(JobExecution.requested_at.asc(), JobExecution.id.asc())
                .limit(1)
            )
            if execution_id is None:
                return None
            if not self._claim_execution(session, execution_id):
                continue
            return self._run_started_execution(session, execution_id)

    def run_execution(self, session: Session, execution_id: int) -> JobExecution:
        execution = session.get(JobExecution, execution_id)
        if execution is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        if execution.status != "queued":
            raise WebAppError(status_code=409, code="conflict", message="Only queued executions can start immediately")
        if execution.cancel_requested_at is not None:
            canceled = self._cancel_queued_execution(session, execution.id)
            if canceled is None:
                raise WebAppError(status_code=409, code="conflict", message="Execution status changed before canceling")
            return canceled

        if not self._claim_execution(session, execution.id):
            raise WebAppError(status_code=409, code="conflict", message="Execution status changed before start")
        return self._run_started_execution(session, execution.id)

    def _cancel_next_queued_execution(self, session: Session) -> JobExecution | None:
        execution_id = session.scalar(
            select(JobExecution.id)
            .where(JobExecution.status == "queued")
            .where(JobExecution.cancel_requested_at.is_not(None))
            .order_by(JobExecution.requested_at.asc(), JobExecution.id.asc())
            .limit(1)
        )
        if execution_id is None:
            return None
        return self._cancel_queued_execution(session, execution_id)

    def _cancel_queued_execution(self, session: Session, execution_id: int) -> JobExecution | None:
        canceled_at = datetime.now(timezone.utc)
        result = session.execute(
            update(JobExecution)
            .where(JobExecution.id == execution_id)
            .where(JobExecution.status == "queued")
            .where(JobExecution.cancel_requested_at.is_not(None))
            .values(
                status="canceled",
                canceled_at=canceled_at,
                ended_at=canceled_at,
                progress_message="Execution canceled before start",
                last_progress_at=canceled_at,
            )
        )
        if result.rowcount != 1:
            session.rollback()
            return None
        session.add(
            JobExecutionEvent(
                execution_id=execution_id,
                event_type="canceled",
                level="INFO",
                message="Execution canceled before start",
                payload_json={},
                occurred_at=canceled_at,
            )
        )
        session.commit()
        execution = session.get(JobExecution, execution_id)
        if execution is None:
            return None
        session.refresh(execution)
        return execution

    def _claim_execution(self, session: Session, execution_id: int) -> bool:
        started_at = datetime.now(timezone.utc)
        result = session.execute(
            update(JobExecution)
            .where(JobExecution.id == execution_id)
            .where(JobExecution.status == "queued")
            .where(JobExecution.cancel_requested_at.is_(None))
            .values(
                status="running",
                started_at=started_at,
                progress_message="系统已经开始处理这次任务。",
                last_progress_at=started_at,
            )
        )
        if result.rowcount != 1:
            session.rollback()
            return False
        session.add(
            JobExecutionEvent(
                execution_id=execution_id,
                event_type="started",
                level="INFO",
                message="Execution started",
                payload_json={},
                occurred_at=started_at,
            )
        )
        session.commit()
        return True

    def _run_started_execution(self, session: Session, execution_id: int) -> JobExecution:
        execution = session.get(JobExecution, execution_id)
        if execution is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        try:
            try:
                outcome = self.dispatcher.dispatch(session, execution)
            except Exception as exc:
                safe_message = self._sanitize_error_message(str(exc))
                outcome = DispatchOutcome(
                    status="failed",
                    error_code="dispatcher_error",
                    error_message=safe_message,
                    summary_message=safe_message,
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
        execution.summary_message = self._sanitize_summary_message(outcome.summary_message)
        execution.error_code = outcome.error_code
        execution.error_message = self._sanitize_error_message(outcome.error_message)
        if execution.cancel_requested_at is not None and outcome.status in {"success", "partial_success"}:
            outcome.status = "canceled"
            outcome.summary_message = outcome.summary_message or "任务已收到停止请求，已在当前处理单元后停止。"
            execution.summary_message = self._sanitize_summary_message(outcome.summary_message)
            execution.error_code = None
            execution.error_message = None
        if outcome.status == "success" and execution.progress_total is not None:
            execution.progress_current = execution.progress_total
            execution.progress_percent = 100
        if outcome.status == "canceled":
            execution.canceled_at = execution.canceled_at or execution.ended_at
        if outcome.status == "failed":
            # Preserve the latest business progress for troubleshooting.
            execution.progress_message = self._sanitize_progress_message(last_progress_message or outcome.summary_message)
        else:
            execution.progress_message = self._sanitize_progress_message(outcome.summary_message or execution.progress_message)
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
                message=self._sanitize_summary_message(outcome.summary_message),
                payload_json={},
                occurred_at=execution.ended_at,
            )
        )
        session.commit()
        refresh_error = self._refresh_snapshot_for_execution(
            session,
            spec_type=execution.spec_type,
            spec_key=execution.spec_key,
        )
        if refresh_error is not None:
            self._record_snapshot_refresh_failure(session, execution.id, refresh_error)
        session.refresh(execution)
        return execution

    def _emergency_fail_execution(self, session: Session, execution_id: int, message: str) -> JobExecution:
        execution = session.get(JobExecution, execution_id)
        if execution is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        last_progress_message = execution.progress_message
        execution.status = "failed"
        execution.ended_at = datetime.now(timezone.utc)
        execution.summary_message = self._sanitize_summary_message(message)
        execution.error_code = execution.error_code or "worker_finalize_error"
        execution.error_message = self._sanitize_error_message(message)
        execution.last_progress_at = execution.ended_at
        execution.progress_message = self._sanitize_progress_message(last_progress_message or message)
        session.add(
            JobExecutionEvent(
                execution_id=execution.id,
                event_type="failed",
                level="ERROR",
                message=self._sanitize_summary_message(message),
                payload_json={},
                occurred_at=execution.ended_at,
            )
        )
        session.commit()
        session.refresh(execution)
        return execution

    def _record_snapshot_refresh_failure(self, session: Session, execution_id: int, error_message: str) -> None:
        detail = self._sanitize_error_message(error_message)
        try:
            session.add(
                JobExecutionEvent(
                    execution_id=execution_id,
                    event_type="warning",
                    level="WARNING",
                    message="Dataset status snapshot refresh failed",
                    payload_json={"code": "dataset_snapshot_refresh_failed", "detail": detail},
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
        except Exception:
            session.rollback()

    @staticmethod
    def _refresh_snapshot_for_execution(session: Session, *, spec_type: str, spec_key: str) -> str | None:
        bind = session.get_bind()
        if bind is None:
            return "Database bind is unavailable for snapshot refresh."
        try:
            with Session(bind=bind, autoflush=False, autocommit=False, future=True) as snapshot_session:
                refreshed = DatasetStatusSnapshotService().refresh_for_execution(
                    snapshot_session,
                    spec_type=spec_type,
                    spec_key=spec_key,
                    strict=True,
                )
            if refreshed <= 0:
                return f"Snapshot refresh returned 0 rows for {spec_type}:{spec_key}."
            return None
        except Exception as exc:
            return str(exc)

    @classmethod
    def _sanitize_error_message(cls, message: str | None) -> str | None:
        return truncate_text(message, cls.MAX_EXECUTION_ERROR_MESSAGE_LENGTH)

    @classmethod
    def _sanitize_summary_message(cls, message: str | None) -> str | None:
        return truncate_text(message, cls.MAX_EXECUTION_SUMMARY_LENGTH)

    @classmethod
    def _sanitize_progress_message(cls, message: str | None) -> str | None:
        return truncate_text(message, cls.MAX_PROGRESS_MESSAGE_LENGTH)
