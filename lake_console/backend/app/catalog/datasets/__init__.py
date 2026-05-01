from __future__ import annotations

from lake_console.backend.app.catalog.datasets.market_equity import MARKET_EQUITY_DATASETS
from lake_console.backend.app.catalog.datasets.moneyflow import MONEYFLOW_DATASETS
from lake_console.backend.app.catalog.datasets.reference_master import REFERENCE_MASTER_DATASETS
from lake_console.backend.app.catalog.models import LakeDatasetDefinition


LAKE_DATASETS: tuple[LakeDatasetDefinition, ...] = (
    *REFERENCE_MASTER_DATASETS,
    *MARKET_EQUITY_DATASETS,
    *MONEYFLOW_DATASETS,
)

_DATASET_BY_KEY = {dataset.dataset_key: dataset for dataset in LAKE_DATASETS}


def get_dataset_definition(dataset_key: str) -> LakeDatasetDefinition:
    try:
        return _DATASET_BY_KEY[dataset_key]
    except KeyError as exc:
        raise ValueError(f"Unknown Lake dataset: {dataset_key}") from exc


def list_dataset_definitions() -> tuple[LakeDatasetDefinition, ...]:
    return LAKE_DATASETS
