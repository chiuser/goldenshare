from __future__ import annotations

from src.foundation.services.sync_v2.strategy_helpers.param_format import (
    build_plan_units,
    resolve_enum_combinations,
    split_multi_values,
)
from src.foundation.services.sync_v2.strategy_helpers.trade_date_expand import resolve_anchors


def _resolve_index_codes(request, dao) -> list[str]:
    explicit_codes = split_multi_values(request.params.get("ts_code"))
    if explicit_codes:
        return sorted({str(code).strip().upper() for code in explicit_codes if str(code).strip()})

    active_codes = dao.index_series_active.list_active_codes("index_daily")
    if not active_codes:
        active_codes = [item.ts_code for item in dao.index_basic.get_active_indexes() if item.ts_code]
    normalized_codes = sorted({str(code).strip().upper() for code in active_codes if str(code).strip()})
    if not normalized_codes:
        raise RuntimeError("no active index codes found for dataset=index_monthly")
    return normalized_codes


def build_index_monthly_units(request, contract, dao, settings, session):
    anchors = resolve_anchors(
        request=request,
        contract=contract,
        dao=dao,
        settings=settings,
    )
    enum_combinations = resolve_enum_combinations(request=request, fields=())
    universe_values = [{"ts_code": code} for code in _resolve_index_codes(request, dao)]
    return build_plan_units(
        request=request,
        contract=contract,
        anchors=anchors,
        enum_combinations=enum_combinations,
        universe_values=universe_values,
        pagination_policy_override="offset_limit",
        page_limit_override=1000,
    )
