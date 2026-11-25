from __future__ import annotations

# Query/Depends are declarative FastAPI defaults.
# ruff: noqa: B008
from collections.abc import Awaitable, Callable
from time import monotonic

from fastapi import APIRouter, Depends, Query, Request, Response

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.biz.api.wealth.market.nine_turn_query_params import (
    parse_cursor,
    parse_date,
    parse_debug,
    parse_index_nine_turn_freq,
    parse_limit,
    parse_nine_turn_ts_code,
    validate_query_shape,
)
from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
    IndexDetailRequestError,
)
from src.foundation.clients.local_lake.major_index_mins_reader import (
    IndexMinuteRequestError, IndexMinuteSourceContractError,
)
from src.foundation.config.local_minute_capability import LocalMinuteCapabilityError


_ALLOWED_QUERY_PARAMS = {
    "tsCode",
    "freq",
    "startDate",
    "endDate",
    "limit",
    "cursor",
    "debug",
}


def build_router(*, run_page: Callable[..., Awaitable[Response]]) -> APIRouter:
    router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])

    @router.get("/minute-nine-turn", response_model=NineTurnSeriesDto)
    async def get_index_minute_nine_turn(
        request: Request,
        ts_code: str | None = Query(default=None, alias="tsCode"),
        freq: str | None = Query(default=None),
        start_date: str | None = Query(default=None, alias="startDate"),
        end_date: str | None = Query(default=None, alias="endDate"),
        limit: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        debug: str | None = Query(default=None),
        _user: AuthenticatedUser | None = Depends(require_quote_access),
    ) -> Response:
        arrived_at = monotonic()
        try:
            validate_query_shape(request, allowed=_ALLOWED_QUERY_PARAMS)
            return await run_page(
                request, dataset="nine_turn", arrived_at=arrived_at,
                ts_code=parse_nine_turn_ts_code(ts_code),
                freq=parse_index_nine_turn_freq(freq),
                start_date=parse_date(start_date, field_name="startDate"),
                end_date=parse_date(end_date, field_name="endDate"),
                limit=parse_limit(limit, default=500, maximum=10_000),
                cursor=parse_cursor(cursor),
                debug=parse_debug(debug),
            )
        except Exception as exc:  # noqa: BLE001
            _raise_http_error(exc)
            raise AssertionError("unreachable")

    return router


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, WebAppError):
        raise exc
    if isinstance(exc, IndexDetailNotFoundError):
        raise WebAppError(
            status_code=404, code="NT_NOT_FOUND", message=str(exc)
        ) from exc
    if isinstance(
        exc, (IndexDetailRequestError, IndexMinuteRequestError, ValueError)
    ):
        raise WebAppError(
            status_code=400,
            code="NT_REQUEST_INVALID",
            message=str(exc),
        ) from exc
    if isinstance(exc, IndexMinuteSourceContractError):
        raise WebAppError(
            status_code=500,
            code="NT_SOURCE_CONTRACT_INVALID",
            message="指数分钟九转源数据合同校验失败。",
        ) from exc
    if isinstance(exc, LocalMinuteCapabilityError):
        raise WebAppError(status_code=503, code=exc.code, message=exc.message) from exc
    raise WebAppError(
        status_code=500,
        code="NT_QUERY_FAILED",
        message="指数分钟九转查询失败。",
    ) from exc


__all__ = ["build_router"]
