from __future__ import annotations

# FastAPI dependency declarations intentionally use Query/Depends in signatures,
# matching the existing API modules in this repository.
# ruff: noqa: B008
from datetime import date

from fastapi import APIRouter, Depends, Query

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.stock_detail_minutes.stock_detail_minutes_query_service import (
    StockMinuteQueryService,
)
from src.biz.schemas.wealth.market.stock_detail_minutes import (
    StockMinuteIndicatorsResponseDto,
    StockMinutesResponseDto,
)
from src.foundation.clients.local_lake.stock_mins_reader import (
    MinuteQueryError,
    MinuteRequestError,
    MinuteSourceContractError,
)
from src.foundation.config.local_minute_capability import (
    resolve_local_minute_capability,
)
from src.foundation.config.settings import get_settings

router = APIRouter(prefix="/wealth/market/stock-detail", tags=["wealth-market"])


def _service() -> StockMinuteQueryService:
    capability = resolve_local_minute_capability(get_settings())
    if not capability.enabled or capability.lake_root is None:
        raise WebAppError(
            status_code=503,
            code="SM_LOCAL_LAKE_NOT_CONFIGURED",
            message="本地分钟数据能力未启用。",
        )
    return StockMinuteQueryService(capability.lake_root)


@router.get("/minutes", response_model=StockMinutesResponseDto)
def get_stock_minute_bars(
    ts_code: str = Query(alias="tsCode"),
    freq: int = Query(),
    start_date: date | None = Query(default=None, alias="startDate"),
    end_date: date | None = Query(default=None, alias="endDate"),
    limit: int = Query(default=500, ge=1, le=10_000),
    cursor: str | None = Query(default=None),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
) -> StockMinutesResponseDto:
    try:
        return _service().read_bars(
            ts_code=ts_code,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            cursor=cursor,
            debug=bool(debug),
        )
    except MinuteRequestError as exc:
        raise WebAppError(status_code=400, code=exc.code, message=str(exc)) from exc
    except MinuteSourceContractError as exc:
        raise WebAppError(status_code=503, code=exc.code, message="分钟源数据合同校验失败。") from exc
    except MinuteQueryError as exc:
        raise WebAppError(status_code=503, code=exc.code, message="分钟数据查询失败。") from exc


@router.get("/minute-indicators", response_model=StockMinuteIndicatorsResponseDto)
def get_stock_minute_indicators(
    ts_code: str = Query(alias="tsCode"),
    freq: int = Query(),
    start_date: date | None = Query(default=None, alias="startDate"),
    end_date: date | None = Query(default=None, alias="endDate"),
    limit: int = Query(default=500, ge=1, le=10_000),
    cursor: str | None = Query(default=None),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
) -> StockMinuteIndicatorsResponseDto:
    try:
        return _service().read_indicators(
            ts_code=ts_code,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            cursor=cursor,
            debug=bool(debug),
        )
    except MinuteRequestError as exc:
        raise WebAppError(status_code=400, code=exc.code, message=str(exc)) from exc
    except MinuteSourceContractError as exc:
        raise WebAppError(status_code=503, code=exc.code, message="分钟源数据合同校验失败。") from exc
    except MinuteQueryError as exc:
        raise WebAppError(status_code=503, code=exc.code, message="分钟数据查询失败。") from exc
