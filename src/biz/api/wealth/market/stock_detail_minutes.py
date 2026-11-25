from __future__ import annotations

# FastAPI declares validation and authorization in the route signatures.
# ruff: noqa: B008
from collections.abc import Awaitable, Callable
from datetime import date
from time import monotonic

from fastapi import APIRouter, Depends, Query, Request, Response
from goldenshare_technical_indicators.errors import SourceContractError, SourceReadError, TechnicalIndicatorError

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.stock_nine_turn.stock_nine_turn_query_service import StockNineTurnSourceContractError
from src.biz.schemas.wealth.market.stock_detail_minutes import (
    StockMinuteChartResponseDto,
    StockMinuteIndicatorsResponseDto,
)
from src.foundation.clients.local_lake.stock_mins_reader import MAX_MINUTE_LIMIT, MinuteReadRequest, MinuteRequestError


def build_router(*, run_page: Callable[..., Awaitable[Response]]) -> APIRouter:
    router = APIRouter(prefix="/wealth/market/stock-detail", tags=["wealth-market"])

    @router.get("/minutes", response_model=StockMinuteChartResponseDto)
    async def get_stock_minute_bars(
        request: Request,
        ts_code: str = Query(alias="tsCode"),
        freq: int = Query(),
        start_date: date | None = Query(default=None, alias="startDate"),
        end_date: date | None = Query(default=None, alias="endDate"),
        limit: int = Query(default=500, ge=1, le=MAX_MINUTE_LIMIT),
        cursor: str | None = Query(default=None),
        debug: int = Query(default=0, ge=0, le=1),
        _user: AuthenticatedUser | None = Depends(require_quote_access),
    ) -> Response:
        try:
            return await run_page(
                request, output="chart", arrived_at=monotonic(), debug=bool(debug),
                query=MinuteReadRequest(ts_code, freq, start_date, end_date, limit, cursor),
            )
        except (MinuteRequestError, StockNineTurnSourceContractError, TechnicalIndicatorError) as exc:
            raise _http_error(exc) from exc

    @router.get("/minute-indicators", response_model=StockMinuteIndicatorsResponseDto)
    async def get_stock_minute_indicators(
        request: Request,
        ts_code: str = Query(alias="tsCode"),
        freq: int = Query(),
        start_date: date | None = Query(default=None, alias="startDate"),
        end_date: date | None = Query(default=None, alias="endDate"),
        limit: int = Query(default=500, ge=1, le=MAX_MINUTE_LIMIT),
        cursor: str | None = Query(default=None),
        debug: int = Query(default=0, ge=0, le=1),
        _user: AuthenticatedUser | None = Depends(require_quote_access),
    ) -> Response:
        try:
            return await run_page(
                request, output="indicators", arrived_at=monotonic(), debug=bool(debug),
                query=MinuteReadRequest(ts_code, freq, start_date, end_date, limit, cursor),
            )
        except (MinuteRequestError, TechnicalIndicatorError) as exc:
            raise _http_error(exc) from exc

    return router


def is_stock_minute_source_contract_error(exc: Exception) -> bool:
    if isinstance(exc, (SourceContractError, StockNineTurnSourceContractError)):
        return True
    if isinstance(exc, SourceReadError):
        from duckdb import BinderException, ConversionException

        return isinstance(exc.__cause__, (BinderException, ConversionException))
    return False


def _http_error(exc: Exception) -> WebAppError:
    if isinstance(exc, MinuteRequestError):
        return WebAppError(status_code=400, code=exc.code, message=str(exc))
    if is_stock_minute_source_contract_error(exc):
        return WebAppError(status_code=503, code="SM_SOURCE_CONTRACT_INVALID", message="分钟源数据合同校验失败。")
    return WebAppError(status_code=503, code="SM_QUERY_FAILED", message="分钟数据查询失败。")
