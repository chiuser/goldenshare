from __future__ import annotations

# FastAPI dependency declarations intentionally use Query/Depends in signatures.
# ruff: noqa: B008
from datetime import date
import re

from fastapi import APIRouter, Depends, Query, Request

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.index_detail_minutes.index_detail_minutes_query_service import (
    IndexDetailMinutesQueryService,
)
from src.biz.schemas.wealth.market.index_detail_minutes import (
    IndexMinuteIndicatorsResponseDto,
    IndexMinutesResponseDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
    IndexDetailQueryError,
    IndexDetailRequestError,
    IndexDetailUniverseService,
)
from src.foundation.clients.local_lake.major_index_mins_reader import (
    IndexMinuteQueryError,
    IndexMinuteRequestError,
    IndexMinuteSourceContractError,
)
from src.foundation.config.local_minute_capability import (
    LocalMinuteCapabilityError,
    resolve_index_minute_capability,
)
from src.foundation.config.settings import get_settings


router = APIRouter(prefix="/wealth/market/index-detail", tags=["wealth-market"])
_ISO_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_ALLOWED_QUERY_PARAMS = {"tsCode", "freq", "startDate", "endDate", "limit", "cursor"}


def _service() -> IndexDetailMinutesQueryService:
    capability = resolve_index_minute_capability(get_settings())
    if not capability.enabled or capability.lake_root is None:
        raise WebAppError(
            status_code=503,
            code=capability.reason_code or "SM_LOCAL_LAKE_NOT_CONFIGURED",
            message="本地指数分钟数据能力未启用。",
        )
    return IndexDetailMinutesQueryService(capability.lake_root)


@router.get("/minutes", response_model=IndexMinutesResponseDto)
def get_index_minute_bars(
    request: Request,
    ts_code: str | None = Query(default=None, alias="tsCode"),
    freq: str | None = Query(default=None),
    start_date: str | None = Query(default=None, alias="startDate"),
    end_date: str | None = Query(default=None, alias="endDate"),
    limit: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
) -> IndexMinutesResponseDto:
    try:
        _validate_query_shape(request)
        normalized_code = _normalize_supported_code(ts_code)
        return _service().read_bars(
            ts_code=normalized_code,
            freq=_parse_freq(freq),
            start_date=_parse_date(start_date, field_name="startDate"),
            end_date=_parse_date(end_date, field_name="endDate"),
            limit=_parse_limit(limit),
            cursor=_parse_cursor(cursor),
        )
    except Exception as exc:  # noqa: BLE001
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.get("/minute-indicators", response_model=IndexMinuteIndicatorsResponseDto)
def get_index_minute_indicators(
    request: Request,
    ts_code: str | None = Query(default=None, alias="tsCode"),
    freq: str | None = Query(default=None),
    start_date: str | None = Query(default=None, alias="startDate"),
    end_date: str | None = Query(default=None, alias="endDate"),
    limit: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
) -> IndexMinuteIndicatorsResponseDto:
    try:
        _validate_query_shape(request)
        normalized_code = _normalize_supported_code(ts_code)
        return _service().read_indicators(
            ts_code=normalized_code,
            freq=_parse_freq(freq),
            start_date=_parse_date(start_date, field_name="startDate"),
            end_date=_parse_date(end_date, field_name="endDate"),
            limit=_parse_limit(limit),
            cursor=_parse_cursor(cursor),
        )
    except Exception as exc:  # noqa: BLE001
        _raise_http_error(exc)
        raise AssertionError("unreachable")


def _validate_query_shape(request: Request) -> None:
    supplied = [key for key, _value in request.query_params.multi_items()]
    unknown = sorted(set(supplied) - _ALLOWED_QUERY_PARAMS)
    if unknown:
        raise IndexDetailRequestError(f"不支持的查询参数：{', '.join(unknown)}")
    duplicated = sorted(key for key in set(supplied) if supplied.count(key) > 1)
    if duplicated:
        raise IndexDetailRequestError(f"查询参数不能重复：{', '.join(duplicated)}")


def _normalize_supported_code(raw_value: str | None) -> str:
    normalized = IndexDetailUniverseService.normalize_ts_code(raw_value)
    IndexDetailUniverseService().require_supported(normalized)
    return normalized


def _parse_freq(raw_value: str | None) -> int:
    value = "" if raw_value is None else raw_value
    if not value.isdigit():
        raise IndexDetailRequestError("freq 必须是整数分钟频率")
    normalized = int(value)
    if normalized not in {1, 5, 15, 30, 60, 90, 120}:
        raise IndexDetailRequestError("freq 只允许 1/5/15/30/60/90/120")
    return normalized


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
    value = "500" if raw_value is None else raw_value
    if not value.isdigit():
        raise IndexDetailRequestError("limit 必须是整数")
    normalized = int(value)
    if not 1 <= normalized <= 10_000:
        raise IndexDetailRequestError("limit 必须在 1 到 10000 之间")
    return normalized


def _parse_cursor(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    if not raw_value.strip():
        raise IndexDetailRequestError("cursor 不能为空")
    return raw_value


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, WebAppError):
        raise exc
    if isinstance(exc, (IndexDetailRequestError, IndexMinuteRequestError)):
        raise WebAppError(status_code=400, code="ID_REQUEST_INVALID", message=str(exc)) from exc
    if isinstance(exc, IndexDetailNotFoundError):
        raise WebAppError(status_code=404, code="ID_NOT_FOUND", message=str(exc)) from exc
    if isinstance(exc, IndexMinuteSourceContractError):
        raise WebAppError(
            status_code=500,
            code="IM_SOURCE_CONTRACT_INVALID",
            message="指数分钟源数据合同校验失败。",
        ) from exc
    if isinstance(exc, (IndexMinuteQueryError, IndexDetailQueryError)):
        raise WebAppError(
            status_code=500,
            code="IM_QUERY_FAILED",
            message="指数分钟数据查询失败。",
        ) from exc
    if isinstance(exc, LocalMinuteCapabilityError):
        raise WebAppError(status_code=503, code=exc.code, message=exc.message) from exc
    raise WebAppError(
        status_code=500,
        code="IM_QUERY_FAILED",
        message="指数分钟数据查询失败。",
    ) from exc
