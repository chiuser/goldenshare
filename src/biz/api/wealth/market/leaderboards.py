from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.leaderboards.leaderboards_query_service import MarketLeaderboardsQueryService
from src.biz.schemas.wealth.market.leaderboards import LeaderboardsResponseDto


router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])


@router.get("/leaderboards", response_model=LeaderboardsResponseDto)
def get_market_leaderboards(
    request: Request,
    market: str = Query(default="CN_A"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    limit: int | None = Query(default=None, ge=1, le=50),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> LeaderboardsResponseDto:
    normalized_market = market.strip().upper()
    if normalized_market != "CN_A":
        raise WebAppError(status_code=400, code="400001", message=f"不支持的市场：{market}")
    if "boardKeys" in request.query_params:
        raise WebAppError(status_code=400, code="400001", message="boardKeys 不支持通过请求参数传入")
    try:
        return MarketLeaderboardsQueryService().build_leaderboards(
            session,
            market=normalized_market,
            trade_date=trade_date,
            limit=limit,
            debug=bool(debug),
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc

