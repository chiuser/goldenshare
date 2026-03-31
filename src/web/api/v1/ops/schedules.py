from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.web.auth.dependencies import require_admin
from src.web.dependencies import get_db_session
from src.web.domain.user import AuthenticatedUser
from src.web.queries.ops import ScheduleQueryService
from src.web.schemas.ops.schedule import (
    CreateScheduleRequest,
    ScheduleDetailResponse,
    ScheduleListResponse,
    SchedulePreviewRequest,
    SchedulePreviewResponse,
    ScheduleRevisionListResponse,
    UpdateScheduleRequest,
)
from src.web.services.ops import OpsScheduleCommandService


router = APIRouter(prefix="/ops/schedules", tags=["ops"])


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
        cron_expr=body.cron_expr,
        timezone_name=body.timezone,
        calendar_policy=body.calendar_policy,
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
