from __future__ import annotations

from datetime import date
import re

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.biz.queries.wealth.market.sector_overview.sector_overview_query_service import (
    MarketSectorOverviewQueryService,
)
from src.biz.schemas.wealth.market.sector_overview import SectorOverviewResponseDto


router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])

_ALLOWED_QUERY_PARAMS = {
    "market",
    "tradeDate",
    "view",
    "industryRankMetric",
    "selectedIndustryCode",
    "conceptRankMetric",
    "selectedConceptCode",
    "regionRankMetric",
    "selectedRegionCode",
    "debug",
}
_RANK_PARAM_BY_VIEW = {
    "INDUSTRY": "industryRankMetric",
    "CONCEPT": "conceptRankMetric",
    "REGION": "regionRankMetric",
}
_SELECTION_PARAM_BY_VIEW = {
    "INDUSTRY": "selectedIndustryCode",
    "CONCEPT": "selectedConceptCode",
    "REGION": "selectedRegionCode",
}
_RANK_VALUES = {
    "INDUSTRY": {"CHANGE_PCT_UP", "CHANGE_PCT_DOWN", "MAIN_NET_INFLOW", "UP_COUNT"},
    "CONCEPT": {"HEAT_SCORE", "HEAT_DELTA_1D", "CHANGE_PCT", "MAIN_NET_INFLOW"},
    "REGION": {"CHANGE_PCT", "MAIN_NET_INFLOW", "UP_COUNT"},
}
_DEFAULT_RANK = {"INDUSTRY": "CHANGE_PCT_UP", "CONCEPT": "HEAT_SCORE", "REGION": "CHANGE_PCT"}
_SECTOR_CODE_PATTERN = re.compile(r"^BK[0-9]{4}(?:\.DC)?$")
_ISO_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _validate_query_shape(request: Request) -> None:
    supplied = [key for key, _value in request.query_params.multi_items()]
    unknown = sorted(set(supplied) - _ALLOWED_QUERY_PARAMS)
    if unknown:
        raise ValueError(f"不支持的查询参数：{', '.join(unknown)}")
    duplicated = sorted(key for key in set(supplied) if supplied.count(key) > 1)
    if duplicated:
        raise ValueError(f"查询参数不能重复：{', '.join(duplicated)}")


def _parse_date(raw_value: str | None) -> date | None:
    if raw_value is None:
        return None
    if not _ISO_DATE_PATTERN.fullmatch(raw_value):
        raise ValueError("tradeDate 必须是 YYYY-MM-DD")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError("tradeDate 不是有效日期") from exc


def _parse_debug(raw_value: str | None) -> bool:
    value = "0" if raw_value is None else raw_value
    if value not in {"0", "1"}:
        raise ValueError("debug 只允许 0 或 1")
    return value == "1"


def _normalize_sector_code(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    normalized = raw_value.strip().upper()
    if not _SECTOR_CODE_PATTERN.fullmatch(normalized):
        raise ValueError("板块代码格式必须为 BK0000 或 BK0000.DC")
    return normalized if normalized.endswith(".DC") else f"{normalized}.DC"


def _resolve_view_params(
    request: Request,
    *,
    view: str,
    industry_rank_metric: str | None,
    selected_industry_code: str | None,
    concept_rank_metric: str | None,
    selected_concept_code: str | None,
    region_rank_metric: str | None,
    selected_region_code: str | None,
) -> tuple[str, str | None]:
    if view not in _RANK_VALUES:
        raise ValueError(f"不支持的板块视图：{view}")
    supplied = set(request.query_params.keys())
    relevant = {_RANK_PARAM_BY_VIEW[view], _SELECTION_PARAM_BY_VIEW[view]}
    irrelevant = sorted(
        supplied.intersection(set(_RANK_PARAM_BY_VIEW.values()) | set(_SELECTION_PARAM_BY_VIEW.values())) - relevant
    )
    if irrelevant:
        raise ValueError(f"当前 {view} 视图不接受参数：{', '.join(irrelevant)}")

    ranks = {
        "INDUSTRY": industry_rank_metric,
        "CONCEPT": concept_rank_metric,
        "REGION": region_rank_metric,
    }
    selections = {
        "INDUSTRY": selected_industry_code,
        "CONCEPT": selected_concept_code,
        "REGION": selected_region_code,
    }
    rank_metric = (ranks[view] or _DEFAULT_RANK[view]).strip().upper()
    if rank_metric not in _RANK_VALUES[view]:
        raise ValueError(f"{_RANK_PARAM_BY_VIEW[view]} 不支持：{rank_metric}")
    return rank_metric, _normalize_sector_code(selections[view])


@router.get(
    "/sector-overview",
    response_model=SectorOverviewResponseDto,
)
def get_market_sector_overview(
    request: Request,
    market: str | None = Query(default=None),
    trade_date: str | None = Query(default=None, alias="tradeDate"),
    view: str | None = Query(default=None),
    industry_rank_metric: str | None = Query(default=None, alias="industryRankMetric"),
    selected_industry_code: str | None = Query(default=None, alias="selectedIndustryCode"),
    concept_rank_metric: str | None = Query(default=None, alias="conceptRankMetric"),
    selected_concept_code: str | None = Query(default=None, alias="selectedConceptCode"),
    region_rank_metric: str | None = Query(default=None, alias="regionRankMetric"),
    selected_region_code: str | None = Query(default=None, alias="selectedRegionCode"),
    debug: str | None = Query(default=None),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> SectorOverviewResponseDto:
    try:
        _validate_query_shape(request)
        normalized_market = (market or "CN_A").strip().upper()
        if normalized_market != "CN_A":
            raise ValueError(f"不支持的市场：{market}")
        normalized_view = (view or "INDUSTRY").strip().upper()
        rank_metric, selected_code = _resolve_view_params(
            request,
            view=normalized_view,
            industry_rank_metric=industry_rank_metric,
            selected_industry_code=selected_industry_code,
            concept_rank_metric=concept_rank_metric,
            selected_concept_code=selected_concept_code,
            region_rank_metric=region_rank_metric,
            selected_region_code=selected_region_code,
        )
        return MarketSectorOverviewQueryService().build_sector_overview(
            session,
            market=normalized_market,
            trade_date=_parse_date(trade_date),
            view=normalized_view,  # type: ignore[arg-type]
            rank_metric=rank_metric,  # type: ignore[arg-type]
            selected_code=selected_code,
            debug=_parse_debug(debug),
        )
    except ValueError as exc:
        raise WebAppError(status_code=400, code="400001", message=str(exc)) from exc
