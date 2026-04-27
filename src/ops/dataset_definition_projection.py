from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions


@dataclass(frozen=True, slots=True)
class DatasetLayerProjection:
    dataset_key: str
    source_keys: tuple[str, ...]
    delivery_mode: str
    layer_plan: str
    raw_table: str
    std_table_hint: str | None
    serving_table: str | None
    raw_enabled: bool
    std_enabled: bool
    resolution_enabled: bool
    serving_enabled: bool
    notes: str

    @property
    def source_scope(self) -> str:
        return ",".join(self.source_keys)


@dataclass(frozen=True, slots=True)
class DatasetFreshnessProjection:
    dataset_key: str
    resource_key: str
    display_name: str
    domain_key: str
    domain_display_name: str
    target_table: str
    cadence: str
    raw_table: str
    observed_date_column: str | None = None
    primary_action_key: str | None = None


def build_dataset_layer_projection(definition: DatasetDefinition) -> DatasetLayerProjection:
    delivery_mode = definition.storage.delivery_mode
    return DatasetLayerProjection(
        dataset_key=definition.dataset_key,
        source_keys=definition.source.source_keys,
        delivery_mode=delivery_mode,
        layer_plan=definition.storage.layer_plan,
        raw_table=definition.storage.raw_table,
        std_table_hint=definition.storage.std_table,
        serving_table=definition.storage.serving_table,
        raw_enabled=True,
        std_enabled=delivery_mode == "multi_source_fusion",
        resolution_enabled=delivery_mode == "multi_source_fusion",
        serving_enabled=delivery_mode in {"single_source_serving", "multi_source_fusion"},
        notes=f"由 DatasetDefinition 派生：{delivery_mode_label(delivery_mode)}",
    )


def build_dataset_freshness_projection(definition: DatasetDefinition) -> DatasetFreshnessProjection:
    action = definition.capabilities.get_action("maintain")
    return DatasetFreshnessProjection(
        dataset_key=definition.dataset_key,
        resource_key=definition.dataset_key,
        display_name=definition.display_name,
        domain_key=definition.domain.domain_key,
        domain_display_name=definition.domain.domain_display_name,
        target_table=definition.storage.target_table,
        cadence=definition.domain.cadence,
        raw_table=definition.storage.raw_table,
        observed_date_column=definition.date_model.observed_field,
        primary_action_key=definition.action_key("maintain") if action is not None else None,
    )


@lru_cache(maxsize=1)
def list_dataset_freshness_projections() -> tuple[DatasetFreshnessProjection, ...]:
    return tuple(
        build_dataset_freshness_projection(definition)
        for definition in sorted(list_dataset_definitions(), key=lambda item: item.dataset_key)
    )


def get_dataset_freshness_projection(resource_key: str) -> DatasetFreshnessProjection | None:
    try:
        return build_dataset_freshness_projection(get_dataset_definition(resource_key))
    except KeyError:
        return None


def validate_dataset_freshness_projections(
    projections: dict[str, DatasetFreshnessProjection],
    *,
    observed_model_registry: dict[str, type],
) -> list[str]:
    errors: list[str] = []
    missing_models: list[str] = []
    missing_columns: list[str] = []
    for resource_key, projection in sorted(projections.items()):
        if projection.observed_date_column is None:
            continue
        model = observed_model_registry.get(projection.target_table)
        if model is None:
            missing_models.append(resource_key)
            continue
        if not hasattr(model, projection.observed_date_column):
            missing_columns.append(
                f"{resource_key}({projection.target_table}.{projection.observed_date_column})"
            )
    if missing_models:
        errors.append(f"Missing observed model mapping: {', '.join(missing_models)}")
    if missing_columns:
        errors.append(f"Missing observed date column on mapped model: {', '.join(missing_columns)}")
    return errors


def delivery_mode_label(delivery_mode: str) -> str:
    if delivery_mode == "single_source_serving":
        return "单源服务"
    if delivery_mode == "multi_source_fusion":
        return "多源融合"
    if delivery_mode == "raw_collection":
        return "原始采集"
    if delivery_mode == "core_direct":
        return "核心直写"
    return "未定义"


def delivery_mode_tone(delivery_mode: str) -> str:
    if delivery_mode == "single_source_serving":
        return "success"
    if delivery_mode == "multi_source_fusion":
        return "info"
    if delivery_mode == "raw_collection":
        return "neutral"
    if delivery_mode == "core_direct":
        return "warning"
    return "neutral"
