"""Stable contracts for the index minute data set."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
import hashlib
import re

from orchestrator.defs.run_contracts.configs import normalize_iso_trade_date
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    DerivedMinuteWindow,
    cn_a_derived_minute_windows,
)


INDEX_MINS_HISTORY_START_DATE = "2025-01-02"
INDEX_MINS_SOURCE_FREQS = ("1min", "5min", "15min", "30min", "60min")
INDEX_MINS_ASSET_FREQS = (1, 5, 15, 30, 60)
INDEX_MINS_DERIVED_FREQS = (90, 120)
INDEX_MINS_SILVER_FREQS = INDEX_MINS_ASSET_FREQS + INDEX_MINS_DERIVED_FREQS
INDEX_MINS_FALLBACK_FREQS = (15, 30, 60)
INDEX_MINS_FALLBACK_SOURCE_FREQ = "5min"
INDEX_MINS_FALLBACK_SOURCE_TIMES = (
    "09:30:00",
    "09:35:00",
    "09:40:00",
    "09:45:00",
    "09:50:00",
    "09:55:00",
    "10:00:00",
    "10:05:00",
    "10:10:00",
    "10:15:00",
    "10:20:00",
    "10:25:00",
    "10:30:00",
    "10:35:00",
    "10:40:00",
    "10:45:00",
    "10:50:00",
    "10:55:00",
    "11:00:00",
    "11:05:00",
    "11:10:00",
    "11:15:00",
    "11:20:00",
    "11:25:00",
    "11:30:00",
    "13:05:00",
    "13:10:00",
    "13:15:00",
    "13:20:00",
    "13:25:00",
    "13:30:00",
    "13:35:00",
    "13:40:00",
    "13:45:00",
    "13:50:00",
    "13:55:00",
    "14:00:00",
    "14:05:00",
    "14:10:00",
    "14:15:00",
    "14:20:00",
    "14:25:00",
    "14:30:00",
    "14:35:00",
    "14:40:00",
    "14:45:00",
    "14:50:00",
    "14:55:00",
    "15:00:00",
)
INDEX_MINS_SENSOR_WINDOW_LIMIT = 10
INDEX_MINS_BOOTSTRAP_BATCH_SIZE = 20
INDEX_MINS_BOOTSTRAP_MAX_EXPECTED_DATES = 800
INDEX_MINS_BOOTSTRAP_MAX_SOURCE_PROBE_QUERIES = 4_000
INDEX_MINS_BOOTSTRAP_MAX_SOURCE_PROBE_MS = 300_000
INDEX_MINS_BOOTSTRAP_MAX_TARGET_FILES = 9_600
INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER = 1.25
INDEX_MINS_SOURCE_PAGE_LIMIT = 8_000
INDEX_MINS_ACTIVE_POOL_RESOURCE = "index_mins"
INDEX_MINS_ACTIVE_POOL_MAX_CODES = 2_000
INDEX_MINS_ACTIVE_POOL_FETCH_SIZE = 500

INDEX_MINS_SOURCE_COLUMNS = (
    "ts_code",
    "freq",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "exchange",
    "vwap",
)

INDEX_MINS_SOURCE_FREQ_BY_ASSET_FREQ = {
    asset_freq: source_freq
    for asset_freq, source_freq in zip(
        INDEX_MINS_ASSET_FREQS,
        INDEX_MINS_SOURCE_FREQS,
        strict=True,
    )
}
INDEX_MINS_ASSET_FREQ_BY_SOURCE_FREQ = {
    source_freq: asset_freq
    for asset_freq, source_freq in INDEX_MINS_SOURCE_FREQ_BY_ASSET_FREQ.items()
}
INDEX_MINS_DERIVED_SOURCE_FREQ_BY_FREQ = {
    90: "30min",
    120: "60min",
}
INDEX_MINS_FALLBACK_TARGET_TIMES = {
    15: (
        "09:30:00",
        "09:45:00",
        "10:00:00",
        "10:15:00",
        "10:30:00",
        "10:45:00",
        "11:00:00",
        "11:15:00",
        "11:30:00",
        "13:15:00",
        "13:30:00",
        "13:45:00",
        "14:00:00",
        "14:15:00",
        "14:30:00",
        "14:45:00",
        "15:00:00",
    ),
    30: (
        "09:30:00",
        "10:00:00",
        "10:30:00",
        "11:00:00",
        "11:30:00",
        "13:30:00",
        "14:00:00",
        "14:30:00",
        "15:00:00",
    ),
    60: ("09:30:00", "10:30:00", "11:30:00", "14:00:00", "15:00:00"),
}
INDEX_MINS_RAW_ASSET_NAMES = tuple(
    f"raw_index_mins_{frequency}m" for frequency in INDEX_MINS_ASSET_FREQS
)
INDEX_MINS_SILVER_ASSET_NAMES = tuple(
    f"silver_index_mins_{frequency}m" for frequency in INDEX_MINS_SILVER_FREQS
)
INDEX_MINS_RAW_CHECKS = tuple(
    f"{asset_name}_core_check" for asset_name in INDEX_MINS_RAW_ASSET_NAMES
)
INDEX_MINS_SILVER_CHECKS = tuple(
    f"{asset_name}_core_check" for asset_name in INDEX_MINS_SILVER_ASSET_NAMES
)
_INDEX_MINS_CODE_RE = re.compile(r"^[0-9A-Z]{1,12}\.[A-Z0-9]{2,8}$")


def normalize_index_mins_source_freq(value: object) -> str:
    normalized = str(value).strip().lower()
    if normalized not in INDEX_MINS_SOURCE_FREQS:
        allowed = ", ".join(INDEX_MINS_SOURCE_FREQS)
        raise ValueError(
            f"index_mins source frequency must be one of {allowed}; got {value!r}."
        )
    return normalized


def normalize_index_mins_asset_freq(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("index_mins asset frequency must not be boolean.")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"index_mins asset frequency is invalid: {value!r}."
        ) from error
    if normalized not in INDEX_MINS_ASSET_FREQS:
        allowed = ", ".join(str(freq) for freq in INDEX_MINS_ASSET_FREQS)
        raise ValueError(
            f"index_mins asset frequency must be one of {allowed}; got {value!r}."
        )
    return normalized


def normalize_index_mins_silver_freq(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("index_mins Silver frequency must not be boolean.")
    normalized = str(value).strip().lower()
    if normalized.endswith("min"):
        numeric = normalized[:-3]
    else:
        numeric = normalized
    try:
        frequency = int(numeric)
    except ValueError as error:
        raise ValueError(
            f"index_mins Silver frequency is invalid: {value!r}."
        ) from error
    if frequency not in INDEX_MINS_SILVER_FREQS:
        allowed = ", ".join(f"{freq}min" for freq in INDEX_MINS_SILVER_FREQS)
        raise ValueError(
            f"index_mins Silver frequency must be one of {allowed}; got {value!r}."
        )
    return f"{frequency}min"


def source_freq_for_index_mins_asset_freq(value: object) -> str:
    return INDEX_MINS_SOURCE_FREQ_BY_ASSET_FREQ[normalize_index_mins_asset_freq(value)]


def source_freq_for_index_mins_derived_freq(value: object) -> str:
    normalized = normalize_index_mins_silver_freq(value)
    frequency = int(normalized[:-3])
    try:
        return INDEX_MINS_DERIVED_SOURCE_FREQ_BY_FREQ[frequency]
    except KeyError as error:
        raise ValueError(f"index_mins frequency is not derived: {value!r}.") from error


def fallback_target_times_for_index_mins_freq(value: object) -> tuple[str, ...]:
    normalized = normalize_index_mins_silver_freq(value)
    frequency = int(normalized[:-3])
    try:
        return INDEX_MINS_FALLBACK_TARGET_TIMES[frequency]
    except KeyError as error:
        raise ValueError(
            f"index_mins frequency is not a 5min fallback target: {value!r}."
        ) from error


def fallback_source_times_for_index_mins() -> tuple[str, ...]:
    return INDEX_MINS_FALLBACK_SOURCE_TIMES


def index_mins_derived_windows(value: object) -> tuple[DerivedMinuteWindow, ...]:
    normalized = normalize_index_mins_silver_freq(value)
    frequency = int(normalized[:-3])
    try:
        return cn_a_derived_minute_windows(frequency)
    except ValueError as error:
        raise ValueError(f"index_mins frequency is not derived: {value!r}.") from error


def asset_freq_for_index_mins_source_freq(value: object) -> int:
    return INDEX_MINS_ASSET_FREQ_BY_SOURCE_FREQ[normalize_index_mins_source_freq(value)]


def normalize_index_mins_code(value: object) -> str:
    normalized = str(value).strip().upper()
    if not normalized or not _INDEX_MINS_CODE_RE.fullmatch(normalized):
        raise ValueError(f"index_mins code is invalid: {value!r}.")
    return normalized


def normalize_index_mins_codes(
    values: Sequence[object],
    *,
    reject_duplicates: bool = False,
) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = normalize_index_mins_code(value)
        if code in seen:
            if reject_duplicates:
                raise ValueError(f"index_mins code is duplicated: {code}.")
            continue
        seen.add(code)
        normalized.append(code)
    if not normalized:
        raise ValueError("index_mins code collection must not be empty.")
    return tuple(normalized)


def index_mins_code_set_hash(values: Sequence[object]) -> str:
    codes = tuple(sorted(normalize_index_mins_codes(values)))
    return hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()


def index_mins_trade_date_window(trade_date: str) -> tuple[datetime, datetime]:
    normalized = normalize_iso_trade_date(trade_date, field_name="trade_date")
    start_date = date.fromisoformat(normalized)
    end_date = start_date + timedelta(days=1)
    return (
        datetime.combine(start_date, time.min),
        datetime.combine(end_date, time.min),
    )


def normalize_index_mins_datetime(value: object, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip())
        except ValueError as error:
            raise ValueError(f"{field_name} must be an ISO datetime.") from error
    if parsed.tzinfo is not None:
        raise ValueError(f"{field_name} must be timezone-naive for Prod timestamps.")
    return parsed
