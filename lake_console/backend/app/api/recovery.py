from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from lake_console.backend.app.schemas import (
    LakeRecoveryRepositorySummaryResponse,
    LakeRecoverySnapshotDetailResponse,
    LakeRecoverySnapshotListResponse,
)
from lake_console.backend.app.services.kopia_recovery_service import KopiaRecoveryService
from lake_console.backend.app.settings import load_settings


router = APIRouter(prefix="/api/recovery", tags=["recovery"])


@router.get("/repository-summary", response_model=LakeRecoveryRepositorySummaryResponse)
def repository_summary() -> LakeRecoveryRepositorySummaryResponse:
    settings = load_settings()
    service = KopiaRecoveryService(
        settings.lake_root,
        kopia_bin=settings.kopia_bin,
        kopia_config_path=settings.kopia_config_path,
        kopia_password=settings.kopia_password,
    )
    return LakeRecoveryRepositorySummaryResponse(**service.get_repository_summary())


@router.get("/snapshots", response_model=LakeRecoverySnapshotListResponse)
def list_recovery_snapshots(
    scope: str | None = Query(default=None),
    dataset_key: str | None = Query(default=None),
    pinned: bool | None = Query(default=None),
    baseline_only: bool | None = Query(default=None),
    query: str | None = Query(default=None),
    finished_from: str | None = Query(default=None),
    finished_to: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> LakeRecoverySnapshotListResponse:
    settings = load_settings()
    service = KopiaRecoveryService(
        settings.lake_root,
        kopia_bin=settings.kopia_bin,
        kopia_config_path=settings.kopia_config_path,
        kopia_password=settings.kopia_password,
    )
    return LakeRecoverySnapshotListResponse(
        **service.list_snapshots(
            scope=scope,
            dataset_key=dataset_key,
            pinned=pinned,
            baseline_only=baseline_only,
            query=query,
            finished_from=finished_from,
            finished_to=finished_to,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/snapshots/{snapshot_id}", response_model=LakeRecoverySnapshotDetailResponse)
def get_recovery_snapshot(snapshot_id: str) -> LakeRecoverySnapshotDetailResponse:
    settings = load_settings()
    service = KopiaRecoveryService(
        settings.lake_root,
        kopia_bin=settings.kopia_bin,
        kopia_config_path=settings.kopia_config_path,
        kopia_password=settings.kopia_password,
    )
    payload = service.get_snapshot(snapshot_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"未找到快照：{snapshot_id}")
    return LakeRecoverySnapshotDetailResponse(**payload)
