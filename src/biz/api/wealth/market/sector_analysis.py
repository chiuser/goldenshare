from __future__ import annotations

from datetime import date
import re
from typing import Literal, cast

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyUnavailableError,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_query_service import (
    SectorMomentumQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_member_detail_query_service import (
    SectorMemberDetailQueryService,
)
from src.biz.schemas.wealth.market.sector_analysis import (
    SectorAnalysisMetaResponseDto,
    SectorMemberDetailResponseDto,
    SectorMomentumHistoryResponseDto,
    SectorMomentumRankingsResponseDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_detail_contract import (
    SectorMemberDetailRequest,
    SectorMemberFactMismatchError,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDataQueryError,
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
    parse_direction,
    parse_history_range,
    parse_period,
    parse_scope,
)
from src.foundation.config.settings import get_settings


router = APIRouter(prefix="/wealth/market/sector-analysis", tags=["wealth-market"])

_DEBUG_ENVIRONMENTS = frozenset({"local", "dev", "test"})
_ISO_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SECTOR_CODE_PATTERN = re.compile(r"^BK[0-9]{4}\.DC$")


@router.get("/meta", response_model=SectorAnalysisMetaResponseDto)
def get_sector_analysis_meta(
    request: Request,
    market: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> SectorAnalysisMetaResponseDto:
    try:
        _validate_query_shape(request, allowed={"market"})
        return SectorMomentumQueryService().build_meta(
            session,
            market=_parse_market(market),
        )
    except SectorScopeInvalidError as exc:
        _raise_request_error(exc)
    except SectorHierarchyUnavailableError as exc:
        raise WebAppError(
            status_code=500,
            code="SA_HIERARCHY_UNAVAILABLE",
            message="行业分类暂不可用，请稍后重试。",
        ) from exc
    except SectorDataQueryError as exc:
        raise WebAppError(
            status_code=500,
            code="SA_QUERY_FAILED",
            message="板块分析数据读取失败，请稍后重试。",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise WebAppError(
            status_code=500,
            code="SA_QUERY_FAILED",
            message="板块分析数据读取失败，请稍后重试。",
        ) from exc
    raise AssertionError("unreachable")


@router.get("/momentum/rankings", response_model=SectorMomentumRankingsResponseDto)
def get_sector_momentum_rankings(
    request: Request,
    market: str | None = Query(default=None),
    trade_date: str | None = Query(default=None, alias="tradeDate"),
    scope: str | None = Query(default=None),
    level1_code: str | None = Query(default=None, alias="level1Code"),
    level2_code: str | None = Query(default=None, alias="level2Code"),
    period: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    debug: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> SectorMomentumRankingsResponseDto:
    try:
        _validate_query_shape(
            request,
            allowed={
                "market",
                "tradeDate",
                "scope",
                "level1Code",
                "level2Code",
                "period",
                "direction",
                "debug",
            },
        )
        return SectorMomentumQueryService().build_rankings(
            session,
            market=_parse_market(market),
            trade_date=_parse_date(trade_date),
            scope=parse_scope(scope or "LEVEL_1"),
            level1_code=_parse_optional_sector_code(
                level1_code, field_name="level1Code"
            ),
            level2_code=_parse_optional_sector_code(
                level2_code, field_name="level2Code"
            ),
            period=parse_period(
                _parse_choice_int(period, default=1, field_name="period")
            ),
            direction=parse_direction(direction or "GAINERS"),
            debug=_parse_debug(debug),
        )
    except SectorSelectionInvalidError as exc:
        _raise_selection_error(exc)
    except SectorScopeInvalidError as exc:
        _raise_request_error(exc)
    raise AssertionError("unreachable")


@router.get("/momentum/history", response_model=SectorMomentumHistoryResponseDto)
def get_sector_momentum_history(
    request: Request,
    market: str | None = Query(default=None),
    trade_date: str | None = Query(default=None, alias="tradeDate"),
    scope: str | None = Query(default=None),
    level1_code: str | None = Query(default=None, alias="level1Code"),
    level2_code: str | None = Query(default=None, alias="level2Code"),
    period: str | None = Query(default=None),
    history_range: str | None = Query(default=None, alias="historyRange"),
    sector_code: str | None = Query(default=None, alias="sectorCode"),
    debug: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> SectorMomentumHistoryResponseDto:
    try:
        _validate_query_shape(
            request,
            allowed={
                "market",
                "tradeDate",
                "scope",
                "level1Code",
                "level2Code",
                "period",
                "historyRange",
                "sectorCode",
                "debug",
            },
        )
        return SectorMomentumQueryService().build_history(
            session,
            market=_parse_market(market),
            trade_date=_parse_date(trade_date),
            scope=parse_scope(scope or "LEVEL_1"),
            level1_code=_parse_optional_sector_code(
                level1_code, field_name="level1Code"
            ),
            level2_code=_parse_optional_sector_code(
                level2_code, field_name="level2Code"
            ),
            period=parse_period(
                _parse_choice_int(period, default=1, field_name="period")
            ),
            history_range=parse_history_range(
                _parse_choice_int(history_range, default=20, field_name="historyRange")
            ),
            sector_code=_parse_required_sector_code(
                sector_code, field_name="sectorCode"
            ),
            debug=_parse_debug(debug),
        )
    except SectorSelectionInvalidError as exc:
        _raise_selection_error(exc)
    except SectorScopeInvalidError as exc:
        _raise_request_error(exc)
    raise AssertionError("unreachable")


@router.get("/momentum/members", response_model=SectorMemberDetailResponseDto)
def get_sector_momentum_members(
    request: Request,
    market: str | None = Query(default=None),
    trade_date: str | None = Query(default=None, alias="tradeDate"),
    hierarchy_version: str | None = Query(default=None, alias="hierarchyVersion"),
    sector_code: str | None = Query(default=None, alias="sectorCode"),
    period: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> SectorMemberDetailResponseDto:
    try:
        _validate_query_shape(
            request,
            allowed={
                "market",
                "tradeDate",
                "hierarchyVersion",
                "sectorCode",
                "period",
                "direction",
            },
        )
        parsed_date = _parse_date(trade_date)
        if parsed_date is None:
            raise SectorScopeInvalidError("tradeDate 为必填参数")
        if period is None:
            raise SectorScopeInvalidError("period 为必填参数")
        if direction is None:
            raise SectorScopeInvalidError("direction 为必填参数")
        return SectorMemberDetailQueryService().build_members(
            session,
            request=SectorMemberDetailRequest(
                market=_parse_required_market(market),
                trade_date=parsed_date,
                hierarchy_version=_parse_required_text(
                    hierarchy_version,
                    field_name="hierarchyVersion",
                    max_length=128,
                ),
                sector_code=_parse_required_sector_code(
                    sector_code,
                    field_name="sectorCode",
                ),
                period=parse_period(
                    _parse_choice_int(period, default=0, field_name="period")
                ),
                direction=parse_direction(direction),
            ),
        )
    except SectorMemberFactMismatchError as exc:
        raise WebAppError(
            status_code=409,
            code="SA_MEMBER_FACT_MISMATCH",
            message="行业分类已更新，正在重新加载当前数据。",
        ) from exc
    except SectorSelectionInvalidError as exc:
        _raise_selection_error(exc)
    except SectorScopeInvalidError as exc:
        _raise_request_error(exc)
    raise AssertionError("unreachable")


def _validate_query_shape(request: Request, *, allowed: set[str]) -> None:
    supplied = [key for key, _value in request.query_params.multi_items()]
    unknown = sorted(set(supplied) - allowed)
    if unknown:
        raise SectorScopeInvalidError(f"不支持的查询参数：{', '.join(unknown)}")
    duplicated = sorted(key for key in set(supplied) if supplied.count(key) > 1)
    if duplicated:
        raise SectorScopeInvalidError(f"查询参数不能重复：{', '.join(duplicated)}")


def _parse_market(raw_value: str | None) -> str:
    market = (raw_value or "CN_A").strip().upper()
    if market != "CN_A":
        raise SectorScopeInvalidError(f"不支持的市场：{raw_value}")
    return market


def _parse_required_market(raw_value: str | None) -> Literal["CN_A"]:
    if raw_value is None:
        raise SectorScopeInvalidError("market 为必填参数")
    market = _parse_market(raw_value)
    return cast(Literal["CN_A"], market)


def _parse_required_text(
    raw_value: str | None,
    *,
    field_name: str,
    max_length: int,
) -> str:
    value = (raw_value or "").strip()
    if not value or len(value) > max_length:
        raise SectorScopeInvalidError(f"{field_name} 必须是有效的非空字符串")
    return value


def _parse_date(raw_value: str | None) -> date | None:
    if raw_value is None:
        return None
    if not _ISO_DATE_PATTERN.fullmatch(raw_value):
        raise SectorScopeInvalidError("tradeDate 必须是 YYYY-MM-DD")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise SectorScopeInvalidError("tradeDate 不是有效日期") from exc


def _parse_choice_int(raw_value: str | None, *, default: int, field_name: str) -> int:
    value = str(default) if raw_value is None else raw_value
    if not value.isdigit():
        raise SectorScopeInvalidError(f"{field_name} 必须是整数")
    return int(value)


def _parse_optional_sector_code(
    raw_value: str | None, *, field_name: str
) -> str | None:
    if raw_value is None:
        return None
    return _parse_required_sector_code(raw_value, field_name=field_name)


def _parse_required_sector_code(raw_value: str | None, *, field_name: str) -> str:
    if raw_value is None or not _SECTOR_CODE_PATTERN.fullmatch(raw_value):
        raise SectorScopeInvalidError(f"{field_name} 必须使用 BKxxxx.DC 格式")
    return raw_value


def _parse_debug(raw_value: str | None) -> bool:
    value = raw_value or "0"
    if value not in {"0", "1"}:
        raise SectorScopeInvalidError("debug 只允许 0 或 1")
    return (
        value == "1" and get_settings().app_env.strip().lower() in _DEBUG_ENVIRONMENTS
    )


def _raise_request_error(exc: Exception) -> None:
    raise WebAppError(
        status_code=400, code="SA_SCOPE_INVALID", message=str(exc)
    ) from exc


def _raise_selection_error(exc: Exception) -> None:
    raise WebAppError(
        status_code=400, code="SA_SELECTION_INVALID", message=str(exc)
    ) from exc
