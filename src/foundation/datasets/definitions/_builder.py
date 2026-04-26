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
    storage_row = dict(row["storage"])
    storage_row.setdefault("raw_table", _infer_raw_table(identity.dataset_key))
    return DatasetDefinition(
        identity=identity,
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
        storage=DatasetStorageDefinition(**storage_row),
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


def _infer_raw_table(dataset_key: str) -> str:
    if dataset_key in {"stk_period_bar_week", "stk_period_bar_month"}:
        return "raw_tushare.stk_period_bar"
    if dataset_key in {"stk_period_bar_adj_week", "stk_period_bar_adj_month"}:
        return "raw_tushare.stk_period_bar_adj"
    if dataset_key == "index_weekly":
        return "raw_tushare.index_weekly_bar"
    if dataset_key == "index_monthly":
        return "raw_tushare.index_monthly_bar"
    if dataset_key == "limit_list_d":
        return "raw_tushare.limit_list"
    if dataset_key == "stk_holdernumber":
        return "raw_tushare.holdernumber"
    if dataset_key.startswith("biying_"):
        return f"raw_biying.{dataset_key.removeprefix('biying_')}"
    return f"raw_tushare.{dataset_key}"
