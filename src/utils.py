from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any


PSEUDO_NULL_TEXTS = {"0", "nan", "nat", "none", "null"}


class CoerceRowError(ValueError):
    def __init__(self, *, reason_code: str, field: str, value: Any, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.field = field
        self.value = value


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
    text = str(value).strip()
    if not text or text.lower() in PSEUDO_NULL_TEXTS:
        return None
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
            value = normalized.get(key)
            try:
                normalized[key] = parse_tushare_date(value)
            except (TypeError, ValueError) as exc:
                raise CoerceRowError(
                    reason_code="normalize.invalid_date",
                    field=key,
                    value=value,
                    message=f"invalid date field `{key}`: {value}",
                ) from exc
    for key in decimal_fields:
        if key in normalized:
            value = normalized.get(key)
            try:
                normalized[key] = to_decimal(value)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise CoerceRowError(
                    reason_code="normalize.invalid_decimal",
                    field=key,
                    value=value,
                    message=f"invalid decimal field `{key}`: {value}",
                ) from exc
    return normalized


def truncate_text(value: str | None, max_length: int, *, suffix: str = "... [已截断]") -> str | None:
    if value is None:
        return None
    if max_length <= 0:
        return ""
    if len(value) <= max_length:
        return value
    reserve = max(max_length - len(suffix), 0)
    return value[:reserve] + suffix
