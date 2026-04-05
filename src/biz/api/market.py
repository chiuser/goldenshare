from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.biz.queries.quote_query_service import QuoteQueryService
from src.biz.schemas.quote import MarketTradeCalendarResponse
from src.platform.auth.dependencies import require_quote_access
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.platform.exceptions import WebAppError


router = APIRouter(prefix="/market", tags=["market"])


@router.get("/trade-calendar", response_model=MarketTradeCalendarResponse)
def get_trade_calendar(
    exchange: str = Query(default="SSE"),
    start_date: date = Query(...),
    end_date: date = Query(...),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> MarketTradeCalendarResponse:
    normalized_exchange = exchange.strip().upper()
    if start_date > end_date:
        raise WebAppError(status_code=400, code="INVALID_DATE_RANGE", message="起始日期不能晚于结束日期")
    return QuoteQueryService().build_trade_calendar(
        session,
        exchange=normalized_exchange,
        start_date=start_date,
        end_date=end_date,
    )
