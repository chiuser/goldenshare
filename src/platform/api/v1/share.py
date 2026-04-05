from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.platform.auth.dependencies import require_admin
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.platform.queries.share_market_query_service import safe_build_market_overview
from src.platform.schemas.share import ShareMarketOverviewResponse


router = APIRouter(prefix="/share", tags=["share"])


@router.get("/market-overview", response_model=ShareMarketOverviewResponse)
def get_market_overview(
    limit: int = Query(default=8, ge=1, le=30),
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ShareMarketOverviewResponse:
    return safe_build_market_overview(session, limit=limit)
