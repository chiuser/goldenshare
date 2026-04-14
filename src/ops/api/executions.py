from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.platform.auth.dependencies import require_admin
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.ops.queries import ExecutionQueryService
from src.ops.schemas.execution import (
    CreateExecutionRequest,
    ExecutionDetailResponse,
    ExecutionEventsResponse,
    ExecutionLogsResponse,
    ExecutionListResponse,
    ExecutionStepsResponse,
)
from src.ops.services import OpsExecutionCommandService


router = APIRouter(prefix="/ops/executions", tags=["ops"])


@router.get("", response_model=ExecutionListResponse)
def list_ops_executions(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    status: str | None = Query(None),
    trigger_source: str | None = Query(None),
    spec_type: str | None = Query(None),
    spec_key: str | None = Query(None),
    dataset_key: str | None = Query(None),
    source_key: str | None = Query(None),
    stage: str | None = Query(None),
    run_scope: str | None = Query(None),
    schedule_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ExecutionListResponse:
    return ExecutionQueryService().list_executions(
        session,
        status=status,
        trigger_source=trigger_source,
        spec_type=spec_type,
        spec_key=spec_key,
        dataset_key=dataset_key,
        source_key=source_key,
        stage=stage,
        run_scope=run_scope,
        schedule_id=schedule_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{execution_id}", response_model=ExecutionDetailResponse)
def get_ops_execution_detail(
    execution_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionDetailResponse:
    return ExecutionQueryService().get_execution_detail(session, execution_id)


@router.get("/{execution_id}/steps", response_model=ExecutionStepsResponse)
def list_ops_execution_steps(
    execution_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionStepsResponse:
    return ExecutionQueryService().get_execution_steps(session, execution_id)


@router.get("/{execution_id}/events", response_model=ExecutionEventsResponse)
def list_ops_execution_events(
    execution_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionEventsResponse:
    return ExecutionQueryService().get_execution_events(session, execution_id)


@router.get("/{execution_id}/logs", response_model=ExecutionLogsResponse)
def list_ops_execution_logs(
    execution_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionLogsResponse:
    return ExecutionQueryService().get_execution_logs(session, execution_id)


@router.post("", response_model=ExecutionDetailResponse)
def create_ops_execution(
    body: CreateExecutionRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionDetailResponse:
    execution_id = OpsExecutionCommandService().create_manual_execution(
        session,
        user=user,
        spec_type=body.spec_type,
        spec_key=body.spec_key,
        params_json=body.params_json,
    )
    return ExecutionQueryService().get_execution_detail(session, execution_id)


@router.post("/run-now", response_model=ExecutionDetailResponse)
def create_ops_execution_and_run_now(
    body: CreateExecutionRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionDetailResponse:
    execution_id = OpsExecutionCommandService().create_manual_execution(
        session,
        user=user,
        spec_type=body.spec_type,
        spec_key=body.spec_key,
        params_json=body.params_json,
    )
    return ExecutionQueryService().get_execution_detail(session, execution_id)


@router.post("/{execution_id}/retry", response_model=ExecutionDetailResponse)
def retry_ops_execution(
    execution_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionDetailResponse:
    new_execution_id = OpsExecutionCommandService().retry_execution(session, user=user, execution_id=execution_id)
    return ExecutionQueryService().get_execution_detail(session, new_execution_id)


@router.post("/{execution_id}/retry-now", response_model=ExecutionDetailResponse)
def retry_ops_execution_and_run_now(
    execution_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionDetailResponse:
    new_execution_id = OpsExecutionCommandService().retry_execution(session, user=user, execution_id=execution_id)
    return ExecutionQueryService().get_execution_detail(session, new_execution_id)


@router.post("/{execution_id}/run-now", response_model=ExecutionDetailResponse)
def run_ops_execution_now(
    execution_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionDetailResponse:
    return ExecutionQueryService().get_execution_detail(session, execution_id)


@router.post("/{execution_id}/cancel", response_model=ExecutionDetailResponse)
def cancel_ops_execution(
    execution_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ExecutionDetailResponse:
    result_execution_id = OpsExecutionCommandService().cancel_execution(session, user=user, execution_id=execution_id)
    return ExecutionQueryService().get_execution_detail(session, result_execution_id)
