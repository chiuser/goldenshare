from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.foundation.services.sync_v2.dataset_strategies.common import build_default_units
from src.foundation.services.sync_v2.strategy_helpers.param_format import split_multi_values


DC_HOT_DEFAULT_MARKETS = ("A股市场", "ETF基金", "港股市场", "美股市场")
DC_HOT_DEFAULT_HOT_TYPES = ("人气榜", "飙升榜")
DC_HOT_DEFAULT_IS_NEW = ("Y",)


def _with_safe_default_filters(request):
    params = dict(request.params)
    _fill_default(params, "market", DC_HOT_DEFAULT_MARKETS)
    _fill_default(params, "hot_type", DC_HOT_DEFAULT_HOT_TYPES)
    _fill_default(params, "is_new", DC_HOT_DEFAULT_IS_NEW)
    return replace(request, params=params)


def _fill_default(params: dict[str, Any], key: str, values: tuple[str, ...]) -> None:
    selected_values = {item.strip() for item in split_multi_values(params.get(key)) if item.strip()}
    if not selected_values or "__ALL__" in selected_values:
        params[key] = list(values)


def build_dc_hot_units(request, contract, dao, settings, session):
    safe_request = _with_safe_default_filters(request)
    return build_default_units(
        safe_request,
        contract,
        dao,
        settings,
        session,
        page_limit=2000,
        enum_fields=("market", "hot_type", "is_new"),
    )
