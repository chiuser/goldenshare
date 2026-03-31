from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.ops.job_execution import JobExecution
from src.models.ops.job_execution_event import JobExecutionEvent
from src.operations.specs import get_job_spec, get_workflow_spec
from src.web.exceptions import WebAppError


class OperationsExecutionService:
    def create_execution(
        self,
        session: Session,
        *,
        spec_type: str,
        spec_key: str,
        params_json: dict | None,
        trigger_source: str,
        requested_by_user_id: int | None,
        schedule_id: int | None = None,
    ) -> JobExecution:
        self._validate_spec(spec_type, spec_key)
        now = datetime.now(timezone.utc)
        execution = JobExecution(
            schedule_id=schedule_id,
            spec_type=spec_type,
            spec_key=spec_key,
            trigger_source=trigger_source,
            status="queued",
            requested_by_user_id=requested_by_user_id,
            requested_at=now,
            queued_at=now,
            params_json=params_json or {},
        )
        session.add(execution)
        session.flush()
        session.add_all(
            [
                JobExecutionEvent(
                    execution_id=execution.id,
                    event_type="created",
                    level="INFO",
                    message="Execution created",
                    payload_json={"trigger_source": trigger_source},
                    occurred_at=now,
                ),
                JobExecutionEvent(
                    execution_id=execution.id,
                    event_type="queued",
                    level="INFO",
                    message="Execution queued",
                    payload_json={},
                    occurred_at=now,
                ),
            ]
        )
        session.commit()
        session.refresh(execution)
        return execution

    def retry_execution(self, session: Session, *, execution_id: int, requested_by_user_id: int) -> JobExecution:
        existing = session.scalar(select(JobExecution).where(JobExecution.id == execution_id))
        if existing is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        return self.create_execution(
            session,
            spec_type=existing.spec_type,
            spec_key=existing.spec_key,
            params_json=dict(existing.params_json or {}),
            trigger_source="retry",
            requested_by_user_id=requested_by_user_id,
            schedule_id=existing.schedule_id,
        )

    def request_cancel(self, session: Session, *, execution_id: int, requested_by_user_id: int) -> JobExecution:
        execution = session.scalar(select(JobExecution).where(JobExecution.id == execution_id))
        if execution is None:
            raise WebAppError(status_code=404, code="not_found", message="Execution does not exist")
        if execution.status in {"success", "failed", "canceled"}:
            raise WebAppError(status_code=409, code="conflict", message="Execution is already finished")

        now = datetime.now(timezone.utc)
        execution.cancel_requested_at = now
        session.add(
            JobExecutionEvent(
                execution_id=execution.id,
                event_type="cancel_requested",
                level="INFO",
                message="Cancel requested",
                payload_json={"requested_by_user_id": requested_by_user_id},
                occurred_at=now,
            )
        )
        session.commit()
        session.refresh(execution)
        return execution

    @staticmethod
    def _validate_spec(spec_type: str, spec_key: str) -> None:
        if spec_type == "job":
            if get_job_spec(spec_key) is None:
                raise WebAppError(status_code=404, code="not_found", message="Job spec does not exist")
            return
        if spec_type == "workflow":
            if get_workflow_spec(spec_key) is None:
                raise WebAppError(status_code=404, code="not_found", message="Workflow spec does not exist")
            return
        raise WebAppError(status_code=422, code="validation_error", message="Unsupported spec_type")
