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
    parse_nine_turn_ts_code,
    validate_query_shape,
)
from src.biz.queries.wealth.market.index_nine_turn.index_nine_turn_query_service import (
    IndexNineTurnQueryError,
    IndexNineTurnQueryService,
    IndexNineTurnSourceContractError,
)
from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
    IndexDetailQueryError,
    IndexDetailRequestError,
)


router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])
_ALLOWED_QUERY_PARAMS = {
    "tsCode",
    "startDate",
    "endDate",
    "limit",
    "cursor",
    "debug",
}


@router.get("/nine-turn", response_model=NineTurnSeriesDto)
def get_index_daily_nine_turn(
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
        return IndexNineTurnQueryService().read_daily(
            session,
            ts_code=parse_nine_turn_ts_code(ts_code),
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
    if isinstance(exc, IndexDetailNotFoundError):
        raise WebAppError(
            status_code=404, code="NT_NOT_FOUND", message=str(exc)
        ) from exc
    if isinstance(exc, (IndexDetailRequestError, ValueError)):
        raise WebAppError(
            status_code=400,
            code="NT_REQUEST_INVALID",
            message=str(exc),
        ) from exc
    if isinstance(exc, IndexNineTurnSourceContractError):
        raise WebAppError(
            status_code=500,
            code="NT_SOURCE_CONTRACT_INVALID",
            message="指数日线九转源数据合同校验失败。",
        ) from exc
    if isinstance(exc, (IndexNineTurnQueryError, IndexDetailQueryError)):
        raise WebAppError(
            status_code=500,
            code="NT_QUERY_FAILED",
            message="指数日线九转查询失败。",
        ) from exc
    raise WebAppError(
        status_code=500,
        code="NT_QUERY_FAILED",
        message="指数日线九转查询失败。",
    ) from exc


__all__ = ["router"]
