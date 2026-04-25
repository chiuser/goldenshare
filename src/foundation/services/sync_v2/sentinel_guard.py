from __future__ import annotations

from typing import Any


FORBIDDEN_BUSINESS_SENTINELS = frozenset({"__" + "ALL" + "__"})
SENTINEL_GUARDED_DATASETS = frozenset({"dc_hot", "ths_hot", "kpl_list", "limit_list_ths"})
ROW_QUERY_CONTEXT_FIELDS = (
    "query_market",
    "query_hot_type",
    "query_is_new",
    "query_limit_type",
    "tag",
)


def find_forbidden_business_sentinel(value: Any, *, path: str = "$") -> tuple[str, str] | None:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized in FORBIDDEN_BUSINESS_SENTINELS:
            return path, normalized
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            found = find_forbidden_business_sentinel(item, path=f"{path}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            found = find_forbidden_business_sentinel(item, path=f"{path}[{index}]")
            if found is not None:
                return found
        return None
    return None


def assert_no_forbidden_business_sentinel(value: Any, *, location: str) -> None:
    found = find_forbidden_business_sentinel(value)
    if found is None:
        return
    path, sentinel = found
    raise ValueError(f"forbidden business sentinel {sentinel!r} at {location}{path}")


def should_guard_dataset_rows(dataset_key: str) -> bool:
    return dataset_key in SENTINEL_GUARDED_DATASETS


def find_forbidden_business_sentinel_in_row_context(row: dict[str, Any], *, path: str) -> tuple[str, str] | None:
    for field_name in ROW_QUERY_CONTEXT_FIELDS:
        if field_name not in row:
            continue
        found = find_forbidden_business_sentinel(row[field_name], path=f"{path}.{field_name}")
        if found is not None:
            return found
    return None
