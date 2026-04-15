from __future__ import annotations

import json
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_schedule import JobSchedule
from src.platform.auth.dependencies import require_admin
from src.platform.auth.domain import AuthenticatedUser
from src.platform.auth.jwt_service import JWTService
from src.platform.auth.user_repository import UserRepository
from src.platform.dependencies import get_db_session
from src.platform.exceptions import WebAppError
from src.ops.queries import ScheduleQueryService
from src.ops.schemas.schedule import (
    CreateScheduleRequest,
    DeleteScheduleResponse,
    ScheduleDetailResponse,
    ScheduleListResponse,
    SchedulePreviewRequest,
    SchedulePreviewResponse,
    ScheduleRevisionListResponse,
    UpdateScheduleRequest,
)
from src.ops.services import OpsScheduleCommandService


router = APIRouter(prefix="/ops/schedules", tags=["ops"])


def _require_admin_from_stream_token(session: Session, token: str) -> None:
    jwt_service = JWTService()
    token_payload = jwt_service.decode(token)
    user = UserRepository().get_by_id(session, token_payload.sub)
    if user is None:
        raise WebAppError(status_code=401, code="unauthorized", message="User does not exist")
    if not user.is_active:
        raise WebAppError(status_code=401, code="unauthorized", message="User is inactive")
    if not user.is_admin:
        raise WebAppError(status_code=403, code="forbidden", message="Admin permission required")


def _schedule_signature(session: Session) -> dict[str, str | int | None]:
    schedule_updated_at = session.scalar(select(func.max(JobSchedule.updated_at)))
    execution_requested_at = session.scalar(select(func.max(JobExecution.requested_at)))
    active_executions = session.scalar(
        select(func.count())
        .select_from(JobExecution)
        .where(JobExecution.status.in_(("queued", "running", "canceling")))
    ) or 0
    return {
        "schedule_updated_at": schedule_updated_at.isoformat() if isinstance(schedule_updated_at, datetime) else None,
        "execution_requested_at": execution_requested_at.isoformat() if isinstance(execution_requested_at, datetime) else None,
        "active_executions": int(active_executions),
    }


@router.get("", response_model=ScheduleListResponse)
def list_ops_schedules(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    status: str | None = Query(None),
    spec_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ScheduleListResponse:
    return ScheduleQueryService().list_schedules(
        session,
        status=status,
        spec_type=spec_type,
        limit=limit,
        offset=offset,
    )


@router.get("/stream")
def stream_ops_schedules(
    token: str = Query(..., min_length=8),
    session: Session = Depends(get_db_session),
):
    _require_admin_from_stream_token(session, token)

    def event_stream():
        last_signature: dict[str, str | int | None] | None = None
        while True:
            current_signature = _schedule_signature(session)
            if current_signature != last_signature:
                payload = json.dumps(current_signature, ensure_ascii=False)
                yield f"event: schedules\ndata: {payload}\n\n"
                last_signature = current_signature
            else:
                yield ": ping\n\n"
            time.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("", response_model=ScheduleDetailResponse)
def create_ops_schedule(
    body: CreateScheduleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ScheduleDetailResponse:
    schedule_id = OpsScheduleCommandService().create_schedule(
        session,
        user=user,
        spec_type=body.spec_type,
        spec_key=body.spec_key,
        display_name=body.display_name,
        schedule_type=body.schedule_type,
        trigger_mode=body.trigger_mode,
        cron_expr=body.cron_expr,
        timezone_name=body.timezone,
        calendar_policy=body.calendar_policy,
        probe_config_json=body.probe_config.model_dump() if body.probe_config else {},
        params_json=body.params_json,
        retry_policy_json=body.retry_policy_json,
        concurrency_policy_json=body.concurrency_policy_json,
        next_run_at=body.next_run_at,
    )
    return ScheduleQueryService().get_schedule_detail(session, schedule_id)


@router.get("/{schedule_id}", response_model=ScheduleDetailResponse)
def get_ops_schedule_detail(
    schedule_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ScheduleDetailResponse:
    return ScheduleQueryService().get_schedule_detail(session, schedule_id)


@router.patch("/{schedule_id}", response_model=ScheduleDetailResponse)
def update_ops_schedule(
    schedule_id: int,
    body: UpdateScheduleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ScheduleDetailResponse:
    updated_schedule_id = OpsScheduleCommandService().update_schedule(
        session,
        user=user,
        schedule_id=schedule_id,
        changes=body.model_dump(exclude_unset=True),
    )
    return ScheduleQueryService().get_schedule_detail(session, updated_schedule_id)


@router.post("/{schedule_id}/pause", response_model=ScheduleDetailResponse)
def pause_ops_schedule(
    schedule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ScheduleDetailResponse:
    updated_schedule_id = OpsScheduleCommandService().pause_schedule(session, user=user, schedule_id=schedule_id)
    return ScheduleQueryService().get_schedule_detail(session, updated_schedule_id)


@router.post("/{schedule_id}/resume", response_model=ScheduleDetailResponse)
def resume_ops_schedule(
    schedule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ScheduleDetailResponse:
    updated_schedule_id = OpsScheduleCommandService().resume_schedule(session, user=user, schedule_id=schedule_id)
    return ScheduleQueryService().get_schedule_detail(session, updated_schedule_id)


@router.delete("/{schedule_id}", response_model=DeleteScheduleResponse)
def delete_ops_schedule(
    schedule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> DeleteScheduleResponse:
    deleted_schedule_id = OpsScheduleCommandService().delete_schedule(session, user=user, schedule_id=schedule_id)
    return DeleteScheduleResponse(id=deleted_schedule_id)


@router.get("/{schedule_id}/revisions", response_model=ScheduleRevisionListResponse)
def list_ops_schedule_revisions(
    schedule_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ScheduleRevisionListResponse:
    return ScheduleQueryService().list_schedule_revisions(session, schedule_id)


@router.post("/preview", response_model=SchedulePreviewResponse)
def preview_ops_schedule(
    body: SchedulePreviewRequest,
    _user: AuthenticatedUser = Depends(require_admin),
) -> SchedulePreviewResponse:
    preview_times = OpsScheduleCommandService().preview_schedule(
        schedule_type=body.schedule_type,
        cron_expr=body.cron_expr,
        timezone_name=body.timezone,
        next_run_at=body.next_run_at,
        count=body.count,
    )
    return SchedulePreviewResponse(
        schedule_type=body.schedule_type,
        timezone=body.timezone,
        preview_times=preview_times,
    )
