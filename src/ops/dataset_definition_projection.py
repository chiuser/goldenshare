from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions


@dataclass(frozen=True, slots=True)
class DatasetPipelineProjection:
    dataset_key: str
    source_keys: tuple[str, ...]
    mode: str
    layer_plan: str
    raw_table: str | None
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
    raw_table: str | None = None
    observed_date_column: str | None = None
    primary_action_key: str | None = None


def build_dataset_pipeline_projection(definition: DatasetDefinition) -> DatasetPipelineProjection:
    mode = _mode_from_definition(definition)
    return DatasetPipelineProjection(
        dataset_key=definition.dataset_key,
        source_keys=_source_keys_from_definition(definition),
        mode=mode,
        layer_plan=_layer_plan(mode),
        raw_table=definition.storage.raw_table,
        std_table_hint=_std_table_hint(definition, mode),
        serving_table=_serving_table(definition, mode),
        raw_enabled=True,
        std_enabled=mode == "multi_source_pipeline",
        resolution_enabled=mode == "multi_source_pipeline",
        serving_enabled=mode in {"single_source_direct", "multi_source_pipeline"},
        notes=f"由 DatasetDefinition 派生：{mode}",
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


def _mode_from_definition(definition: DatasetDefinition) -> str:
    write_path = definition.storage.write_path
    target_table = definition.storage.target_table
    if write_path.startswith("raw_std_publish"):
        return "multi_source_pipeline"
    if write_path == "raw_only_upsert" or target_table.startswith("raw_"):
        return "raw_only"
    if target_table.startswith("core_serving."):
        return "single_source_direct"
    return "direct_maintain"


def _layer_plan(mode: str) -> str:
    if mode == "multi_source_pipeline":
        return "raw->std->resolution->serving"
    if mode == "single_source_direct":
        return "raw->serving"
    if mode == "raw_only":
        return "raw-only"
    if mode == "direct_maintain":
        return "raw->core"
    return "unknown"


def _std_table_hint(definition: DatasetDefinition, mode: str) -> str | None:
    if mode != "multi_source_pipeline":
        return None
    return f"core_multi.{definition.storage.core_dao_name}"


def _serving_table(definition: DatasetDefinition, mode: str) -> str | None:
    if mode in {"raw_only", "direct_maintain"}:
        return None
    if definition.storage.target_table.startswith("core_serving."):
        return definition.storage.target_table
    return None


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
