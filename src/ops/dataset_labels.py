from __future__ import annotations

from functools import lru_cache

from src.foundation.datasets.registry import get_dataset_definition


@lru_cache(maxsize=512)
def get_dataset_display_name(dataset_key: str | None) -> str | None:
    normalized_key = (dataset_key or "").strip()
    if not normalized_key:
        return None
    try:
        return get_dataset_definition(normalized_key).display_name
    except KeyError:
        return None
