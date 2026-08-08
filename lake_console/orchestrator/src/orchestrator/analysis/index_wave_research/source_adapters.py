"""Versioned, read-only Lake source adapters for index-wave research."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time
from typing import Final

from ..index_wave.bars import (
    SHANGHAI_TIMEZONE,
    CanonicalBar,
    ContinuityStatus,
    InputContractError,
    adapt_canonical_rows,
)


INDEX_DAILY_SOURCE_CONTRACT_VERSION: Final = "SILVER_INDEX_DAILY_CANONICAL_V1"
MAJOR_INDEX_120M_SOURCE_CONTRACT_VERSION: Final = (
    "SILVER_MAJOR_INDEX_MINS_120M_CANONICAL_V1"
)
INDEX_DAILY_SOURCE_ASSET_KEY: Final = "silver_index_daily"
MAJOR_INDEX_120M_SOURCE_ASSET_KEY: Final = "silver_major_index_mins_120m"
INDEX_DAILY_FREQ: Final = "1d"
MAJOR_INDEX_120M_FREQ: Final = "120min"
EXPECTED_120M_END_TIMES: Final = (time(11, 30), time(15, 0))


def _as_date(value: object, *, row_index: int) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise InputContractError(
            "SOURCE_TRADE_DATE_INVALID", f"row {row_index} has invalid trade_date"
        ) from exc


def _require_identity(
    row: Mapping[str, object],
    *,
    row_index: int,
    ts_code: str,
    expected_freq: str | None = None,
) -> None:
    if str(row.get("ts_code", "")) != ts_code:
        raise InputContractError(
            "SOURCE_TS_CODE_MISMATCH",
            f"row {row_index} does not belong to {ts_code}",
        )
    if expected_freq is not None and str(row.get("freq", "")) != expected_freq:
        raise InputContractError(
            "SOURCE_FREQ_MISMATCH",
            f"row {row_index} does not belong to {expected_freq}",
        )


def _require_prices(row: Mapping[str, object], *, row_index: int) -> None:
    missing = tuple(
        field_name
        for field_name in ("open", "high", "low", "close")
        if row.get(field_name) is None
    )
    if missing:
        raise InputContractError(
            "SOURCE_PRICE_FIELD_MISSING",
            f"row {row_index} is missing required prices {missing}",
        )


def _validate_expected_dates(
    observed_dates: Sequence[date], expected_trade_dates: Sequence[date] | None
) -> None:
    if expected_trade_dates is None:
        return
    expected = tuple(expected_trade_dates)
    if tuple(observed_dates) != expected:
        raise InputContractError(
            "SOURCE_TRADE_DATE_COVERAGE_MISMATCH",
            "observed trade dates do not exactly match the expected open-date sequence",
        )


def adapt_index_daily_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    ts_code: str,
    data_snapshot_id: str,
    as_of: datetime,
    expected_trade_dates: Sequence[date] | None = None,
    continuity_status: ContinuityStatus = ContinuityStatus.COMPLETE,
) -> tuple[CanonicalBar, ...]:
    """Adapt ordered silver index-daily rows without sorting or repairing them."""

    normalized: list[dict[str, object]] = []
    observed_dates: list[date] = []
    for row_index, row in enumerate(rows):
        _require_identity(row, row_index=row_index, ts_code=ts_code)
        _require_prices(row, row_index=row_index)
        trade_date = _as_date(row.get("trade_date"), row_index=row_index)
        observed_dates.append(trade_date)
        normalized.append(
            {
                "trade_date": trade_date,
                "bar_end_at": datetime.combine(
                    trade_date, time(15, 0), tzinfo=SHANGHAI_TIMEZONE
                ),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "vol": row.get("vol"),
                "amount": row.get("amount"),
                "source_partition": f"trade_date={trade_date.isoformat()}",
            }
        )
    _validate_expected_dates(observed_dates, expected_trade_dates)
    return adapt_canonical_rows(
        normalized,
        ts_code=ts_code,
        freq=INDEX_DAILY_FREQ,
        source_asset_key=INDEX_DAILY_SOURCE_ASSET_KEY,
        source_contract_version=INDEX_DAILY_SOURCE_CONTRACT_VERSION,
        data_snapshot_id=data_snapshot_id,
        as_of=as_of,
        continuity_status=continuity_status,
    )


def _as_shanghai_trade_time(value: object, *, row_index: int) -> datetime:
    try:
        trade_time = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except ValueError as exc:
        raise InputContractError(
            "SOURCE_TRADE_TIME_INVALID", f"row {row_index} has invalid trade_time"
        ) from exc
    if trade_time.tzinfo is None or trade_time.utcoffset() is None:
        return trade_time.replace(tzinfo=SHANGHAI_TIMEZONE)
    shanghai_time = trade_time.astimezone(SHANGHAI_TIMEZONE)
    if trade_time.utcoffset() != shanghai_time.utcoffset():
        raise InputContractError(
            "SOURCE_TRADE_TIME_TIMEZONE_INVALID",
            f"row {row_index} trade_time is not Asia/Shanghai",
        )
    return shanghai_time


def adapt_major_index_120m_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    ts_code: str,
    data_snapshot_id: str,
    as_of: datetime,
    expected_trade_dates: Sequence[date] | None = None,
    continuity_status: ContinuityStatus = ContinuityStatus.COMPLETE,
) -> tuple[CanonicalBar, ...]:
    """Adapt ordered 120-minute rows and fail closed on session-bar coverage."""

    normalized: list[dict[str, object]] = []
    observed_keys: list[tuple[date, time]] = []
    for row_index, row in enumerate(rows):
        _require_identity(
            row,
            row_index=row_index,
            ts_code=ts_code,
            expected_freq=MAJOR_INDEX_120M_FREQ,
        )
        _require_prices(row, row_index=row_index)
        trade_time = _as_shanghai_trade_time(row.get("trade_time"), row_index=row_index)
        if trade_time.time().replace(tzinfo=None) not in EXPECTED_120M_END_TIMES:
            raise InputContractError(
                "SOURCE_120M_SESSION_TIME_INVALID",
                f"row {row_index} is not an 11:30 or 15:00 closed bar",
            )
        trade_date = trade_time.date()
        observed_keys.append((trade_date, trade_time.time().replace(tzinfo=None)))
        normalized.append(
            {
                "trade_date": trade_date,
                "bar_end_at": trade_time,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "vol": row.get("vol"),
                "amount": row.get("amount"),
                "source_partition": f"freq=120min/trade_date={trade_date.isoformat()}",
            }
        )
    if expected_trade_dates is not None:
        expected_keys = tuple(
            (trade_date, bar_end_time)
            for trade_date in expected_trade_dates
            for bar_end_time in EXPECTED_120M_END_TIMES
        )
        if tuple(observed_keys) != expected_keys:
            raise InputContractError(
                "SOURCE_120M_COVERAGE_MISMATCH",
                "120-minute rows do not exactly contain 11:30 and 15:00 for every expected date",
            )
    return adapt_canonical_rows(
        normalized,
        ts_code=ts_code,
        freq=MAJOR_INDEX_120M_FREQ,
        source_asset_key=MAJOR_INDEX_120M_SOURCE_ASSET_KEY,
        source_contract_version=MAJOR_INDEX_120M_SOURCE_CONTRACT_VERSION,
        data_snapshot_id=data_snapshot_id,
        as_of=as_of,
        continuity_status=continuity_status,
    )
