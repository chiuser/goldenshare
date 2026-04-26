from __future__ import annotations

from functools import lru_cache

from src.foundation.datasets.definitions import list_defined_datasets
from src.foundation.datasets.models import DatasetDefinition


@lru_cache(maxsize=1)
def list_dataset_definitions() -> tuple[DatasetDefinition, ...]:
    return list_defined_datasets()


def get_dataset_definition(dataset_key: str) -> DatasetDefinition:
    for definition in list_dataset_definitions():
        if definition.dataset_key == dataset_key:
            return definition
    raise KeyError(f"dataset definition not found for dataset={dataset_key}")


def get_dataset_action_key(dataset_key: str, action: str = "maintain") -> str:
    return get_dataset_definition(dataset_key).action_key(action)


def get_dataset_definition_by_action_key(action_key: str) -> tuple[DatasetDefinition, str]:
    for definition in list_dataset_definitions():
        for action in definition.capabilities.actions:
            if definition.action_key(action.action) == action_key:
                return definition, action.action
    raise KeyError(f"dataset definition not found for action_key={action_key}")
