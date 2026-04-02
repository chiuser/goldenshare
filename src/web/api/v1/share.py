from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.web.auth.dependencies import require_admin
from src.web.dependencies import get_db_session
from src.web.domain.user import AuthenticatedUser
from src.web.queries.share_market_query_service import safe_build_market_overview
from src.web.schemas.share import ShareMarketOverviewResponse


router = APIRouter(prefix="/share", tags=["share"])


@router.get("/market-overview", response_model=ShareMarketOverviewResponse)
def get_market_overview(
    limit: int = Query(default=8, ge=1, le=30),
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ShareMarketOverviewResponse:
    return safe_build_market_overview(session, limit=limit)
