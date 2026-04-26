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
    return DatasetDefinition(
        identity=DatasetIdentity(**row["identity"]),
        domain=DatasetDomain(**row["domain"]),
        source=DatasetSourceDefinition(**row["source"]),
        date_model=DatasetDateModel(**row["date_model"]),
        input_model=DatasetInputModel(
            time_fields=tuple(DatasetInputField(**field) for field in row["input_model"]["time_fields"]),
            filters=tuple(DatasetInputField(**field) for field in row["input_model"]["filters"]),
            required_groups=tuple(tuple(item) for item in row["input_model"].get("required_groups", ())),
            mutually_exclusive_groups=tuple(tuple(item) for item in row["input_model"].get("mutually_exclusive_groups", ())),
            dependencies=tuple(tuple(item) for item in row["input_model"].get("dependencies", ())),
        ),
        storage=DatasetStorageDefinition(**row["storage"]),
        planning=DatasetPlanningDefinition(**row["planning"]),
        normalization=DatasetNormalizationDefinition(**row["normalization"]),
        capabilities=DatasetCapabilities(
            actions=tuple(DatasetActionCapability(**action) for action in row["capabilities"]["actions"]),
        ),
        observability=DatasetObservability(**row["observability"]),
        quality=DatasetQualityPolicy(**row["quality"]),
        transaction=DatasetTransactionDefinition(**row.get("transaction", {})),
    )


def build_definitions(rows: Iterable[dict[str, Any]]) -> tuple[DatasetDefinition, ...]:
    return tuple(build_definition(row) for row in rows)
