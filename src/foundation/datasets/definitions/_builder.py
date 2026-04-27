from __future__ import annotations

from collections.abc import Iterable
from typing import Any

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
)


def build_definition(row: dict[str, Any]) -> DatasetDefinition:
    identity = DatasetIdentity(**row["identity"])
    source_row = dict(row["source"])
    if "source_keys" not in source_row:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} must declare source.source_keys explicitly")
    source_keys = tuple(str(item).strip().lower() for item in source_row["source_keys"] if str(item).strip())
    if not source_keys:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} source.source_keys must not be empty")
    source_default = str(source_row["source_key_default"]).strip().lower()
    if source_default not in source_keys:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} source_key_default must be included in source.source_keys")
    source_row["source_key_default"] = source_default
    source_row["source_keys"] = source_keys
    storage_row = dict(row["storage"])
    if "raw_table" not in storage_row:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} must declare storage.raw_table explicitly")
    if "delivery_mode" not in storage_row:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} must declare storage.delivery_mode explicitly")
    if "layer_plan" not in storage_row:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} must declare storage.layer_plan explicitly")
    if "std_table" not in storage_row:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} must declare storage.std_table explicitly")
    if "serving_table" not in storage_row:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} must declare storage.serving_table explicitly")
    if "transaction" not in row:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} must declare transaction explicitly")
    transaction_row = dict(row["transaction"])
    if "commit_policy" not in transaction_row:
        raise ValueError(f"DatasetDefinition {identity.dataset_key} must declare transaction.commit_policy explicitly")
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
        planning=DatasetPlanningDefinition(**row["planning"]),
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
