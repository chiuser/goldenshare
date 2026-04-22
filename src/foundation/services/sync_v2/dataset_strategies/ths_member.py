from __future__ import annotations

from src.foundation.services.sync_v2.strategy_helpers.param_format import (
    build_plan_units,
    resolve_enum_combinations,
)


def build_ths_member_units(request, contract, dao, settings, session):
    enum_combinations = resolve_enum_combinations(request=request, fields=())
    return build_plan_units(
        request=request,
        contract=contract,
        anchors=[None],
        enum_combinations=enum_combinations,
        universe_values=[{}],
        pagination_policy_override="offset_limit",
        page_limit_override=5000,
    )

