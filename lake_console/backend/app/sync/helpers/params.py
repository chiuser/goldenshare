from __future__ import annotations

from datetime import date
from typing import Any


def parse_csv(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def parse_date(value: Any) -> date:
    if hasattr(value, "date") and callable(value.date):
        return value.date()
    if isinstance(value, date):
        return value
    raw_value = str(value).strip()
    if len(raw_value) == 8 and raw_value.isdigit():
        return date(int(raw_value[:4]), int(raw_value[4:6]), int(raw_value[6:]))
    return date.fromisoformat(raw_value)
