from __future__ import annotations

from src.foundation.services.sync_v2.strategy_helpers.param_format import (
    build_plan_units,
    resolve_enum_combinations,
    split_multi_values,
)


def _resolve_index_codes(request, dao) -> list[str]:
    explicit = split_multi_values(request.params.get("index_code"))
    if explicit:
        return sorted({str(code).strip().upper() for code in explicit if str(code).strip()})

    active_codes = dao.index_series_active.list_active_codes(request.dataset_key)
    if not active_codes:
        active_codes = [item.ts_code for item in dao.index_basic.get_active_indexes() if item.ts_code]
    normalized = sorted({str(code).strip().upper() for code in active_codes if str(code).strip()})
    if not normalized:
        raise RuntimeError(f"no active index codes found for dataset={request.dataset_key}")
    return normalized


def build_index_weight_units(request, contract, dao, settings, session):
    if request.run_profile != "range_rebuild":
        raise RuntimeError(f"index_weight unsupported run_profile: {request.run_profile}")

    enum_combinations = resolve_enum_combinations(request=request, fields=())
    universe_values = [{"index_code": code} for code in _resolve_index_codes(request, dao)]
    return build_plan_units(
        request=request,
        contract=contract,
        anchors=[None],
        enum_combinations=enum_combinations,
        universe_values=universe_values,
        pagination_policy_override="offset_limit",
        page_limit_override=6000,
    )
