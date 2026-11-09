from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from functools import partial
import re
from time import monotonic

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.index_detail.index_detail_kline_query_service import (
    IndexDetailKlineQueryService,
)
from src.biz.queries.wealth.market.index_detail.index_detail_page_query_service import (
    IndexDetailPageQueryService,
)
from src.biz.queries.wealth.market.index_detail.index_detail_weights_query_service import (
    IndexDetailWeightsQueryService,
)
from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailKlineResponseDto,
    IndexDetailPageInitResponseDto,
    IndexDetailWeightsResponseDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
    IndexDetailQueryError,
    IndexDetailRequestError,
    IndexDetailUniverseService,
)
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader

_ISO_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _validate_query_shape(request: Request, *, allowed: set[str]) -> None:
    supplied = [key for key, _value in request.query_params.multi_items()]
    unknown = sorted(set(supplied) - allowed)
    if unknown:
        raise IndexDetailRequestError(f"不支持的查询参数：{', '.join(unknown)}")
    duplicated = sorted(key for key in set(supplied) if supplied.count(key) > 1)
    if duplicated:
        raise IndexDetailRequestError(f"查询参数不能重复：{', '.join(duplicated)}")


def _parse_date(raw_value: str | None, *, field_name: str) -> date | None:
    if raw_value is None:
        return None
    if not _ISO_DATE_PATTERN.fullmatch(raw_value):
        raise IndexDetailRequestError(f"{field_name} 必须是 YYYY-MM-DD")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise IndexDetailRequestError(f"{field_name} 不是有效日期") from exc


def _parse_limit(raw_value: str | None) -> int:
    value = "300" if raw_value is None else raw_value
    if not value.isdigit():
        raise IndexDetailRequestError("limit 必须是整数")
    limit = int(value)
    if limit < 1 or limit > 2000:
        raise IndexDetailRequestError("limit 必须在 1 到 2000 之间")
    return limit


def _normalize_ts_code(raw_value: str | None) -> str:
    return IndexDetailUniverseService.normalize_ts_code(raw_value)


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, IndexDetailRequestError):
        raise WebAppError(status_code=400, code="ID_REQUEST_INVALID", message=str(exc)) from exc
    if isinstance(exc, IndexDetailNotFoundError):
        raise WebAppError(status_code=404, code="ID_NOT_FOUND", message=str(exc)) from exc
    if isinstance(exc, IndexDetailQueryError):
        raise WebAppError(status_code=500, code="ID_QUERY_FAILED", message=str(exc)) from exc
    raise WebAppError(status_code=500, code="ID_QUERY_FAILED", message="指数详情查询失败") from exc


def get_index_detail_page_init(
    request: Request,
    ts_code: str | None = Query(default=None, alias="tsCode"),
    trade_date: str | None = Query(default=None, alias="tradeDate"),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> IndexDetailPageInitResponseDto:
    try:
        _validate_query_shape(request, allowed={"tsCode", "tradeDate"})
        return IndexDetailPageQueryService().build_page_init(
            session,
            ts_code=_normalize_ts_code(ts_code),
            trade_date=_parse_date(trade_date, field_name="tradeDate"),
        )
    except Exception as exc:  # noqa: BLE001
        _raise_http_error(exc)
        raise AssertionError("unreachable")


def get_index_detail_weights(
    request: Request,
    ts_code: str | None = Query(default=None, alias="tsCode"),
    trade_date: str | None = Query(default=None, alias="tradeDate"),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> IndexDetailWeightsResponseDto:
    try:
        _validate_query_shape(request, allowed={"tsCode", "tradeDate"})
        return IndexDetailWeightsQueryService().build_weights(
            session,
            ts_code=_normalize_ts_code(ts_code),
            trade_date=_parse_date(trade_date, field_name="tradeDate"),
        )
    except Exception as exc:  # noqa: BLE001
        _raise_http_error(exc)
        raise AssertionError("unreachable")


def build_router(
    *, daily_lake: IndexDailyLakeReader | None = None,
    run_sse_kline: Callable[..., Awaitable[bytes]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])
    router.add_api_route(
        "/page-init", get_index_detail_page_init, methods=["GET"],
        response_model=IndexDetailPageInitResponseDto,
    )

    @router.get("/kline", response_model=IndexDetailKlineResponseDto)
    async def get_index_detail_kline(
        request: Request,
        ts_code: str | None = Query(default=None, alias="tsCode"),
        period: str | None = Query(default=None),
        start_date: str | None = Query(default=None, alias="startDate"),
        end_date: str | None = Query(default=None, alias="endDate"),
        limit: str | None = Query(default=None),
        _user: AuthenticatedUser | None = Depends(require_quote_access),
        session: Session = Depends(get_db_session),
    ) -> IndexDetailKlineResponseDto | Response:
        return await query_kline_response(
            request, session, ts_code=ts_code, period=period, start_date=start_date, end_date=end_date,
            limit=limit, daily_lake=daily_lake, run_sse_kline=run_sse_kline,
        )

    router.add_api_route(
        "/weights", get_index_detail_weights, methods=["GET"],
        response_model=IndexDetailWeightsResponseDto,
    )
    return router


async def query_kline_response(
    request: Request, session: Session, *, ts_code: str | None, period: str | None,
    start_date: str | None, end_date: str | None, limit: str | None,
    daily_lake: IndexDailyLakeReader | None, run_sse_kline: Callable[..., Awaitable[bytes]] | None,
    project=None,
):
    arrived_at = monotonic()
    try:
        _validate_query_shape(request, allowed={"tsCode", "period", "startDate", "endDate", "limit"})
        params = dict(
            ts_code=_normalize_ts_code(ts_code), period="day" if period is None else period,
            start_date=_parse_date(start_date, field_name="startDate"),
            end_date=_parse_date(end_date, field_name="endDate"), limit=_parse_limit(limit),
        )
        if params["ts_code"] == "000001.SH" and params["period"] == "day" and params["limit"] <= 500:
            start, end = params["start_date"], params["end_date"]
            if start is not None and end is not None and start > end:
                raise IndexDetailRequestError("startDate 不能晚于 endDate")
            if run_sse_kline is None:
                raise IndexDetailQueryError("000001.SH 日线指标运行环境未装配")
            body = await run_sse_kline(request, arrived_at=arrived_at, project=project, **params)
            return Response(content=body, media_type="application/json")
        service = IndexDetailKlineQueryService(daily_lake=daily_lake)
        if project is None:
            return await run_in_threadpool(partial(service.build_kline, session, **params))
        def build():
            return project(*service.query_kline(session, **params))

        return await run_in_threadpool(build)
    except Exception as exc:  # noqa: BLE001
        _raise_http_error(exc)
        raise AssertionError("unreachable")
