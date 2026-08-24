from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.news.news_query_service import MarketNewsQueryService
from src.biz.schemas.wealth.market.news_communications import NewsCommunicationsResponseDto


router = APIRouter(prefix="/wealth/market/news", tags=["wealth-market"])


@router.get("/communications", response_model=NewsCommunicationsResponseDto)
def get_news_communications(
    market: str = Query(default="CN_A"),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> NewsCommunicationsResponseDto:
    normalized_market = market.strip().upper()
    if normalized_market != "CN_A":
        raise WebAppError(status_code=400, code="400001", message=f"不支持的市场：{market}")
    try:
        return MarketNewsQueryService().build_news_communications(
            session,
            market=normalized_market,
            debug=bool(debug),
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc
