from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries.resolution_release_query_service import ResolutionReleaseQueryService
from src.ops.schemas.resolution_release import (
    CreateResolutionReleaseRequest,
    ResolutionReleaseDetailResponse,
    ResolutionReleaseListResponse,
    ResolutionReleaseStageStatusListResponse,
    UpdateResolutionReleaseStatusRequest,
    UpsertResolutionReleaseStageStatusRequest,
)
from src.ops.services.resolution_release_service import OpsResolutionReleaseCommandService


router = APIRouter(tags=["ops"])


@router.get("/ops/releases", response_model=ResolutionReleaseListResponse)
def list_resolution_releases(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    dataset_key: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ResolutionReleaseListResponse:
    return ResolutionReleaseQueryService().list_releases(
        session,
        dataset_key=dataset_key,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/ops/releases", response_model=ResolutionReleaseDetailResponse)
def create_resolution_release(
    body: CreateResolutionReleaseRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ResolutionReleaseDetailResponse:
    release_id = OpsResolutionReleaseCommandService().create_release(
        session,
        user=user,
        dataset_key=body.dataset_key,
        target_policy_version=body.target_policy_version,
        status=body.status,
        rollback_to_release_id=body.rollback_to_release_id,
    )
    return ResolutionReleaseQueryService().get_release_detail(session, release_id)


@router.get("/ops/releases/{release_id}", response_model=ResolutionReleaseDetailResponse)
def get_resolution_release(
    release_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ResolutionReleaseDetailResponse:
    return ResolutionReleaseQueryService().get_release_detail(session, release_id)


@router.patch("/ops/releases/{release_id}/status", response_model=ResolutionReleaseDetailResponse)
def update_resolution_release_status(
    release_id: int,
    body: UpdateResolutionReleaseStatusRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ResolutionReleaseDetailResponse:
    updated_release_id = OpsResolutionReleaseCommandService().update_release_status(
        session,
        user=user,
        release_id=release_id,
        status=body.status,
        finished_at=body.finished_at,
    )
    return ResolutionReleaseQueryService().get_release_detail(session, updated_release_id)


@router.get("/ops/releases/{release_id}/stages", response_model=ResolutionReleaseStageStatusListResponse)
def list_resolution_release_stages(
    release_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    dataset_key: str | None = Query(None),
    source_key: str | None = Query(None),
    stage: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ResolutionReleaseStageStatusListResponse:
    return ResolutionReleaseQueryService().list_release_stage_statuses(
        session,
        release_id=release_id,
        dataset_key=dataset_key,
        source_key=source_key,
        stage=stage,
        limit=limit,
        offset=offset,
    )


@router.put("/ops/releases/{release_id}/stages", response_model=ResolutionReleaseStageStatusListResponse)
def upsert_resolution_release_stages(
    release_id: int,
    body: UpsertResolutionReleaseStageStatusRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ResolutionReleaseStageStatusListResponse:
    OpsResolutionReleaseCommandService().upsert_release_stage_statuses(
        session,
        user=user,
        release_id=release_id,
        items=[item.model_dump() for item in body.items],
    )
    return ResolutionReleaseQueryService().list_release_stage_statuses(
        session,
        release_id=release_id,
    )
