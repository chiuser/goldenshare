from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries import TaskRunQueryService
from src.ops.schemas.task_run import (
    CreateTaskRunRequest,
    TaskRunCreateResponse,
    TaskRunIssueDetailResponse,
    TaskRunListResponse,
    TaskRunSummaryResponse,
    TaskRunViewResponse,
)
from src.ops.services import TaskRunCommandService


router = APIRouter(prefix="/ops/task-runs", tags=["ops"])


@router.get("", response_model=TaskRunListResponse)
def list_ops_task_runs(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    status: str | None = Query(None),
    trigger_source: str | None = Query(None),
    task_type: str | None = Query(None),
    resource_key: str | None = Query(None),
    schedule_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
) -> TaskRunListResponse:
    return TaskRunQueryService().list_task_runs(
        session,
        status=status,
        trigger_source=trigger_source,
        task_type=task_type,
        resource_key=resource_key,
        schedule_id=schedule_id,
        page=page,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=TaskRunSummaryResponse)
def get_ops_task_run_summary(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    status: str | None = Query(None),
    trigger_source: str | None = Query(None),
    task_type: str | None = Query(None),
    resource_key: str | None = Query(None),
    schedule_id: int | None = Query(None),
) -> TaskRunSummaryResponse:
    return TaskRunQueryService().get_summary(
        session,
        status=status,
        trigger_source=trigger_source,
        task_type=task_type,
        resource_key=resource_key,
        schedule_id=schedule_id,
    )


@router.post("", response_model=TaskRunCreateResponse)
def create_ops_task_run(
    body: CreateTaskRunRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> TaskRunCreateResponse:
    task_run_id = TaskRunCommandService().create_manual_task_run(
        session,
        user=user,
        task_type=body.task_type,
        resource_key=body.resource_key,
        action=body.action,
        time_input=body.time_input.model_dump(exclude_none=True),
        filters=body.filters,
        request_payload=body.request_payload,
    )
    task_run = TaskRunQueryService().get_view(session, task_run_id).run
    return TaskRunCreateResponse(
        id=task_run.id,
        status=task_run.status,
        title=task_run.title,
        resource_key=task_run.resource_key,
        created_at=task_run.requested_at,
    )


@router.get("/{task_run_id}/view", response_model=TaskRunViewResponse)
def get_ops_task_run_view(
    task_run_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> TaskRunViewResponse:
    return TaskRunQueryService().get_view(session, task_run_id)


@router.get("/{task_run_id}/issues/{issue_id}", response_model=TaskRunIssueDetailResponse)
def get_ops_task_run_issue(
    task_run_id: int,
    issue_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> TaskRunIssueDetailResponse:
    return TaskRunQueryService().get_issue_detail(session, task_run_id=task_run_id, issue_id=issue_id)


@router.post("/{task_run_id}/retry", response_model=TaskRunCreateResponse)
def retry_ops_task_run(
    task_run_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> TaskRunCreateResponse:
    new_task_run = TaskRunCommandService().retry_task_run(session, task_run_id=task_run_id, requested_by_user_id=user.id)
    return TaskRunCreateResponse(
        id=new_task_run.id,
        status=new_task_run.status,
        title=new_task_run.title,
        resource_key=new_task_run.resource_key,
        created_at=new_task_run.requested_at,
    )


@router.post("/{task_run_id}/cancel", response_model=TaskRunCreateResponse)
def cancel_ops_task_run(
    task_run_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> TaskRunCreateResponse:
    task_run = TaskRunCommandService().request_cancel(session, task_run_id=task_run_id, requested_by_user_id=user.id)
    return TaskRunCreateResponse(
        id=task_run.id,
        status=task_run.status,
        title=task_run.title,
        resource_key=task_run.resource_key,
        created_at=task_run.requested_at,
    )
