from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.platform.auth.dependencies import require_admin
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.ops.queries.dataset_pipeline_mode_query_service import DatasetPipelineModeQueryService
from src.ops.schemas.dataset_pipeline import DatasetPipelineModeListResponse


router = APIRouter(tags=["ops"])


@router.get("/ops/pipeline-modes", response_model=DatasetPipelineModeListResponse)
def list_dataset_pipeline_modes(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> DatasetPipelineModeListResponse:
    return DatasetPipelineModeQueryService().list_modes(session, limit=limit, offset=offset)
