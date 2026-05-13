from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.schemas.wealth.market.context import MarketPageContextDto, MarketPageContextResponseDto


router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])


@router.get("/context", response_model=MarketPageContextResponseDto)
def get_market_page_context(
    market: str = Query(default="CN_A"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> MarketPageContextResponseDto:
    normalized_market = market.strip().upper()
    if normalized_market != "CN_A":
        raise WebAppError(status_code=400, code="400001", message=f"不支持的市场：{market}")
    try:
        context = MarketPageContextQuery().resolve_context(
            session,
            market=normalized_market,
            requested_trade_date=trade_date,
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc

    return MarketPageContextResponseDto(
        pageContext=MarketPageContextDto(
            market="CN_A",
            tradeDate=context.trade_date,
            prevTradeDate=context.prev_trade_date,
            isTradingDay=context.is_trading_day,
            sessionStatus=context.session_status,  # type: ignore[arg-type]
            timezone="Asia/Shanghai",
            generatedAt=context.generated_at,
            source=context.source,  # type: ignore[arg-type]
        )
    )
