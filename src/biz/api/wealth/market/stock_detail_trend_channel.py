from __future__ import annotations

# FastAPI Query/Depends declarations are intentionally used in signatures.
# ruff: noqa: B008
from datetime import date
import re

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.stock_detail_trend_channel.stock_detail_trend_channel_query_service import (
    StockDetailTrendChannelQueryService,
    StockTrendChannelNotFoundError,
)
from src.biz.schemas.wealth.market.stock_detail_trend_channel import (
    StockTrendChannelResponseDto,
)
from src.foundation.clients.local_lake.stock_daily_trend_channel_reader import (
    StockDailyTrendChannelReadError,
    StockDailyTrendChannelRequestError,
    StockDailyTrendChannelSourceNotReadyError,
)
from src.foundation.config.settings import get_settings
from src.foundation.config.stock_daily_trend_channel_capability import (
    resolve_stock_daily_trend_channel_capability,
)


router = APIRouter(prefix="/wealth/market/stock-detail", tags=["wealth-market"])
_ALLOWED_QUERY_PARAMS = {"tsCode", "endDate", "limit"}
_ISO_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


@router.get("/trend-channel", response_model=StockTrendChannelResponseDto)
def get_stock_daily_trend_channel(
    request: Request,
    ts_code: str | None = Query(default=None, alias="tsCode"),
    end_date: str | None = Query(default=None, alias="endDate"),
    limit: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> StockTrendChannelResponseDto:
    service: StockDetailTrendChannelQueryService | None = None
    try:
        _validate_query_shape(request)
        capability = resolve_stock_daily_trend_channel_capability(get_settings())
        if not capability.enabled or capability.lake_root is None:
            raise StockDailyTrendChannelSourceNotReadyError(
                "本地股票趋势通道能力尚未就绪。"
            )
        service = StockDetailTrendChannelQueryService(capability.lake_root)
        return service.read(
            session,
            ts_code=_parse_ts_code(ts_code),
            end_date=_parse_date(end_date),
            limit=_parse_limit(limit),
        )
    except Exception as exc:  # noqa: BLE001
        _raise_http_error(exc)
        raise AssertionError("unreachable")
    finally:
        if service is not None:
            service.close()


def _validate_query_shape(request: Request) -> None:
    supplied = [key for key, _value in request.query_params.multi_items()]
    unknown = sorted(set(supplied) - _ALLOWED_QUERY_PARAMS)
    if unknown:
        raise ValueError(f"不支持的查询参数：{', '.join(unknown)}")
    duplicated = sorted(key for key in set(supplied) if supplied.count(key) > 1)
    if duplicated:
        raise ValueError(f"查询参数不能重复：{', '.join(duplicated)}")


def _parse_ts_code(raw_value: str | None) -> str:
    value = "" if raw_value is None else raw_value.strip().upper()
    if not re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", value):
        raise ValueError("tsCode 必须是六位代码加 SH/SZ/BJ 后缀。")
    return value


def _parse_date(raw_value: str | None) -> date | None:
    if raw_value is None:
        return None
    if not _ISO_DATE_PATTERN.fullmatch(raw_value):
        raise ValueError("endDate 必须是 YYYY-MM-DD。")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError("endDate 不是有效日期。") from exc


def _parse_limit(raw_value: str | None) -> int:
    value = "300" if raw_value is None else raw_value
    if not value.isdigit():
        raise ValueError("limit 必须是整数。")
    limit = int(value)
    if not 1 <= limit <= 2_000:
        raise ValueError("limit 必须在 1 到 2000 之间。")
    return limit


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, WebAppError):
        raise exc
    if isinstance(exc, StockTrendChannelNotFoundError):
        raise WebAppError(
            status_code=404,
            code="STOCK_NOT_FOUND",
            message=str(exc),
        ) from exc
    if isinstance(exc, (StockDailyTrendChannelRequestError, ValueError)):
        raise WebAppError(
            status_code=400,
            code="INVALID_ARGUMENT",
            message=str(exc),
        ) from exc
    if isinstance(exc, StockDailyTrendChannelSourceNotReadyError):
        raise WebAppError(
            status_code=503,
            code="STOCK_TREND_CHANNEL_SOURCE_NOT_READY",
            message="股票趋势通道正式数据尚未准备完成。",
        ) from exc
    if isinstance(exc, StockDailyTrendChannelReadError):
        raise WebAppError(
            status_code=500,
            code="STOCK_TREND_CHANNEL_READ_FAILED",
            message="股票趋势通道读取失败。",
        ) from exc
    raise WebAppError(
        status_code=500,
        code="STOCK_TREND_CHANNEL_READ_FAILED",
        message="股票趋势通道读取失败。",
    ) from exc
