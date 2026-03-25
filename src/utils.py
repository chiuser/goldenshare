from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def chunked(items: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def parse_tushare_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.fromisoformat(text).date()


def to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def coerce_row(row: dict[str, Any], date_fields: Iterable[str], decimal_fields: Iterable[str]) -> dict[str, Any]:
    normalized = dict(row)
    for key in date_fields:
        if key in normalized:
            normalized[key] = parse_tushare_date(normalized.get(key))
    for key in decimal_fields:
        if key in normalized:
            normalized[key] = to_decimal(normalized.get(key))
    return normalized
