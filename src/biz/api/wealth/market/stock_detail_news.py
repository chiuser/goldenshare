from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.stock_detail.news_query import StockDetailNewsQuery
from src.biz.queries.wealth.market.stock_detail.stock_detail_query_service import StockDetailNotFoundError
from src.biz.schemas.wealth.market.stock_detail_news import StockDetailNewsResponseDto


router = APIRouter(prefix="/wealth/market/stock-detail", tags=["wealth-market"])


@router.get(
    "/news",
    response_model=StockDetailNewsResponseDto,
    response_model_exclude_none=True,
)
def get_stock_detail_news(
    ts_code: str = Query(alias="tsCode"),
    start_at: datetime | None = Query(default=None, alias="startAt"),
    end_at: datetime | None = Query(default=None, alias="endAt"),
    limit: int = Query(default=50, ge=1),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> StockDetailNewsResponseDto:
    if start_at is not None and start_at.tzinfo is None:
        raise WebAppError(status_code=400, code="400001", message="startAt 必须包含时区偏移")
    if end_at is not None and end_at.tzinfo is None:
        raise WebAppError(status_code=400, code="400001", message="endAt 必须包含时区偏移")
    try:
        return StockDetailNewsQuery().build(
            session,
            ts_code=ts_code,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            debug=bool(debug),
        )
    except StockDetailNotFoundError as exc:
        raise WebAppError(status_code=404, code="404001", message=str(exc)) from exc
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc
