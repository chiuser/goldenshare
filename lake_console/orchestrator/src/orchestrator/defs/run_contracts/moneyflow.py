"""Moneyflow market identity, request limits and lossless scalar contract."""

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

MONEYFLOW_MKT_DC_FIELDS = tuple(c.name for c in RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA)
MONEYFLOW_PAGE_SIZE = 2000
MONEYFLOW_STABILITY_SECONDS = 60
MONEYFLOW_REQUEST_TIMEOUT_SECONDS = 30
MONEYFLOW_DUCKDB_MEMORY_LIMIT = "512MB"
MONEYFLOW_DUCKDB_THREADS = 1
MONEYFLOW_MAX_REQUESTS = 64
MONEYFLOW_MAX_ELAPSED_SECONDS = 300


class MoneyflowContractError(ValueError):
    """A source or candidate failed a blocking moneyflow contract."""


def market_moneyflow_day(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise MoneyflowContractError("partition_date")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise MoneyflowContractError("partition_date") from error
    return value


def market_moneyflow_policy() -> TushareRequestPolicy:
    return TushareRequestPolicy(
        minimum_interval_seconds=1,
        max_requests=MONEYFLOW_MAX_REQUESTS,
        max_elapsed_seconds=MONEYFLOW_MAX_ELAPSED_SECONDS,
    )


def normalize_market_moneyflow_row(row, trade_date: str) -> dict:
    """Scalar normalization is bounded to the market endpoint's one row."""
    day = market_moneyflow_day(trade_date).replace("-", "")
    if set(row) != set(MONEYFLOW_MKT_DC_FIELDS):
        raise MoneyflowContractError("source_row_schema")
    if row["trade_date"] != day:
        raise MoneyflowContractError("source_partition_date")
    result = {"trade_date": day}
    for c in RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA[1:]:
        value = row[c.name]
        if value is None:
            result[c.name] = None
            continue
        if isinstance(value, bool) or (
            isinstance(value, float) and abs(value) >= 2**53
        ):
            raise MoneyflowContractError("numeric_type")
        try:
            number = Decimal(str(value))
            precision, scale = map(
                int, c.type.removeprefix("DECIMAL(").removesuffix(")").split(",")
            )
            with localcontext() as context:
                context.prec = 64
                if not number.is_finite() or abs(number) >= Decimal(10) ** (
                    precision - scale
                ):
                    raise MoneyflowContractError("numeric_range")
                if number != number.quantize(Decimal(10) ** -scale):
                    raise MoneyflowContractError("numeric_precision")
                result[c.name] = format(number.quantize(Decimal(10) ** -scale), "f")
        except InvalidOperation as error:
            raise MoneyflowContractError("numeric_type") from error
    return result


def market_moneyflow_row_hash(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
