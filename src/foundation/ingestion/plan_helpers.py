from __future__ import annotations

from datetime import date
from itertools import product
from typing import Any, Callable

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot, ValidatedDatasetActionRequest
from src.foundation.ingestion.sentinel_guard import assert_no_forbidden_business_sentinel


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
    request: ValidatedDatasetActionRequest,
    fields: tuple[str, ...],
    missing_field_defaults: dict[str, tuple[str, ...]] | None = None,
) -> list[dict[str, Any]]:
    if not fields:
        return [{}]

    missing_field_defaults = missing_field_defaults or {}
    assert_no_forbidden_business_sentinel(request.params, location="request.params")
    assert_no_forbidden_business_sentinel(missing_field_defaults, location="missing_field_defaults")

    options_by_field: list[tuple[str, list[str]]] = []
    for field_name in fields:
        selected = split_multi_values(request.params.get(field_name))
        if not selected and field_name in missing_field_defaults:
            selected = list(missing_field_defaults[field_name])
        if not selected:
            continue
        selected_set = {str(item).strip() for item in selected if str(item).strip()}
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
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
    anchors: list[date | None],
    enum_combinations: list[dict[str, Any]],
    request_builder: Callable[[ValidatedDatasetActionRequest, date | None, dict[str, Any]], dict[str, Any]],
    universe_values: list[dict[str, Any]] | None = None,
    pagination_policy_override: str | None = None,
    page_limit_override: int | None = None,
    progress_context_builder: Callable[[date | None, dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> list[PlanUnitSnapshot]:
    source_key = request.source_key or definition.source.source_key_default
    pagination_policy = pagination_policy_override or definition.planning.pagination_policy
    page_limit = page_limit_override if page_limit_override is not None else definition.planning.page_limit
    universe_values = universe_values or [{}]

    units: list[PlanUnitSnapshot] = []
    ordinal = 0
    for anchor in anchors:
        for enum_values in enum_combinations:
            for universe_value in universe_values:
                merged_values = {**enum_values, **universe_value}
                request_params = request_builder(request, anchor, merged_values)
                assert_no_forbidden_business_sentinel(request_params, location="plan_unit.request_params")
                progress_context = (
                    progress_context_builder(anchor, merged_values, request_params) if progress_context_builder else {}
                )
                units.append(
                    PlanUnitSnapshot(
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
                        progress_context=progress_context,
                        pagination_policy=pagination_policy,
                        page_limit=page_limit,
                    )
                )
                ordinal += 1
    return units
