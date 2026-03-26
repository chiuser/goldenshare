from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping


DIVIDEND_ROW_KEY_FIELDS = (
    "ts_code",
    "end_date",
    "ann_date",
    "div_proc",
    "stk_div",
    "stk_bo_rate",
    "stk_co_rate",
    "cash_div",
    "cash_div_tax",
    "record_date",
    "ex_date",
    "pay_date",
    "div_listdate",
    "imp_ann_date",
    "base_date",
    "base_share",
)

DIVIDEND_EVENT_KEY_FIELDS = (
    "ts_code",
    "end_date",
    "ann_date",
    "div_proc",
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


def build_dividend_row_key_hash(row: Mapping[str, Any]) -> str:
    return _build_hash(row, DIVIDEND_ROW_KEY_FIELDS)


def build_dividend_event_key_hash(row: Mapping[str, Any]) -> str:
    return _build_hash(row, DIVIDEND_EVENT_KEY_FIELDS)
