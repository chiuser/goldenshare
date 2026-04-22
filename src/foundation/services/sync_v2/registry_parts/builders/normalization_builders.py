from __future__ import annotations

from src.foundation.services.sync_v2.contracts import NormalizationSpec

def build_normalization_spec(**kwargs) -> NormalizationSpec:  # type: ignore[no-untyped-def]
    tuple_fields = ("date_fields", "decimal_fields", "required_fields")
    normalized = dict(kwargs)
    for key in tuple_fields:
        value = normalized.get(key)
        if value is not None:
            normalized[key] = tuple(value)
    return NormalizationSpec(**normalized)
