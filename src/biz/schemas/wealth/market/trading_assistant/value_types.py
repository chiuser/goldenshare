"""Strict wire values from §4.28. Never implicitly coerce a JSON number to text."""

from datetime import date, datetime, timedelta
import re
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BeforeValidator, Field, StrictInt, StrictStr

from .input_policy import (ACCOUNT_NAME_MAX_GRAPHEMES, BROKER_NAME_MAX_GRAPHEMES,
                           DECIMAL_INPUT_MAX_INTEGER_DIGITS, MAX_SAFE_QUANTITY,
                           NOTE_MAX_GRAPHEMES, validate_graphemes)

DECIMAL_TEXT_PATTERN = r"^-?[0-9]+(?:\.[0-9]{1,2})?$"
MONEY_TEXT_PATTERN = r"^-?(?:0|[1-9][0-9]*)\.[0-9]{2}$"


def _decimal(value: str) -> str:
    if type(value) is not str or not re.fullmatch(DECIMAL_TEXT_PATTERN, value):
        raise ValueError("Expected decimal text with at most two decimal places")
    raw = value.lstrip("-").split(".")
    integer = raw[0].lstrip("0") or "0"
    if len(integer) > DECIMAL_INPUT_MAX_INTEGER_DIGITS:
        raise ValueError("Decimal input exceeds 18 integer digits")
    fraction = raw[1].ljust(2, "0") if len(raw) > 1 else "00"
    negative = value.startswith("-") and (integer != "0" or fraction != "00")
    return f"{'-' if negative else ''}{integer}.{fraction}"


def _output_decimal(value: str) -> str:
    if type(value) is not str or not re.fullmatch(MONEY_TEXT_PATTERN, value):
        raise ValueError("Expected canonical two-decimal result")
    if value == "-0.00":
        raise ValueError("Negative zero is not a canonical result")
    return value


def decimal_cents(value: str) -> int:
    whole, fractional = value.lstrip("-").split(".")
    result = int(whole) * 100 + int(fractional)
    return -result if value.startswith("-") else result


def _nonnegative(value: str) -> str:
    if decimal_cents(value) < 0:
        raise ValueError("Must be nonnegative")
    return value


def _positive(value: str) -> str:
    if decimal_cents(value) <= 0:
        raise ValueError("Must be positive")
    return value


def _percentage(value: str) -> str:
    if not 0 <= decimal_cents(value) <= 10000:
        raise ValueError("Percentage must be between 0 and 100")
    return value


def _uuid(value: str) -> str:
    if type(value) is not str or not value:
        raise ValueError("Expected UUID text")
    return str(UUID(value))


def _version(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9]+", value):
        raise ValueError("Expected decimal version text")
    significant = value.lstrip("0") or "0"
    if len(significant) > 19 or int(significant) > 9223372036854775807:
        raise ValueError("Version exceeds BIGINT")
    return significant


def _positive_version(value: str) -> str:
    if value == "0":
        raise ValueError("Version starts at one")
    return value


def _date(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Expected YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def _month(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise ValueError("Expected YYYY-MM")
    date.fromisoformat(value + "-01")
    return value


def _instant(value: str) -> str:
    if type(value) is not str or "T" not in value:
        raise ValueError("Expected ISO instant with timezone")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone is required")
    return value


def _deadline(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(hours=8) or parsed.second or parsed.microsecond:
        raise ValueError("Deadline must be a Shanghai minute boundary")
    return value


def _stock(value: str) -> str:
    value = value.strip().upper()
    if not value:
        raise ValueError("Stock code is required")
    return value  # Identity resolution is deliberately not performed by a wire type.


Decimal2Input = Annotated[StrictStr, Field(pattern=DECIMAL_TEXT_PATTERN), BeforeValidator(_decimal)]
NonnegativeInput = Annotated[Decimal2Input, AfterValidator(_nonnegative)]
PositiveInput = Annotated[Decimal2Input, AfterValidator(_positive)]
StampTaxInput = Annotated[Decimal2Input, AfterValidator(_percentage)]
Money = Annotated[StrictStr, Field(pattern=MONEY_TEXT_PATTERN), BeforeValidator(_output_decimal)]
SourceDecimal = Annotated[StrictStr, Field(pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")]
NonnegativeMoney = Annotated[Money, AfterValidator(_nonnegative)]
PositiveMoney = Annotated[Money, AfterValidator(_positive)]
WeightPct = Annotated[NonnegativeMoney, AfterValidator(_percentage)]
ReturnPct = Money
EntityId = Annotated[StrictStr, BeforeValidator(_uuid)]
Version = Annotated[StrictStr, BeforeValidator(_version)]
PositiveVersion = Annotated[Version, AfterValidator(_positive_version)]
Quantity = Annotated[StrictInt, Field(ge=1, le=MAX_SAFE_QUANTITY)]
AvailableQuantity = Annotated[StrictInt, Field(ge=0, le=MAX_SAFE_QUANTITY)]
Count = AvailableQuantity
BusinessDate = Annotated[StrictStr, BeforeValidator(_date)]
Month = Annotated[StrictStr, BeforeValidator(_month)]
Instant = Annotated[StrictStr, BeforeValidator(_instant)]
DeadlineAt = Annotated[Instant, AfterValidator(_deadline)]
StockCode = Annotated[StrictStr, AfterValidator(_stock)]
AccountName = Annotated[StrictStr, AfterValidator(lambda v: validate_graphemes(v, ACCOUNT_NAME_MAX_GRAPHEMES, required=True))]
BrokerName = Annotated[StrictStr, AfterValidator(lambda v: validate_graphemes(v, BROKER_NAME_MAX_GRAPHEMES, required=True))]
Note = Annotated[StrictStr, AfterValidator(lambda v: validate_graphemes(v, NOTE_MAX_GRAPHEMES))]
