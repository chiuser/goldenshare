"""Local copies of the verified price-source contracts for the indicator kernel.

Producer evidence: DG asset_column_schemas.py (daily, factors, canonical minute),
run_contracts/stock_weekly.py and stock_monthly.py (source-preserving periods).
This module describes fields and SQL projection; it performs no I/O or arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.foundation.technical_indicators.contracts import CalculationRequest
from src.foundation.technical_indicators.discovery.catalog import SourceCapability
from src.foundation.technical_indicators.errors import SourceUnsupportedError

from .major_index_mins_contract import MAJOR_INDEX_MINS_GOLD_CODES


MINUTE_PERIODS = ("1m", "5m", "15m", "30m", "60m", "90m", "120m")
VALUE_FIELDS = ("open", "high", "low", "close", "volume", "amount")
MINUTE_SCHEMA = (
    ("ts_code", "VARCHAR"), ("trade_date", "DATE"),
    ("trade_time", "TIMESTAMP"),
    *((name, "DOUBLE") for name in ("open", "high", "low", "close", "vol", "amount")),
)
DAILY_SCHEMA = (
    ("ts_code", "VARCHAR"), ("trade_date", "DATE"),
    *((name, "DOUBLE") for name in ("open", "high", "low", "close", "vol", "amount")),
)
PERIOD_SCHEMA = (
    ("ts_code", "VARCHAR"), ("trade_date", "VARCHAR"), ("end_date", "VARCHAR"),
    *((name + suffix, "DECIMAL(18,4)")
      for suffix in ("", "_qfq", "_hfq") for name in ("open", "high", "low", "close")),
    ("vol", "DECIMAL(20,4)"), ("amount", "DECIMAL(20,4)"),
)
FACTOR_SCHEMA = (("ts_code", "VARCHAR"), ("trade_date", "DATE"), ("adj_factor", "DOUBLE"))


@dataclass(frozen=True, slots=True)
class LakePriceContract:
    source_id: str
    relative_root: str
    schema: tuple[tuple[str, str], ...]
    input_adjustment: str
    adjustment_paths: tuple[tuple[str, str], ...]
    volume_unit: str
    amount_unit: str
    period_kind: str


def price_contract(request: CalculationRequest) -> LakePriceContract:
    """Reject unsupported combinations before any filesystem access."""
    if request.period in MINUTE_PERIODS:
        if request.security_type == "index":
            if request.ts_code not in MAJOR_INDEX_MINS_GOLD_CODES or request.adjustment != "none":
                raise SourceUnsupportedError("The declared index-minute source supports explicit none only")
            return LakePriceContract("lake_major_index_minutes", "gold/quote/major_index_mins", MINUTE_SCHEMA,
                                     "none", (("none", "none"),), "share", "CNY", "minute")
        if request.adjustment != "qfq":
            raise SourceUnsupportedError("The declared stock-minute source supplies qfq only")
        return LakePriceContract("lake_stock_minutes_qfq", "gold/quote/stk_mins_qfq", MINUTE_SCHEMA,
                                 "qfq", (("qfq", "qfq"),), "share", "CNY", "minute")
    if request.security_type != "stock":
        raise SourceUnsupportedError("Index daily, weekly and monthly sources are not assembled")
    if request.period == "day":
        return LakePriceContract("lake_stock_daily", "silver/quote/stock_daily", DAILY_SCHEMA,
                                 "none", (("none", "none"), ("none", "qfq"), ("none", "hfq")),
                                 "lot", "thousand_CNY", "day")
    if request.period in ("week", "month"):
        relative = "silver/quote/stock_weekly" if request.period == "week" else "silver/quote/stock_monthly"
        return LakePriceContract("lake_stock_" + request.period, relative, PERIOD_SCHEMA,
                                 request.adjustment, ((request.adjustment, request.adjustment),),
                                 "lot", "thousand_CNY", request.period)
    raise SourceUnsupportedError("The requested source combination is not declared")


def source_projection(contract: LakePriceContract, fields: frozenset[str], adjustment: str):
    """Return physical names and the built-in b-only SQL expressions.

    The filter columns remain in the physical projection, so their row-group
    decoding cost is included even when the caller requests only MACD close.
    """
    if not fields <= frozenset(VALUE_FIELDS):
        raise SourceUnsupportedError("The source cannot supply the requested fields")
    if contract.period_kind == "minute":
        physical = ["ts_code", "trade_date", "trade_time"]
        standard = [("trade_date", 'CAST(b."trade_date" AS DATE)'),
                    ("trade_time", 'CAST(b."trade_time" AS TIMESTAMP)')]
    else:
        periodic = contract.period_kind in ("week", "month")
        physical = ["ts_code", "trade_date"] + (["end_date"] if periodic else [])
        day = 'CAST(strptime(b."trade_date", \'%Y%m%d\') AS DATE)' if periodic else 'CAST(b."trade_date" AS DATE)'
        if contract.period_kind == "week":
            start = f"CAST(date_trunc('week', {day}) AS DATE)"
            end = f"CAST({start} + INTERVAL 4 DAY AS DATE)"
        elif contract.period_kind == "month":
            start = f"CAST(date_trunc('month', {day}) AS DATE)"
            end = f"CAST({start} + INTERVAL 1 MONTH - INTERVAL 1 DAY AS DATE)"
        else:
            start = end = day
        as_of = 'CAST(strptime(b."end_date", \'%Y%m%d\') AS DATE)' if periodic else day
        standard = [("trade_date", day), ("period_start", start), ("period_end", end), ("source_as_of", as_of)]
    suffix = "_" + adjustment if contract.period_kind in ("week", "month") and adjustment != "none" else ""
    for field in VALUE_FIELDS:
        if field not in fields:
            continue
        name = "vol" if field == "volume" else field
        if field in ("open", "high", "low", "close"):
            name += suffix
        physical.append(name)
        standard.append((field, f'CAST(b."{name}" AS DOUBLE)'))
    return tuple(physical), tuple(standard)


def source_capabilities() -> tuple[SourceCapability, ...]:
    """Static support only; this does not check today's files or data quality."""
    return tuple(
        [SourceCapability("index", period, "none", "lake_major_index_minutes") for period in MINUTE_PERIODS]
        + [SourceCapability("stock", period, "qfq", "lake_stock_minutes_qfq") for period in MINUTE_PERIODS]
        + [SourceCapability("stock", period, adjustment, "lake_stock_" + ("daily" if period == "day" else period))
           for period in ("day", "week", "month") for adjustment in ("none", "qfq", "hfq")]
    )
