from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping


HOLDERNUMBER_ROW_KEY_FIELDS = (
    "ts_code",
    "ann_date",
    "end_date",
    "holder_num",
)

HOLDERNUMBER_EVENT_KEY_FIELDS = (
    "ts_code",
    "end_date",
)


def _serialize_hash_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _build_hash(row: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    payload = "|".join(_serialize_hash_value(row.get(field)) for field in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_holdernumber_row_key_hash(row: Mapping[str, Any]) -> str:
    return _build_hash(row, HOLDERNUMBER_ROW_KEY_FIELDS)


def build_holdernumber_event_key_hash(row: Mapping[str, Any]) -> str:
    return _build_hash(row, HOLDERNUMBER_EVENT_KEY_FIELDS)
