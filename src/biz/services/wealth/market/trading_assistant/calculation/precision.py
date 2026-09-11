"""Exact arithmetic for design §4.32. All final monetary values are cents."""

import re

from src.biz.schemas.wealth.market.trading_assistant.input_policy import DECIMAL_INPUT_MAX_INTEGER_DIGITS


class CalculationInvariantError(ValueError):
    """Invalid frozen calculation facts, not an HTTP request error."""


def require_integer(value: int, *, minimum: int | None = None) -> None:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise CalculationInvariantError("Invalid integer calculation fact")


def round_ratio_half_up(numerator: int, denominator: int) -> int:
    require_integer(numerator)
    require_integer(denominator, minimum=1)
    quotient, remainder = divmod(abs(numerator), denominator)
    result = quotient + (2 * remainder >= denominator)
    return -result if numerator < 0 else result


def format_cents(value: int) -> str:
    require_integer(value)
    whole, fraction = divmod(abs(value), 100)
    return f"{'-' if value < 0 else ''}{whole}.{fraction:02d}"


def parse_money_cents(value: str) -> int:
    if type(value) is not str or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]{1,2})?", value):
        raise CalculationInvariantError("Expected fixed-point decimal text")
    digits = value.lstrip("-").split(".")
    whole = digits[0].lstrip("0") or "0"
    if len(whole) > DECIMAL_INPUT_MAX_INTEGER_DIGITS:
        raise CalculationInvariantError("Input exceeds 18 integer digits")
    cents = int(whole) * 100 + int(digits[1].ljust(2, "0") if len(digits) == 2 else "0")
    return -cents if value.startswith("-") else cents


def format_return_pct(profit_cents: int, capital_cents: int) -> str:
    require_integer(profit_cents)
    require_integer(capital_cents, minimum=1)
    return format_cents(round_ratio_half_up(profit_cents * 10000, capital_cents))


def compare_return(a_profit: int, a_capital: int, b_profit: int, b_capital: int) -> int:
    require_integer(a_profit)
    require_integer(b_profit)
    require_integer(a_capital, minimum=1)
    require_integer(b_capital, minimum=1)
    difference = a_profit * b_capital - b_profit * a_capital
    return (difference > 0) - (difference < 0)
