from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.breadth.breadth_query_service import MarketBreadthQueryService
from src.biz.schemas.wealth.market.breadth import BreadthResponseDto


router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])


def get_market_breadth_query_service() -> MarketBreadthQueryService:
    return MarketBreadthQueryService()


@router.get("/breadth", response_model=BreadthResponseDto)
def get_market_breadth(
    market: str = Query(default="CN_A"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
    service: MarketBreadthQueryService = Depends(get_market_breadth_query_service),
) -> BreadthResponseDto:
    normalized_market = market.strip().upper()
    if normalized_market != "CN_A":
        raise WebAppError(status_code=400, code="400001", message=f"不支持的市场：{market}")
    try:
        return service.build_breadth(
            session,
            market=normalized_market,
            trade_date=trade_date,
            debug=bool(debug),
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc
