from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_TEN_THOUSAND = Decimal("10000")
_TWO_DECIMAL_PLACES = Decimal("0.01")


def format_daily_volume_display(value: object | None) -> str | None:
    if value is None:
        return None

    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None

    if not decimal_value.is_finite():
        return None

    scaled = (decimal_value / _TEN_THOUSAND).quantize(
        _TWO_DECIMAL_PLACES,
        rounding=ROUND_HALF_UP,
    )
    return f"{scaled:.2f}万"
