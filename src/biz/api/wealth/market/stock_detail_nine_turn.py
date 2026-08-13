from __future__ import annotations

# Query/Depends are declarative FastAPI defaults.
# ruff: noqa: B008
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.api.wealth.market.nine_turn_query_params import (
    parse_cursor,
    parse_date,
    parse_debug,
    parse_limit,
    parse_stock_code,
    validate_query_shape,
)
from src.biz.queries.wealth.market.stock_nine_turn.stock_nine_turn_query_service import (
    StockNineTurnNotFoundError,
    StockNineTurnQueryError,
    StockNineTurnQueryService,
    StockNineTurnRequestError,
    StockNineTurnSourceContractError,
)
from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto


router = APIRouter(prefix="/wealth/market/stock-detail", tags=["wealth-market"])
_ALLOWED_QUERY_PARAMS = {
    "tsCode",
    "startDate",
    "endDate",
    "limit",
    "cursor",
    "debug",
}


@router.get("/nine-turn", response_model=NineTurnSeriesDto)
def get_stock_daily_nine_turn(
    request: Request,
    ts_code: str | None = Query(default=None, alias="tsCode"),
    start_date: str | None = Query(default=None, alias="startDate"),
    end_date: str | None = Query(default=None, alias="endDate"),
    limit: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    debug: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> NineTurnSeriesDto:
    try:
        validate_query_shape(request, allowed=_ALLOWED_QUERY_PARAMS)
        return StockNineTurnQueryService().read_daily(
            session,
            ts_code=parse_stock_code(ts_code),
            start_date=parse_date(start_date, field_name="startDate"),
            end_date=parse_date(end_date, field_name="endDate"),
            limit=parse_limit(limit, default=300, maximum=2_000),
            cursor=parse_cursor(cursor),
            debug=parse_debug(debug),
        )
    except Exception as exc:  # noqa: BLE001
        _raise_http_error(exc)
        raise AssertionError("unreachable")


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, WebAppError):
        raise exc
    if isinstance(exc, StockNineTurnNotFoundError):
        raise WebAppError(
            status_code=404,
            code="NT_NOT_FOUND",
            message=str(exc),
        ) from exc
    if isinstance(exc, (StockNineTurnRequestError, ValueError)):
        raise WebAppError(
            status_code=400,
            code="NT_REQUEST_INVALID",
            message=str(exc),
        ) from exc
    if isinstance(exc, StockNineTurnSourceContractError):
        raise WebAppError(
            status_code=500,
            code="NT_SOURCE_CONTRACT_INVALID",
            message="股票日线九转源数据合同校验失败。",
        ) from exc
    if isinstance(exc, StockNineTurnQueryError):
        raise WebAppError(
            status_code=500,
            code="NT_QUERY_FAILED",
            message="股票日线九转查询失败。",
        ) from exc
    raise WebAppError(
        status_code=500,
        code="NT_QUERY_FAILED",
        message="股票日线九转查询失败。",
    ) from exc
