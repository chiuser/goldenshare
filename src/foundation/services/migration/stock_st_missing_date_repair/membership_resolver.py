from __future__ import annotations

from src.foundation.services.migration.stock_st_missing_date_repair.models import StockStNamechangeRecord


def normalize_st_display_name(name: str | None) -> str:
    if not name:
        return ""
    normalized = name.strip()
    while True:
        stripped = False
        for prefix in ("XR", "XD", "DR"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                stripped = True
                break
        if not stripped:
            break
    if normalized.startswith("N"):
        normalized = normalized[1:]
    return normalized


def is_st_like_name(name: str | None) -> bool:
    normalized = normalize_st_display_name(name)
    return normalized.startswith(("S*ST", "SST", "*ST", "ST"))


def select_latest_namechange(records: tuple[StockStNamechangeRecord, ...]) -> StockStNamechangeRecord | None:
    if not records:
        return None
    return records[0]

