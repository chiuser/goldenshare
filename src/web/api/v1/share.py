from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.web.auth.dependencies import require_admin
from src.web.dependencies import get_db_session
from src.web.domain.user import AuthenticatedUser
from src.web.queries.share_market_query_service import safe_build_market_overview
from src.web.queries.share_terminal_query_service import ShareTerminalQueryService
from src.web.schemas.share import ShareMarketOverviewResponse
from src.web.schemas.share_terminal import ShareKlineResponse, ShareNewsResponse, ShareQuoteResponse
from src.web.schemas.share_terminal import ShareSecuritySuggestionsResponse


router = APIRouter(prefix="/share", tags=["share"])


@router.get("/market-overview", response_model=ShareMarketOverviewResponse)
def get_market_overview(
    limit: int = Query(default=8, ge=1, le=30),
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ShareMarketOverviewResponse:
    return safe_build_market_overview(session, limit=limit)


@router.get("/kline", response_model=ShareKlineResponse)
def get_kline(
    ts_code: str = Query(..., min_length=1),
    period: str = Query(default="d", pattern="^(d|w|m)$"),
    adjust_mode: str = Query(default="qfq", pattern="^(qfq|none)$"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=1500, ge=100, le=5000),
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ShareKlineResponse:
    return ShareTerminalQueryService().build_kline(
        session,
        ts_code=ts_code.strip().upper(),
        period=period,
        adjust_mode=adjust_mode,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@router.get("/quote", response_model=ShareQuoteResponse)
def get_quote(
    ts_code: str = Query(..., min_length=1),
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ShareQuoteResponse:
    return ShareTerminalQueryService().build_quote(
        session,
        ts_code=ts_code.strip().upper(),
    )


@router.get("/news", response_model=ShareNewsResponse)
def get_news(
    ts_code: str = Query(..., min_length=1),
    limit: int = Query(default=30, ge=1, le=100),
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ShareNewsResponse:
    return ShareTerminalQueryService().build_news(
        session,
        ts_code=ts_code.strip().upper(),
        limit=limit,
    )


@router.get("/securities", response_model=ShareSecuritySuggestionsResponse)
def search_securities(
    query: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=30),
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ShareSecuritySuggestionsResponse:
    return ShareTerminalQueryService().search_securities(
        session,
        query=query,
        limit=limit,
    )
