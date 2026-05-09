from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.turnover.turnover_query_service import MarketTurnoverQueryService
from src.biz.schemas.wealth.market.turnover import TurnoverResponseDto


router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])


@router.get("/turnover", response_model=TurnoverResponseDto)
def get_market_turnover(
    market: str = Query(default="CN_A"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> TurnoverResponseDto:
    normalized_market = market.strip().upper()
    if normalized_market != "CN_A":
        raise WebAppError(status_code=400, code="400001", message=f"不支持的市场：{market}")
    try:
        return MarketTurnoverQueryService().build_turnover(
            session,
            market=normalized_market,
            trade_date=trade_date,
            debug=bool(debug),
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc
