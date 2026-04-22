from __future__ import annotations

from src.foundation.services.sync_v2.strategy_helpers.param_format import (
    build_plan_units,
    resolve_enum_combinations,
)
from src.foundation.services.sync_v2.strategy_helpers.trade_date_expand import resolve_anchors


def build_index_weekly_units(request, contract, dao, settings, session):
    anchors = resolve_anchors(
        request=request,
        contract=contract,
        dao=dao,
        settings=settings,
    )
    enum_combinations = resolve_enum_combinations(request=request, fields=())
    return build_plan_units(
        request=request,
        contract=contract,
        anchors=anchors,
        enum_combinations=enum_combinations,
        pagination_policy_override="offset_limit",
        page_limit_override=1000,
    )
