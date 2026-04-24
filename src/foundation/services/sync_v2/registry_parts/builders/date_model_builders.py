from __future__ import annotations

from src.foundation.services.sync_v2.contracts import DatasetDateModel
from src.foundation.services.sync_v2.registry_parts.common.date_models import get_dataset_date_model


def build_date_model(dataset_key: str) -> DatasetDateModel:
    return get_dataset_date_model(dataset_key)
