from __future__ import annotations

from datetime import date
from itertools import product
from typing import Any

from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit, ValidatedRunRequest


def split_multi_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def resolve_enum_combinations(
    *,
    request: ValidatedRunRequest,
    fields: tuple[str, ...],
    full_selection_values: dict[str, tuple[str, ...]] | None = None,
    missing_field_defaults: dict[str, tuple[str, ...]] | None = None,
) -> list[dict[str, Any]]:
    if not fields:
        return [{}]

    full_selection_values = full_selection_values or {}
    missing_field_defaults = missing_field_defaults or {}

    options_by_field: list[tuple[str, list[str]]] = []
    for field_name in fields:
        selected = split_multi_values(request.params.get(field_name))
        if not selected and field_name in missing_field_defaults:
            selected = list(missing_field_defaults[field_name])

        if not selected:
            continue

        selected_set = {str(item).strip() for item in selected if str(item).strip()}
        full_values = full_selection_values.get(field_name)
        if full_values is not None and selected_set == set(full_values):
            continue
        options_by_field.append((field_name, sorted(selected_set)))

    if not options_by_field:
        return [{}]

    names = [name for name, _ in options_by_field]
    values = [items for _, items in options_by_field]
    return [{names[index]: row[index] for index in range(len(names))} for row in product(*values)]


def build_unit_id(
    *,
    dataset_key: str,
    anchor: date | None,
    merged_values: dict[str, Any],
    ordinal: int,
) -> str:
    anchor_text = anchor.isoformat() if anchor is not None else "none"
    if not merged_values:
        return f"{dataset_key}:{anchor_text}:{ordinal}"
    merged_text = ",".join(f"{key}={merged_values[key]}" for key in sorted(merged_values.keys()))
    return f"{dataset_key}:{anchor_text}:{merged_text}:{ordinal}"


def build_plan_units(
    *,
    request: ValidatedRunRequest,
    contract: DatasetSyncContract,
    anchors: list[date | None],
    enum_combinations: list[dict[str, Any]],
    universe_values: list[dict[str, Any]] | None = None,
    pagination_policy_override: str | None = None,
    page_limit_override: int | None = None,
) -> list[PlanUnit]:
    source_key = request.source_key or contract.source_spec.source_key_default
    pagination_policy = pagination_policy_override or contract.planning_spec.pagination_policy
    page_limit = (
        page_limit_override
        if page_limit_override is not None
        else contract.pagination_spec.page_limit
    )
    universe_values = universe_values or [{}]

    units: list[PlanUnit] = []
    ordinal = 0
    for anchor in anchors:
        for enum_values in enum_combinations:
            for universe_value in universe_values:
                merged_values = {**enum_values, **universe_value}
                request_params = contract.source_spec.unit_params_builder(request, anchor, merged_values)
                units.append(
                    PlanUnit(
                        unit_id=build_unit_id(
                            dataset_key=request.dataset_key,
                            anchor=anchor,
                            merged_values=merged_values,
                            ordinal=ordinal,
                        ),
                        dataset_key=request.dataset_key,
                        source_key=source_key,
                        trade_date=anchor,
                        request_params=request_params,
                        pagination_policy=pagination_policy,
                        page_limit=page_limit,
                    )
                )
                ordinal += 1
    return units
