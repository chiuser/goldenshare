"""Canonical Bar contract and fail-closed sequence validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from .identities import as_decimal, canonical_datetime, stable_hash


SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")


class InputContractError(ValueError):
    """A canonical input contract violation with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


class ContinuityStatus(str, Enum):
    COMPLETE = "COMPLETE"
    KNOWN_SESSION_EXCEPTION = "KNOWN_SESSION_EXCEPTION"
    GAP = "GAP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CanonicalBar:
    ts_code: str
    freq: str
    trade_date: date
    bar_end_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    source_asset_key: str
    source_partition: str
    source_contract_version: str
    data_snapshot_id: str
    vol: Decimal | None = None
    amount: Decimal | None = None

    def __post_init__(self) -> None:
        for field_name in ("open", "high", "low", "close", "vol", "amount"):
            value = getattr(self, field_name)
            if value is not None:
                try:
                    object.__setattr__(self, field_name, as_decimal(value))
                except ValueError as exc:
                    raise InputContractError(
                        "BAR_NON_FINITE_NUMBER", f"{field_name} is invalid"
                    ) from exc

    @property
    def bar_key(self) -> str:
        return stable_hash(
            "bar/v1", self.ts_code, self.freq, canonical_datetime(self.bar_end_at)
        )


def _validate_bar(bar: CanonicalBar) -> None:
    if not bar.ts_code or bar.ts_code != bar.ts_code.upper():
        raise InputContractError("BAR_TS_CODE_INVALID", "ts_code must be uppercase")
    if not bar.freq:
        raise InputContractError("BAR_FREQ_INVALID", "freq must be non-empty")
    if bar.bar_end_at.tzinfo is None or bar.bar_end_at.utcoffset() is None:
        raise InputContractError(
            "BAR_TIMEZONE_INVALID", "bar_end_at must be timezone-aware"
        )
    shanghai_time = bar.bar_end_at.astimezone(SHANGHAI_TIMEZONE)
    if bar.bar_end_at.utcoffset() != shanghai_time.utcoffset():
        raise InputContractError(
            "BAR_TIMEZONE_INVALID",
            "bar_end_at offset must match Asia/Shanghai at that market time",
        )
    if shanghai_time.date() != bar.trade_date:
        raise InputContractError(
            "BAR_TRADE_DATE_MISMATCH", "trade_date must match Shanghai bar date"
        )
    if not all(
        (
            bar.source_asset_key,
            bar.source_partition,
            bar.source_contract_version,
            bar.data_snapshot_id,
        )
    ):
        raise InputContractError(
            "BAR_SOURCE_LINEAGE_MISSING", "source lineage fields are required"
        )
    for field_name in ("open", "high", "low", "close"):
        if getattr(bar, field_name) <= 0:
            raise InputContractError(
                "BAR_PRICE_NON_POSITIVE", f"{field_name} must be positive"
            )
    if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
        raise InputContractError(
            "BAR_OHLC_ENVELOPE_INVALID", "high/low do not envelope open and close"
        )
    if bar.high < bar.low:
        raise InputContractError("BAR_HIGH_BELOW_LOW", "high must not be below low")
    for field_name in ("vol", "amount"):
        value = getattr(bar, field_name)
        if value is not None and value < 0:
            raise InputContractError(
                "BAR_OPTIONAL_VALUE_NEGATIVE", f"{field_name} must be non-negative"
            )


def validate_canonical_bars(
    bars: Iterable[CanonicalBar],
    *,
    as_of: datetime | None = None,
    continuity_status: ContinuityStatus = ContinuityStatus.COMPLETE,
) -> tuple[CanonicalBar, ...]:
    """Validate without sorting, deduplicating, dropping, or clipping bars."""

    materialized = tuple(bars)
    if not materialized:
        raise InputContractError("BAR_SEQUENCE_EMPTY", "at least one bar is required")
    if continuity_status not in {
        ContinuityStatus.COMPLETE,
        ContinuityStatus.KNOWN_SESSION_EXCEPTION,
    }:
        raise InputContractError(
            "BAR_CONTINUITY_NOT_READY",
            f"continuity status {continuity_status.value} is not runnable",
        )
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise InputContractError(
            "AS_OF_TIMEZONE_INVALID", "as_of must be timezone-aware"
        )

    first = materialized[0]
    identity = (
        first.ts_code,
        first.freq,
        first.source_asset_key,
        first.source_contract_version,
        first.data_snapshot_id,
    )
    previous_end: datetime | None = None
    for bar in materialized:
        _validate_bar(bar)
        current_identity = (
            bar.ts_code,
            bar.freq,
            bar.source_asset_key,
            bar.source_contract_version,
            bar.data_snapshot_id,
        )
        if current_identity != identity:
            raise InputContractError(
                "BAR_SEQUENCE_IDENTITY_MIXED",
                "one run may contain only one instrument/frequency/source snapshot",
            )
        if previous_end is not None:
            if bar.bar_end_at == previous_end:
                raise InputContractError(
                    "BAR_SEQUENCE_DUPLICATE", "duplicate bar_end_at detected"
                )
            if bar.bar_end_at < previous_end:
                raise InputContractError(
                    "BAR_SEQUENCE_OUT_OF_ORDER",
                    "bar_end_at must be strictly increasing",
                )
        if as_of is not None and bar.bar_end_at > as_of:
            raise InputContractError(
                "BAR_AFTER_AS_OF", "adapter passed a bar beyond the decision as_of"
            )
        previous_end = bar.bar_end_at
    return materialized


def adapt_canonical_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    ts_code: str,
    freq: str,
    source_asset_key: str,
    source_contract_version: str,
    data_snapshot_id: str,
    as_of: datetime,
    continuity_status: ContinuityStatus,
) -> tuple[CanonicalBar, ...]:
    """Adapt already normalized rows without assuming a dataset or frequency."""

    bars: list[CanonicalBar] = []
    required = {
        "trade_date",
        "bar_end_at",
        "open",
        "high",
        "low",
        "close",
        "source_partition",
    }
    for index, row in enumerate(rows):
        missing = required.difference(row)
        if missing:
            raise InputContractError(
                "BAR_ROW_FIELD_MISSING",
                f"row {index} is missing fields {sorted(missing)}",
            )
        raw_trade_date = row["trade_date"]
        raw_bar_end_at = row["bar_end_at"]
        try:
            trade_date = (
                raw_trade_date
                if isinstance(raw_trade_date, date)
                else date.fromisoformat(str(raw_trade_date))
            )
            bar_end_at = (
                raw_bar_end_at
                if isinstance(raw_bar_end_at, datetime)
                else datetime.fromisoformat(str(raw_bar_end_at))
            )
            bars.append(
                CanonicalBar(
                    ts_code=ts_code,
                    freq=freq,
                    trade_date=trade_date,
                    bar_end_at=bar_end_at,
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    vol=row.get("vol"),
                    amount=row.get("amount"),
                    source_asset_key=source_asset_key,
                    source_partition=str(row["source_partition"]),
                    source_contract_version=source_contract_version,
                    data_snapshot_id=data_snapshot_id,
                )
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, InputContractError):
                raise
            raise InputContractError(
                "BAR_ROW_VALUE_INVALID", f"row {index} cannot be adapted"
            ) from exc
    return validate_canonical_bars(
        bars, as_of=as_of, continuity_status=continuity_status
    )
