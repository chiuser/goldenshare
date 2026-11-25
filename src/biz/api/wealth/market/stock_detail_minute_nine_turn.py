from __future__ import annotations

# Query/Depends are declarative FastAPI defaults.
# ruff: noqa: B008
from collections.abc import Awaitable, Callable
from time import monotonic

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.api.wealth.market.nine_turn_query_params import (
    parse_cursor, parse_date, parse_debug, parse_limit, parse_nine_turn_ts_code, parse_stock_nine_turn_freq,
    validate_query_shape,
)
from src.biz.api.wealth.market.stock_detail_minutes import is_stock_minute_source_contract_error
from src.biz.queries.wealth.market.stock_nine_turn.stock_nine_turn_query_service import StockNineTurnNotFoundError
from src.biz.schemas.wealth.market.nine_turn import NineTurnSeriesDto
from src.foundation.clients.local_lake.stock_mins_reader import MinuteReadRequest, MinuteRequestError
from src.foundation.clients.local_lake.stock_nine_turn_contract import MAX_NINE_TURN_LIMIT


_ALLOWED_QUERY_PARAMS = {"tsCode", "freq", "startDate", "endDate", "limit", "cursor", "debug"}


def build_router(*, run_page: Callable[..., Awaitable[Response]]) -> APIRouter:
    router = APIRouter(prefix="/wealth/market/stock-detail", tags=["wealth-market"])

    @router.get("/minute-nine-turn", response_model=NineTurnSeriesDto)
    async def get_stock_minute_nine_turn(
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
    ) -> Response:
        arrived_at = monotonic()
        try:
            validate_query_shape(request, allowed=_ALLOWED_QUERY_PARAMS)
            return await run_page(
                request, output="nine_turn", arrived_at=arrived_at, session=session, debug=parse_debug(debug),
                query=MinuteReadRequest(
                    ts_code=parse_nine_turn_ts_code(ts_code), freq=parse_stock_nine_turn_freq(freq),
                    start_date=parse_date(start_date, field_name="startDate"),
                    end_date=parse_date(end_date, field_name="endDate"),
                    limit=parse_limit(limit, default=500, maximum=MAX_NINE_TURN_LIMIT), cursor=parse_cursor(cursor),
                ),
            )
        except WebAppError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc

    return router


def _http_error(exc: Exception) -> WebAppError:
    if isinstance(exc, StockNineTurnNotFoundError):
        return WebAppError(status_code=404, code="NT_NOT_FOUND", message=str(exc))
    if isinstance(exc, (MinuteRequestError, ValueError)):
        return WebAppError(status_code=400, code="NT_REQUEST_INVALID", message=str(exc))
    if is_stock_minute_source_contract_error(exc):
        return WebAppError(
            status_code=500, code="NT_SOURCE_CONTRACT_INVALID", message="股票分钟九转源数据合同校验失败。",
        )
    return WebAppError(status_code=500, code="NT_QUERY_FAILED", message="股票分钟九转查询失败。")
