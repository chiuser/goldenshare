"""Stable contracts for the Tushare international index daily dataset."""

from collections.abc import Mapping, Sequence
from datetime import date
import math
import re
import dagster as dg
from pydantic import Field

from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


INDEX_GLOBAL_FIELDS = tuple(column.name for column in RAW_INDEX_GLOBAL_SCHEMA)
INDEX_GLOBAL_COLUMN_TYPES = {
    column.name: column.type for column in RAW_INDEX_GLOBAL_SCHEMA
}
SILVER_INDEX_GLOBAL_FIELDS = tuple(
    column.name for column in SILVER_INDEX_GLOBAL_SCHEMA
)
SILVER_INDEX_GLOBAL_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_INDEX_GLOBAL_SCHEMA
}

INDEX_GLOBAL_EXPECTED_CODES = (
    "XIN9",
    "HSI",
    "HKTECH",
    "HKAH",
    "DJI",
    "SPX",
    "IXIC",
    "FTSE",
    "FCHI",
    "GDAXI",
    "N225",
    "KS11",
    "AS51",
    "SENSEX",
    "IBOVESPA",
    "RTS",
    "TWII",
    "CKLSE",
    "SPTSX",
    "CSX5P",
    "RUT",
)

INDEX_GLOBAL_PHASES = (
    "asia_1",
    "asia_2",
    "asia_3",
    "europe",
    "americas",
    "late_empty",
)
INDEX_GLOBAL_NORMAL_PHASES = INDEX_GLOBAL_PHASES[:5]

INDEX_GLOBAL_REQUEST_LIMIT = 4000
INDEX_GLOBAL_MAX_PHASE_ROWS = len(INDEX_GLOBAL_EXPECTED_CODES)
INDEX_GLOBAL_MAX_REQUESTS = 20
INDEX_GLOBAL_MAX_ELAPSED_SECONDS = 60.0
INDEX_GLOBAL_MIN_REQUEST_INTERVAL_SECONDS = 0.13
INDEX_GLOBAL_MAX_RETRIES = 3
INDEX_GLOBAL_BACKOFF_BASE_SECONDS = 1.0
INDEX_GLOBAL_MAX_BACKOFF_SECONDS = 8.0
INDEX_GLOBAL_RAW_CHECKS = ("raw_index_global_core_check",)
INDEX_GLOBAL_SILVER_CHECKS = ("silver_index_global_core_check",)
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RAW_DATE_PATTERN = re.compile(r"^\d{8}$")


class IndexGlobalRawConfig(dg.Config):
    """Typed config for one natural-date/phase Raw execution unit."""

    trade_date: str = Field(description="目标自然日，格式 YYYY-MM-DD。")
    probe_phase: str = Field(description="本次源站探测阶段。")
    slot_key: str = Field(description="稳定 phase slot 标识，不从 run key 反解析。")
    attempt: int = Field(default=0, ge=0, description="普通 phase 的重试序号。")
    late_empty_attempt: int = Field(
        default=0,
        ge=0,
        description="late-empty 探测序号；普通 phase 固定为 0。",
    )


def build_index_global_request_policy() -> TushareRequestPolicy:
    """Build the bounded policy for one date/phase request."""

    return TushareRequestPolicy(
        minimum_interval_seconds=INDEX_GLOBAL_MIN_REQUEST_INTERVAL_SECONDS,
        max_retries=INDEX_GLOBAL_MAX_RETRIES,
        backoff_base_seconds=INDEX_GLOBAL_BACKOFF_BASE_SECONDS,
        max_backoff_seconds=INDEX_GLOBAL_MAX_BACKOFF_SECONDS,
        max_requests=INDEX_GLOBAL_MAX_REQUESTS,
        max_elapsed_seconds=INDEX_GLOBAL_MAX_ELAPSED_SECONDS,
    )


def validate_index_global_raw_config(
    config: IndexGlobalRawConfig,
    *,
    partition_key: str,
) -> str:
    """Validate that typed config and the Dagster partition identify one unit."""

    normalized_partition_key = normalize_index_global_trade_date(partition_key)
    configured_trade_date = normalize_index_global_trade_date(config.trade_date)
    if configured_trade_date != normalized_partition_key:
        raise IndexGlobalRawValidationError(
            "index_global config trade_date does not match Dagster partition: "
            f"config={configured_trade_date}, partition={normalized_partition_key}"
        )
    if not config.slot_key.strip():
        raise IndexGlobalRawValidationError("index_global config slot_key is empty")
    if config.probe_phase not in INDEX_GLOBAL_PHASES:
        raise IndexGlobalRawValidationError(
            f"index_global probe_phase is unsupported: {config.probe_phase!r}"
        )
    if config.probe_phase == "late_empty" and config.late_empty_attempt < 1:
        raise IndexGlobalRawValidationError(
            "late_empty probe requires a positive late_empty_attempt"
        )
    if config.probe_phase != "late_empty" and config.late_empty_attempt != 0:
        raise IndexGlobalRawValidationError(
            "normal phase must use late_empty_attempt=0"
        )
    return normalized_partition_key


class IndexGlobalRawValidationError(ValueError):
    """Raised when a phase result cannot enter the Raw merge."""


def normalize_index_global_trade_date(value: str | date) -> str:
    """Return the physical partition date in ISO format."""

    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if _RAW_DATE_PATTERN.fullmatch(text):
        return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
    if not _ISO_DATE_PATTERN.fullmatch(text):
        raise IndexGlobalRawValidationError(
            f"index_global trade_date must be YYYY-MM-DD or YYYYMMDD: {value!r}"
        )
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise IndexGlobalRawValidationError(
            f"index_global trade_date is not a valid calendar date: {value!r}"
        ) from exc


def _raw_trade_date(value: object, *, target_trade_date: str) -> str:
    if value is None:
        raise IndexGlobalRawValidationError("index_global phase row trade_date is null")
    try:
        normalized = normalize_index_global_trade_date(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise IndexGlobalRawValidationError(
            f"index_global phase row trade_date is invalid: {value!r}"
        ) from exc
    if normalized != target_trade_date:
        raise IndexGlobalRawValidationError(
            f"index_global phase row trade_date {normalized} does not match {target_trade_date}"
        )
    return target_trade_date.replace("-", "")


def validate_index_global_phase_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    trade_date: str | date,
    probe_phase: str,
) -> tuple[dict[str, object], ...]:
    """Validate and normalize one bounded Tushare phase result.

    The API is expected to return at most the fixed identity set. Keeping this
    bound here makes the later DuckDB load bounded and prevents an accidental
    broad-history response from becoming a large Python-side write.
    """

    normalized_trade_date = normalize_index_global_trade_date(trade_date)
    if probe_phase not in INDEX_GLOBAL_PHASES:
        raise IndexGlobalRawValidationError(
            f"index_global probe_phase is unsupported: {probe_phase!r}"
        )
    if len(rows) > INDEX_GLOBAL_MAX_PHASE_ROWS:
        raise IndexGlobalRawValidationError(
            "index_global phase row count exceeds the fixed identity bound"
        )

    expected_columns = set(INDEX_GLOBAL_FIELDS)
    allowed_codes = set(INDEX_GLOBAL_EXPECTED_CODES)
    seen_keys: set[tuple[str, str]] = set()
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        observed_columns = set(row)
        if observed_columns != expected_columns:
            missing = sorted(expected_columns - observed_columns)
            extra = sorted(observed_columns - expected_columns)
            raise IndexGlobalRawValidationError(
                f"index_global phase columns do not match contract; missing={missing}, extra={extra}"
            )
        code = str(row["ts_code"] or "").strip()
        if not code or code not in allowed_codes:
            raise IndexGlobalRawValidationError(
                f"index_global phase ts_code is not in the fixed identity set: {code!r}"
            )
        source_trade_date = _raw_trade_date(
            row["trade_date"], target_trade_date=normalized_trade_date
        )
        key = (code, source_trade_date)
        if key in seen_keys:
            raise IndexGlobalRawValidationError(
                f"index_global phase contains duplicate business key: {key!r}"
            )
        seen_keys.add(key)
        normalized_row = dict(row)
        normalized_row["ts_code"] = code
        normalized_row["trade_date"] = source_trade_date
        normalized_rows.append(normalized_row)
    return tuple(normalized_rows)


def normalize_index_global_numeric_values(row: Mapping[str, object]) -> dict[str, object]:
    """Normalize source NaN nulls and reject invalid numeric values."""

    normalized = dict(row)
    for field in INDEX_GLOBAL_FIELDS[2:]:
        value = row[field]
        if value is None:
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise IndexGlobalRawValidationError(
                f"index_global numeric field {field!r} is not numeric"
            ) from exc
        if math.isnan(numeric_value):
            normalized[field] = None
        elif not math.isfinite(numeric_value):
            raise IndexGlobalRawValidationError(
                f"index_global numeric field {field!r} is not finite"
            )
    return normalized


def validate_index_global_numeric_values(row: Mapping[str, object]) -> None:
    """Validate numeric values without changing the input mapping."""

    normalize_index_global_numeric_values(row)
