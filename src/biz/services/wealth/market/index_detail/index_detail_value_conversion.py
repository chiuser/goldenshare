"""Numeric conversion for index detail response values."""

from typing import Any


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
