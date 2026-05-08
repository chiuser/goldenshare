from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from src.foundation.config.settings import get_settings
from src.foundation.datasets.models import (
    DatasetActionCapability,
    DatasetCapabilities,
    DatasetDateModel,
    DatasetDefinition,
    DatasetDomain,
    DatasetIdentity,
    DatasetInputField,
    DatasetInputModel,
    DatasetNormalizationDefinition,
    DatasetObservability,
    DatasetPlanningDefinition,
    DatasetQualityPolicy,
    DatasetSourceDefinition,
    DatasetStorageDefinition,
    DatasetTransactionDefinition,
    DatasetUniverseDefinition,
    DatasetUniverseSourceDefinition,
)


US_HOT_MARKET_VALUES_BY_DATASET = {
    "dc_hot": "美股市场",
    "ths_hot": "美股",
}


def _remove_value(values: tuple[str, ...], forbidden_value: str) -> tuple[str, ...]:
    return tuple(value for value in values if value != forbidden_value)


def _apply_hot_market_feature_flags(row: dict[str, Any]) -> dict[str, Any]:
    dataset_key = str(row["identity"]["dataset_key"])
    forbidden_market = US_HOT_MARKET_VALUES_BY_DATASET.get(dataset_key)
    if forbidden_market is None or get_settings().tushare_enable_us_hot_markets:
        return row

    patched = deepcopy(row)
    for field in patched["input_model"]["filters"]:
        if field.get("name") == "market":
            field["enum_values"] = _remove_value(tuple(field.get("enum_values", ())), forbidden_market)

    enum_defaults = patched["planning"].get("enum_fanout_defaults", {})
    if "market" in enum_defaults:
        enum_defaults["market"] = _remove_value(tuple(enum_defaults["market"]), forbidden_market)
    return patched


def build_definition(row: dict[str, Any]) -> DatasetDefinition:
    row = _apply_hot_market_feature_flags(row)
    identity = DatasetIdentity(**row["identity"])
    source_row = dict(row["source"])
    if "source_keys" not in source_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少来源清单")
    source_keys = tuple(str(item).strip().lower() for item in source_row["source_keys"] if str(item).strip())
    if not source_keys:
        raise ValueError(f"数据集定义 {identity.dataset_key} 来源清单不能为空")
    source_default = str(source_row["source_key_default"]).strip().lower()
    if source_default not in source_keys:
        raise ValueError(f"数据集定义 {identity.dataset_key} 默认来源必须属于来源清单")
    source_row["source_key_default"] = source_default
    source_row["source_keys"] = source_keys
    storage_row = dict(row["storage"])
    if "raw_table" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少原始层目标表")
    if "delivery_mode" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少交付模式")
    if "layer_plan" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少层级计划")
    if "std_table" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少标准层目标表")
    if "serving_table" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少服务层目标表")
    if "transaction" not in row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少事务策略")
    transaction_row = dict(row["transaction"])
    if "commit_policy" not in transaction_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少事务提交策略")
    planning_row = dict(row["planning"])
    universe_row = planning_row.get("universe")
    if universe_row is not None:
        planning_row["universe"] = DatasetUniverseDefinition(
            request_field=str(universe_row["request_field"]).strip(),
            override_fields=tuple(str(item).strip() for item in universe_row.get("override_fields", ()) if str(item).strip()),
            sources=tuple(DatasetUniverseSourceDefinition(**source) for source in universe_row.get("sources", ())),
        )
    return DatasetDefinition(
        identity=identity,
        domain=DatasetDomain(**row["domain"]),
        source=DatasetSourceDefinition(**source_row),
        date_model=DatasetDateModel(**row["date_model"]),
        input_model=DatasetInputModel(
            time_fields=tuple(DatasetInputField(**field) for field in row["input_model"]["time_fields"]),
            filters=tuple(DatasetInputField(**field) for field in row["input_model"]["filters"]),
            required_groups=tuple(tuple(item) for item in row["input_model"].get("required_groups", ())),
            mutually_exclusive_groups=tuple(tuple(item) for item in row["input_model"].get("mutually_exclusive_groups", ())),
            dependencies=tuple(tuple(item) for item in row["input_model"].get("dependencies", ())),
        ),
        storage=DatasetStorageDefinition(**storage_row),
        planning=DatasetPlanningDefinition(**planning_row),
        normalization=DatasetNormalizationDefinition(**row["normalization"]),
        capabilities=DatasetCapabilities(
            actions=tuple(DatasetActionCapability(**action) for action in row["capabilities"]["actions"]),
        ),
        observability=DatasetObservability(**row["observability"]),
        quality=DatasetQualityPolicy(**row["quality"]),
        transaction=DatasetTransactionDefinition(**transaction_row),
    )


def build_definitions(rows: Iterable[dict[str, Any]]) -> tuple[DatasetDefinition, ...]:
    return tuple(build_definition(row) for row in rows)
