from __future__ import annotations

from sqlalchemy.orm import Session

from src.operations.services import OperationsExecutionService
from src.web.domain.user import AuthenticatedUser


class OpsExecutionCommandService:
    def __init__(self) -> None:
        self.execution_service = OperationsExecutionService()

    def create_manual_execution(self, session: Session, *, user: AuthenticatedUser, spec_type: str, spec_key: str, params_json: dict) -> int:
        execution = self.execution_service.create_execution(
            session,
            spec_type=spec_type,
            spec_key=spec_key,
            params_json=params_json,
            trigger_source="manual",
            requested_by_user_id=user.id,
        )
        return execution.id

    def retry_execution(self, session: Session, *, user: AuthenticatedUser, execution_id: int) -> int:
        execution = self.execution_service.retry_execution(session, execution_id=execution_id, requested_by_user_id=user.id)
        return execution.id

    def cancel_execution(self, session: Session, *, user: AuthenticatedUser, execution_id: int) -> int:
        execution = self.execution_service.request_cancel(session, execution_id=execution_id, requested_by_user_id=user.id)
        return execution.id
