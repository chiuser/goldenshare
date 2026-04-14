from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.platform.auth.dependencies import require_admin
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.ops.queries.layer_snapshot_query_service import LayerSnapshotQueryService
from src.ops.schemas.layer_snapshot import LayerSnapshotHistoryResponse, LayerSnapshotLatestResponse


router = APIRouter(tags=["ops"])


@router.get("/ops/layer-snapshots/history", response_model=LayerSnapshotHistoryResponse)
def list_layer_snapshot_history(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    snapshot_date_from: date | None = Query(None),
    snapshot_date_to: date | None = Query(None),
    dataset_key: str | None = Query(None),
    source_key: str | None = Query(None),
    stage: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> LayerSnapshotHistoryResponse:
    return LayerSnapshotQueryService().list_history(
        session,
        snapshot_date_from=snapshot_date_from,
        snapshot_date_to=snapshot_date_to,
        dataset_key=dataset_key,
        source_key=source_key,
        stage=stage,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/ops/layer-snapshots/latest", response_model=LayerSnapshotLatestResponse)
def list_layer_snapshot_latest(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    dataset_key: str | None = Query(None),
    source_key: str | None = Query(None),
    stage: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
) -> LayerSnapshotLatestResponse:
    return LayerSnapshotQueryService().list_latest(
        session,
        dataset_key=dataset_key,
        source_key=source_key,
        stage=stage,
        status=status,
        limit=limit,
    )
