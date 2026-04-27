from __future__ import annotations


LEGACY_COMBINED_SOURCE_KEYS = {"__all__", "all", "combined"}


def normalize_layer_snapshot_source_key(source_key: str | None) -> str | None:
    normalized = (source_key or "").strip().lower()
    if not normalized:
        return None
    if normalized in LEGACY_COMBINED_SOURCE_KEYS:
        return "combined"
    return normalized


def matches_layer_snapshot_source_filter(*, row_source_key: str | None, requested_source_key: str | None) -> bool:
    normalized_row = normalize_layer_snapshot_source_key(row_source_key)
    normalized_requested = normalize_layer_snapshot_source_key(requested_source_key)
    if normalized_requested is None:
        return True
    return normalized_row in {normalized_requested, "combined"}

