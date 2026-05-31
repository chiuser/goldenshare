from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.stock_detail.stock_detail_query_service import (
    StockDetailNotFoundError,
    StockDetailQueryService,
)
from src.biz.schemas.wealth.market.stock_detail import (
    StockDetailKlineResponseDto,
    StockDetailPageInitResponseDto,
)


router = APIRouter(prefix="/wealth/market/stock-detail", tags=["wealth-market"])


@router.get("/page-init", response_model=StockDetailPageInitResponseDto)
def get_stock_detail_page_init(
    ts_code: str = Query(alias="tsCode"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> StockDetailPageInitResponseDto:
    try:
        return StockDetailQueryService().build_page_init(
            session,
            ts_code=ts_code.strip().upper(),
            trade_date=trade_date,
            debug=bool(debug),
        )
    except StockDetailNotFoundError as exc:
        raise WebAppError(status_code=404, code="404001", message=str(exc)) from exc
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc


@router.get("/kline", response_model=StockDetailKlineResponseDto)
def get_stock_detail_kline(
    ts_code: str = Query(alias="tsCode"),
    period: str = Query(default="day"),
    adjustment: str = Query(default="forward"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    start_date: date | None = Query(default=None, alias="startDate"),
    end_date: date | None = Query(default=None, alias="endDate"),
    limit: int = Query(default=300),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> StockDetailKlineResponseDto:
    try:
        return StockDetailQueryService().build_kline(
            session,
            ts_code=ts_code.strip().upper(),
            period=period,
            adjustment=adjustment,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            debug=bool(debug),
        )
    except StockDetailNotFoundError as exc:
        raise WebAppError(status_code=404, code="404001", message=str(exc)) from exc
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc
