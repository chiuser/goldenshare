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
    delivery_mode = _delivery_mode_from_definition(definition)
    return DatasetLayerProjection(
        dataset_key=definition.dataset_key,
        source_keys=_source_keys_from_definition(definition),
        delivery_mode=delivery_mode,
        layer_plan=_layer_plan(delivery_mode),
        raw_table=definition.storage.raw_table,
        std_table_hint=_std_table_hint(definition, delivery_mode),
        serving_table=_serving_table(definition, delivery_mode),
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


def _delivery_mode_from_definition(definition: DatasetDefinition) -> str:
    write_path = definition.storage.write_path
    target_table = definition.storage.target_table
    if write_path.startswith("raw_std_publish"):
        return "multi_source_fusion"
    if write_path == "raw_only_upsert" or target_table.startswith("raw_"):
        return "raw_collection"
    if target_table.startswith("core_serving."):
        return "single_source_serving"
    return "core_direct"


def _layer_plan(delivery_mode: str) -> str:
    if delivery_mode == "multi_source_fusion":
        return "raw->std->resolution->serving"
    if delivery_mode == "single_source_serving":
        return "raw->serving"
    if delivery_mode == "raw_collection":
        return "raw-only"
    if delivery_mode == "core_direct":
        return "raw->core"
    return "unknown"


def _std_table_hint(definition: DatasetDefinition, delivery_mode: str) -> str | None:
    if delivery_mode != "multi_source_fusion":
        return None
    return f"core_multi.{definition.storage.core_dao_name}"


def _serving_table(definition: DatasetDefinition, delivery_mode: str) -> str | None:
    if delivery_mode in {"raw_collection", "core_direct"}:
        return None
    if definition.storage.target_table.startswith("core_serving."):
        return definition.storage.target_table
    return None


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


def _source_keys_from_definition(definition: DatasetDefinition) -> tuple[str, ...]:
    source_values: set[str] = set()
    for field in definition.input_model.filters:
        if field.name != "source_key":
            continue
        source_values.update(
            value.lower()
            for value in field.enum_values
            if value and value.lower() != "all"
        )
    if not source_values:
        source_values.add(definition.source.source_key_default.lower())
    return tuple(sorted(source_values))
