from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries import ManualActionQueryService, TaskRunQueryService
from src.ops.schemas.manual_action import ManualActionListResponse, ManualActionTaskRunCreateRequest
from src.ops.schemas.task_run import TaskRunViewResponse
from src.ops.services import ManualActionCommandService


router = APIRouter(prefix="/ops/manual-actions", tags=["ops"])


@router.get("", response_model=ManualActionListResponse)
def list_ops_manual_actions(
    _user: AuthenticatedUser = Depends(require_admin),
) -> ManualActionListResponse:
    return ManualActionQueryService().build_manual_actions()


@router.post("/{action_key}/task-runs", response_model=TaskRunViewResponse)
def create_ops_manual_action_task_run(
    action_key: str,
    body: ManualActionTaskRunCreateRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> TaskRunViewResponse:
    task_run_id = ManualActionCommandService().create_task_run_for_action(
        session,
        user=user,
        action_key=action_key,
        body=body,
    )
    return TaskRunQueryService().get_view(session, task_run_id)
