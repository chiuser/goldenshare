from __future__ import annotations

from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit, ValidatedRunRequest
from src.foundation.services.sync_v2.strategy_helpers.param_format import (
    build_plan_units,
    resolve_enum_combinations,
)
from src.foundation.services.sync_v2.strategy_helpers.trade_date_expand import resolve_anchors


def build_default_units(
    request: ValidatedRunRequest,
    contract: DatasetSyncContract,
    dao,
    settings,
    session,
    *,
    pagination_policy: str = "offset_limit",
    page_limit: int | None = None,
    anchor_type_override: str | None = None,
    window_policy_override: str | None = None,
    enum_fields: tuple[str, ...] = (),
    full_selection_values: dict[str, tuple[str, ...]] | None = None,
    missing_field_defaults: dict[str, tuple[str, ...]] | None = None,
    universe_values: list[dict[str, object]] | None = None,
) -> list[PlanUnit]:
    anchors = resolve_anchors(
        request=request,
        contract=contract,
        dao=dao,
        settings=settings,
        anchor_type_override=anchor_type_override,
        window_policy_override=window_policy_override,
    )
    enum_combinations = resolve_enum_combinations(
        request=request,
        fields=enum_fields,
        full_selection_values=full_selection_values,
        missing_field_defaults=missing_field_defaults,
    )
    return build_plan_units(
        request=request,
        contract=contract,
        anchors=anchors,
        enum_combinations=enum_combinations,
        universe_values=universe_values,
        pagination_policy_override=pagination_policy,
        page_limit_override=page_limit,
    )

