from __future__ import annotations

from src.foundation.services.sync_v2.contracts import WriteSpec

def build_write_spec(**kwargs) -> WriteSpec:  # type: ignore[no-untyped-def]
    normalized = dict(kwargs)
    if "conflict_columns" in normalized and normalized["conflict_columns"] is not None:
        normalized["conflict_columns"] = tuple(normalized["conflict_columns"])
    return WriteSpec(**normalized)
