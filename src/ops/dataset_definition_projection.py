from __future__ import annotations

from dataclasses import dataclass

from src.foundation.datasets.models import DatasetDefinition


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
