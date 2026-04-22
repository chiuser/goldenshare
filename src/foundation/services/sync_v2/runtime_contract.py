from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit, ValidatedRunRequest
from src.foundation.services.sync_v2.dataset_strategies import get_dataset_strategy

DatasetStrategyFn = Callable[
    [ValidatedRunRequest, DatasetSyncContract, object, object, Session],
    list[PlanUnit],
]


@dataclass(slots=True, frozen=True)
class DatasetRuntimeContract:
    dataset_key: str
    api_name: str
    fields: tuple[str, ...]
    source_key_default: str
    run_profiles_supported: tuple[str, ...]
    strategy_fn: DatasetStrategyFn | None


def to_runtime_contract(contract: DatasetSyncContract) -> DatasetRuntimeContract:
    return DatasetRuntimeContract(
        dataset_key=contract.dataset_key,
        api_name=contract.source_spec.api_name,
        fields=contract.source_spec.fields,
        source_key_default=contract.source_spec.source_key_default,
        run_profiles_supported=contract.run_profiles_supported,
        strategy_fn=get_dataset_strategy(contract.dataset_key),
    )

