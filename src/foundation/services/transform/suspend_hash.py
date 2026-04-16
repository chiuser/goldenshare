from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Mapping


SUSPEND_D_ROW_KEY_FIELDS = (
    "ts_code",
    "trade_date",
    "suspend_timing",
    "suspend_type",
)


def _serialize_hash_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _build_hash(row: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    payload = "|".join(_serialize_hash_value(row.get(field)) for field in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_suspend_d_row_key_hash(row: Mapping[str, Any]) -> str:
    return _build_hash(row, SUSPEND_D_ROW_KEY_FIELDS)

