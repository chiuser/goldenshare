"""Exact NUMERIC/integer boundary; Decimal context cannot round these conversions."""
from decimal import Decimal


def money_numeric(cents: int) -> Decimal:
    if type(cents) is not int:
        raise ValueError("Expected exact integer cents")
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return Decimal(f"{sign}{whole}.{fraction:02d}")


def numeric_cents(value: Decimal) -> int:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Invalid stored money")
    numerator, denominator = value.as_integer_ratio()
    cents, remainder = divmod(numerator * 100, denominator)
    if remainder:
        raise ValueError("Stored amount is not exact cents")
    return cents


def integer_numeric(value: int) -> Decimal:
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative exact integer")
    return Decimal(value)


def numeric_integer(value: Decimal) -> int:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError("Invalid derived quantity in storage")
    integer = int(value)
    if value != integer:
        raise ValueError("Stored derived quantity is fractional")
    return integer


def quantity_text(value: int | Decimal) -> str:
    if isinstance(value, Decimal):
        value = numeric_integer(value)
    if type(value) is not int or value < 0:
        raise ValueError("Invalid derived quantity")
    return str(value)
