from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries.dataset_card_query_service import DatasetCardQueryService
from src.ops.schemas.dataset_card import DatasetCardListResponse


router = APIRouter(tags=["ops"])


@router.get("/ops/dataset-cards", response_model=DatasetCardListResponse)
def list_dataset_cards(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    source_key: str | None = Query(None),
    limit: int = Query(2000, ge=1, le=2000),
) -> DatasetCardListResponse:
    return DatasetCardQueryService().list_cards(session, source_key=source_key, limit=limit)
