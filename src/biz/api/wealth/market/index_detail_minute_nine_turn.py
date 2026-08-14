from __future__ import annotations

# Query/Depends are declarative FastAPI defaults.
# ruff: noqa: B008
from functools import lru_cache
from pathlib import Path

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
    parse_index_nine_turn_freq,
    parse_limit,
    parse_nine_turn_ts_code,
    validate_query_shape,
)
from src.biz.queries.wealth.market.index_minute_nine_turn.index_minute_nine_turn_query_service import (
    IndexMinuteNineTurnQueryService,
)
from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
    IndexDetailQueryError,
    IndexDetailRequestError,
)
from src.foundation.clients.local_lake.index_nine_turn_reader import (
    IndexNineTurnLakeReader,
    IndexNineTurnQueryError,
    IndexNineTurnRequestError,
    IndexNineTurnSourceContractError,
)
from src.foundation.config.local_minute_capability import (
    LocalMinuteCapabilityError,
    resolve_index_nine_turn_minute_capability,
)
from src.foundation.config.settings import get_settings


router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])
_ALLOWED_QUERY_PARAMS = {
    "tsCode",
    "freq",
    "startDate",
    "endDate",
    "limit",
    "cursor",
    "debug",
}


def _service() -> IndexMinuteNineTurnQueryService:
    capability = resolve_index_nine_turn_minute_capability(get_settings())
    if not capability.enabled or capability.lake_root is None:
        raise WebAppError(
            status_code=503,
            code=capability.reason_code or "SM_LOCAL_LAKE_NOT_CONFIGURED",
            message="本地指数分钟九转能力未启用。",
        )
    return IndexMinuteNineTurnQueryService(
        capability.lake_root,
        reader=_reader_for_lake_root(capability.lake_root),
    )


@lru_cache(maxsize=1)
def _reader_for_lake_root(lake_root: Path) -> IndexNineTurnLakeReader:
    return IndexNineTurnLakeReader(lake_root)


@router.get("/minute-nine-turn", response_model=NineTurnSeriesDto)
def get_index_minute_nine_turn(
    request: Request,
    ts_code: str | None = Query(default=None, alias="tsCode"),
    freq: str | None = Query(default=None),
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
        return _service().read(
            session,
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


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, WebAppError):
        raise exc
    if isinstance(exc, IndexDetailNotFoundError):
        raise WebAppError(
            status_code=404, code="NT_NOT_FOUND", message=str(exc)
        ) from exc
    if isinstance(
        exc, (IndexDetailRequestError, IndexNineTurnRequestError, ValueError)
    ):
        raise WebAppError(
            status_code=400,
            code="NT_REQUEST_INVALID",
            message=str(exc),
        ) from exc
    if isinstance(exc, IndexNineTurnSourceContractError):
        raise WebAppError(
            status_code=500,
            code="NT_SOURCE_CONTRACT_INVALID",
            message="指数分钟九转源数据合同校验失败。",
        ) from exc
    if isinstance(exc, (IndexNineTurnQueryError, IndexDetailQueryError)):
        raise WebAppError(
            status_code=500,
            code="NT_QUERY_FAILED",
            message="指数分钟九转查询失败。",
        ) from exc
    if isinstance(exc, LocalMinuteCapabilityError):
        raise WebAppError(status_code=503, code=exc.code, message=exc.message) from exc
    raise WebAppError(
        status_code=500,
        code="NT_QUERY_FAILED",
        message="指数分钟九转查询失败。",
    ) from exc


__all__ = ["router"]
