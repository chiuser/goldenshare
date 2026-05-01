from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions


@dataclass(frozen=True, slots=True)
class DatasetLayerStageProjection:
    stage: str
    display_name: str
    enabled: bool
    status_source: str
    message: str | None


@dataclass(frozen=True, slots=True)
class DatasetLayerProjection:
    dataset_key: str
    source_keys: tuple[str, ...]
    delivery_mode: str
    layer_plan: str
    raw_table: str
    std_table_hint: str | None
    serving_table: str | None
    stages: tuple[DatasetLayerStageProjection, ...]
    notes: str

    @property
    def source_scope(self) -> str:
        return ",".join(self.source_keys)

    @property
    def stage_keys(self) -> tuple[str, ...]:
        return tuple(item.stage for item in self.stages if item.enabled)

    @property
    def all_stage_keys(self) -> tuple[str, ...]:
        return tuple(item.stage for item in self.stages)

    def stage(self, stage_key: str) -> DatasetLayerStageProjection | None:
        normalized = stage_key.strip().lower()
        for item in self.stages:
            if item.stage == normalized:
                return item
        return None


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
        stages=build_layer_stage_projections(delivery_mode),
        notes=f"由 DatasetDefinition 派生：{delivery_mode_label(delivery_mode)}",
    )


def build_layer_stage_projections(delivery_mode: str) -> tuple[DatasetLayerStageProjection, ...]:
    std_enabled = delivery_mode == "multi_source_fusion"
    serving_enabled = delivery_mode in {"single_source_serving", "multi_source_fusion"}
    light_enabled = delivery_mode == "raw_with_serving_light_view"
    stages = [
        DatasetLayerStageProjection(
            stage="raw",
            display_name=_require_layer_stage_display_name("raw"),
            enabled=True,
            status_source="freshness",
            message=f"由 DatasetDefinition 派生：{delivery_mode_label(delivery_mode)}",
        ),
        DatasetLayerStageProjection(
            stage="std",
            display_name=_require_layer_stage_display_name("std"),
            enabled=std_enabled,
            status_source="unobserved" if std_enabled else "skipped",
            message="该层已启用，但暂未接入独立观测指标" if std_enabled else "当前模式未启用 std 物化",
        ),
        DatasetLayerStageProjection(
            stage="resolution",
            display_name=_require_layer_stage_display_name("resolution"),
            enabled=std_enabled,
            status_source="unobserved" if std_enabled else "skipped",
            message="该层已启用，但暂未接入独立观测指标" if std_enabled else "当前模式未启用融合决策层",
        ),
        DatasetLayerStageProjection(
            stage="serving",
            display_name=_require_layer_stage_display_name("serving"),
            enabled=serving_enabled,
            status_source="freshness" if serving_enabled else "skipped",
            message=None if serving_enabled else "当前模式不产出 serving",
        ),
    ]
    if light_enabled:
        stages.append(
            DatasetLayerStageProjection(
                stage="light",
                display_name=_require_layer_stage_display_name("light"),
                enabled=True,
                status_source="freshness",
                message="当前模式通过轻量服务 view 直出",
            )
        )
    return tuple(stages)


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
    if delivery_mode == "raw_with_serving_light_view":
        return "轻量服务直出"
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
    if delivery_mode == "raw_with_serving_light_view":
        return "success"
    if delivery_mode == "core_direct":
        return "warning"
    return "neutral"


LAYER_STAGE_ORDER = ("raw", "std", "resolution", "serving", "light")

LAYER_STAGE_DISPLAY_NAMES = {
    "raw": "原始层",
    "std": "标准层",
    "resolution": "融合层",
    "serving": "服务层",
    "light": "轻量服务层",
}


def get_layer_stage_display_name(stage: str | None) -> str | None:
    normalized = (stage or "").strip().lower()
    if not normalized:
        return None
    return LAYER_STAGE_DISPLAY_NAMES.get(normalized)


def _require_layer_stage_display_name(stage: str) -> str:
    display_name = get_layer_stage_display_name(stage)
    if display_name is None:
        raise ValueError(f"层级缺少显示名称：{stage}")
    return display_name
