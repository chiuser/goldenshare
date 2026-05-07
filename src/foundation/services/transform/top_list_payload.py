from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import math
from typing import Any, Mapping


TOP_LIST_PAYLOAD_FIELDS = (
    "ts_code",
    "trade_date",
    "reason",
    "name",
    "close",
    "pct_change",
    "turnover_rate",
    "amount",
    "l_sell",
    "l_buy",
    "l_amount",
    "net_amount",
    "net_rate",
    "amount_rate",
    "float_values",
)

_PSEUDO_NULL_TEXTS = {"", "nan", "nat", "none", "null"}


def build_top_list_payload_hash(row: Mapping[str, Any]) -> str:
    payload = "\x1f".join(_payload_field_text(field_name, _field_value(row, field_name)) for field_name in TOP_LIST_PAYLOAD_FIELDS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _field_value(row: Mapping[str, Any], field_name: str) -> Any:
    if field_name in row:
        return row.get(field_name)
    if field_name == "pct_change" and "pct_chg" in row:
        return row.get("pct_chg")
    return None


def _payload_field_text(field_name: str, value: Any) -> str:
    normalized = _normalize_payload_value(field_name, value)
    if normalized is None:
        return "null"
    return normalized


def _normalize_payload_value(field_name: str, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value.is_nan():
            return None
        return _canonical_decimal_text(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return _canonical_decimal_text(Decimal(str(value)))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if field_name == "trade_date" else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    if text.strip().lower() in _PSEUDO_NULL_TEXTS:
        return None
    if field_name in {"reason", "name"}:
        return text
    return text.strip()


def _canonical_decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text
