from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries import ExecutionQueryService, ManualActionQueryService
from src.ops.schemas.execution import ExecutionDetailResponse
from src.ops.schemas.manual_action import ManualActionExecutionCreateRequest, ManualActionListResponse
from src.ops.services import ManualActionCommandService


router = APIRouter(prefix="/ops/manual-actions", tags=["ops"])


@router.get("", response_model=ManualActionListResponse)
def list_ops_manual_actions(
    _user: AuthenticatedUser = Depends(require_admin),
) -> ManualActionListResponse:
    return ManualActionQueryService().build_manual_actions()


@router.post("/{action_key}/executions", response_model=ExecutionDetailResponse)
def create_ops_manual_action_execution(
    action_key: str,
    body: ManualActionExecutionCreateRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionDetailResponse:
    execution_id = ManualActionCommandService().create_execution_for_action(
        session,
        user=user,
        action_key=action_key,
        body=body,
    )
    return ExecutionQueryService().get_execution_detail(session, execution_id)
