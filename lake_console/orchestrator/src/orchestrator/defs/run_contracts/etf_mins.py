"""Stable pure contracts for the ETF minute data set."""

from __future__ import annotations

import re
from datetime import date, datetime

ETF_MINS_SOURCE_FREQS = ("1min", "5min", "15min", "30min", "60min")
ETF_MINS_ASSET_FREQS = (1, 5, 15, 30, 60)
ETF_MINS_SENSOR_WINDOW_LIMIT = 10
ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT = 20
ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES = 10_000
ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER = 1.25
ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT = 20
ETF_MINS_HISTORICAL_PROTECTION_CUTOFF = date(2026, 1, 1)
ETF_MINS_SOURCE_COLUMNS = (
    "ts_code",
    "freq",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "vwap",
    "exchange",
)

ETF_MINS_SOURCE_FREQ_BY_ASSET_FREQ = {
    asset_freq: source_freq
    for asset_freq, source_freq in zip(
        ETF_MINS_ASSET_FREQS,
        ETF_MINS_SOURCE_FREQS,
        strict=True,
    )
}
ETF_MINS_ASSET_FREQ_BY_SOURCE_FREQ = {
    source_freq: asset_freq
    for asset_freq, source_freq in ETF_MINS_SOURCE_FREQ_BY_ASSET_FREQ.items()
}
ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX = {
    "SH": "XSHG",
    "SZ": "XSHE",
}

_ISO_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_etf_mins_source_freq(value: object) -> str:
    normalized = str(value).strip().lower()
    if normalized not in ETF_MINS_SOURCE_FREQS:
        allowed = ", ".join(ETF_MINS_SOURCE_FREQS)
        raise ValueError(
            f"ETF minute source frequency must be one of {allowed}; got {value!r}."
        )
    return normalized


def normalize_etf_mins_asset_freq(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(  # noqa: TRY004
            "ETF minute asset frequency must not be boolean."
        )
    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"ETF minute asset frequency is invalid: {value!r}."
        ) from error
    if normalized not in ETF_MINS_ASSET_FREQS:
        allowed = ", ".join(str(freq) for freq in ETF_MINS_ASSET_FREQS)
        raise ValueError(
            f"ETF minute asset frequency must be one of {allowed}; got {value!r}."
        )
    return normalized


def source_freq_for_etf_mins_asset_freq(value: object) -> str:
    return ETF_MINS_SOURCE_FREQ_BY_ASSET_FREQ[normalize_etf_mins_asset_freq(value)]


def asset_freq_for_etf_mins_source_freq(value: object) -> int:
    return ETF_MINS_ASSET_FREQ_BY_SOURCE_FREQ[normalize_etf_mins_source_freq(value)]


def normalize_etf_mins_path_freq(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return source_freq_for_etf_mins_asset_freq(value)
    return normalize_etf_mins_source_freq(value)


def normalize_etf_mins_trade_date(value: object) -> str:
    if isinstance(value, datetime):
        raise ValueError(  # noqa: TRY004
            "ETF minute trade_date must not include a time component."
        )
    if isinstance(value, date):
        return value.isoformat()
    normalized = str(value).strip()
    if not _ISO_TRADE_DATE_RE.fullmatch(normalized):
        raise ValueError("ETF minute trade_date must use YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("ETF minute trade_date must be a valid calendar date.") from error
    return parsed.isoformat()


def expected_etf_mins_source_exchange(ts_code: object) -> str:
    normalized_code = str(ts_code).strip().upper()
    suffix = normalized_code.rsplit(".", 1)[-1] if "." in normalized_code else ""
    try:
        return ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX[suffix]
    except KeyError as error:
        raise ValueError(
            f"ETF minute ts_code must end with .SH or .SZ; got {ts_code!r}."
        ) from error


def raw_etf_mins_check_names(value: object) -> tuple[str, ...]:
    asset_freq = normalize_etf_mins_asset_freq(value)
    asset_name = f"raw_etf_mins_{asset_freq}m"
    return (
        f"{asset_name}_file_contract_check",
        f"{asset_name}_request_scope_check",
        f"{asset_name}_bar_domain_check",
    )


def silver_etf_mins_check_names(value: object) -> tuple[str, ...]:
    asset_freq = normalize_etf_mins_asset_freq(value)
    asset_name = f"silver_etf_mins_{asset_freq}m"
    return (
        f"{asset_name}_file_contract_check",
        f"{asset_name}_raw_equivalence_check",
    )


__all__ = [
    "ETF_MINS_ASSET_FREQS",
    "ETF_MINS_ASSET_FREQ_BY_SOURCE_FREQ",
    "ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT",
    "ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER",
    "ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES",
    "ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT",
    "ETF_MINS_HISTORICAL_PROTECTION_CUTOFF",
    "ETF_MINS_SENSOR_WINDOW_LIMIT",
    "ETF_MINS_SOURCE_COLUMNS",
    "ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX",
    "ETF_MINS_SOURCE_FREQS",
    "ETF_MINS_SOURCE_FREQ_BY_ASSET_FREQ",
    "asset_freq_for_etf_mins_source_freq",
    "expected_etf_mins_source_exchange",
    "normalize_etf_mins_asset_freq",
    "normalize_etf_mins_path_freq",
    "normalize_etf_mins_source_freq",
    "normalize_etf_mins_trade_date",
    "raw_etf_mins_check_names",
    "silver_etf_mins_check_names",
    "source_freq_for_etf_mins_asset_freq",
]
