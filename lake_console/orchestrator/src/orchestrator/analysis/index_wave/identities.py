"""Stable serialization and identity helpers for the wave domain."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256


def as_decimal(value: Decimal | int | float | str) -> Decimal:
    """Convert a finite numeric value without hashing a binary float repr."""

    try:
        converted = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"numeric value is not a valid decimal: {value!r}") from exc
    if not converted.is_finite():
        raise ValueError(f"numeric value must be finite: {value!r}")
    return converted


def canonical_decimal(value: Decimal | int | float | str) -> str:
    """Return a cross-platform, non-exponent decimal representation."""

    converted = as_decimal(value)
    if converted == 0:
        return "0"
    rendered = format(converted.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def canonical_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.isoformat(timespec="microseconds")


def stable_hash(*parts: str) -> str:
    return sha256("".join(parts).encode("utf-8")).hexdigest()
