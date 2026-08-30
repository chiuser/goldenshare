"""Stable pure contracts for ETF Basic lake snapshots."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import dagster as dg
from pydantic import ConfigDict, Field

ETF_BASIC_SOURCE_API = "etf_basic"
ETF_BASIC_PAGE_LIMIT = 5_000
ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT = 20
ETF_BASIC_LIST_STATUSES = ("D", "L", "P")
ETF_BASIC_CODE_SUFFIXES = ("OF", "SH", "SZ")
ETF_BASIC_SILVER_SUFFIXES = ("SH", "SZ")

ETF_BASIC_SOURCE_COLUMNS = (
    "ts_code",
    "csname",
    "extname",
    "cname",
    "index_code",
    "index_name",
    "setup_date",
    "list_date",
    "list_status",
    "exchange",
    "mgr_name",
    "custod_name",
    "mgt_fee",
    "etf_type",
)

RAW_ETF_BASIC_CHECKS = (
    "raw_tushare_etf_basic_source_contract_check",
    "raw_tushare_etf_basic_key_domain_check",
    "raw_tushare_etf_basic_content_hash_check",
)
SILVER_ETF_BASIC_CHECKS = (
    "silver_etf_basic_source_filter_check",
    "silver_etf_basic_key_domain_check",
    "silver_etf_basic_content_hash_check",
)

ETF_BASIC_REQUESTABILITY_NON_EXCHANGE_SUFFIX = "NON_EXCHANGE_SUFFIX"
ETF_BASIC_REQUESTABILITY_EXCHANGE_MISMATCH = "EXCHANGE_MISMATCH"
ETF_BASIC_REQUESTABILITY_STATUS_NOT_LISTED = "STATUS_NOT_LISTED"
ETF_BASIC_REQUESTABILITY_LIST_DATE_NULL = "LIST_DATE_NULL"
ETF_BASIC_REQUESTABILITY_LIST_DATE_AFTER_AS_OF = "LIST_DATE_AFTER_AS_OF"

_ETF_BASIC_STRING_COLUMNS = tuple(
    column for column in ETF_BASIC_SOURCE_COLUMNS if column != "mgt_fee"
)


class EtfBasicRawSnapshotReference(dg.Config):
    """Immutable Raw snapshot identity frozen into one Silver run config."""

    model_config = ConfigDict(frozen=True)

    raw_snapshot_hash: str = Field(description="DG Raw 快照内容 SHA-256。")
    raw_uri: str = Field(description="冻结 Raw Parquet 的绝对路径。")
    raw_observed_at: str = Field(description="Raw 源请求的带时区观测时间。")
    reference_fingerprint: str = Field(description="本引用稳定内容的 SHA-256。")

    def validate_contract(self) -> EtfBasicRawSnapshotReference:
        raw_snapshot_hash = _normalize_sha256(
            self.raw_snapshot_hash,
            field_name="raw_snapshot_hash",
        )
        raw_uri = _normalize_non_empty_string(self.raw_uri, field_name="raw_uri")
        raw_observed_at = _normalize_timezone_datetime(
            self.raw_observed_at,
            field_name="raw_observed_at",
        )
        reference_fingerprint = _normalize_sha256(
            self.reference_fingerprint,
            field_name="reference_fingerprint",
        )
        expected = _etf_basic_reference_fingerprint(
            {
                "raw_snapshot_hash": raw_snapshot_hash,
                "raw_uri": raw_uri,
                "raw_observed_at": raw_observed_at,
            }
        )
        if reference_fingerprint != expected:
            raise ValueError("ETF Basic Raw reference_fingerprint is invalid.")
        return self


class EtfBasicSilverSnapshotReference(dg.Config):
    """Immutable latest-only Basic identity frozen into minute work."""

    model_config = ConfigDict(frozen=True)

    raw_snapshot_hash: str
    silver_content_hash: str
    raw_uri: str
    silver_uri: str
    raw_observed_at: str
    silver_observed_at: str
    eligibility_as_of: str
    requestable_code_count: int
    requestable_code_hash: str
    reference_fingerprint: str

    def validate_contract(self) -> EtfBasicSilverSnapshotReference:
        payload = _normalize_etf_basic_silver_reference_payload(
            raw_snapshot_hash=self.raw_snapshot_hash,
            silver_content_hash=self.silver_content_hash,
            raw_uri=self.raw_uri,
            silver_uri=self.silver_uri,
            raw_observed_at=self.raw_observed_at,
            silver_observed_at=self.silver_observed_at,
            eligibility_as_of=self.eligibility_as_of,
            requestable_code_count=self.requestable_code_count,
            requestable_code_hash=self.requestable_code_hash,
        )
        reference_fingerprint = _normalize_sha256(
            self.reference_fingerprint,
            field_name="reference_fingerprint",
        )
        if reference_fingerprint != _etf_basic_reference_fingerprint(payload):
            raise ValueError("ETF Basic Silver reference_fingerprint is invalid.")
        return self


class EtfBasicSilverConfig(dg.Config):
    """Only the frozen Raw identity is configurable for Basic Silver."""

    raw_snapshot_reference: EtfBasicRawSnapshotReference


def build_etf_basic_raw_snapshot_reference(
    *,
    raw_snapshot_hash: str,
    raw_uri: str,
    raw_observed_at: str,
) -> EtfBasicRawSnapshotReference:
    payload = {
        "raw_snapshot_hash": _normalize_sha256(
            raw_snapshot_hash,
            field_name="raw_snapshot_hash",
        ),
        "raw_uri": _normalize_non_empty_string(raw_uri, field_name="raw_uri"),
        "raw_observed_at": _normalize_timezone_datetime(
            raw_observed_at,
            field_name="raw_observed_at",
        ),
    }
    return EtfBasicRawSnapshotReference(
        **payload,
        reference_fingerprint=_etf_basic_reference_fingerprint(payload),
    ).validate_contract()


def build_etf_basic_silver_snapshot_reference(
    *,
    raw_snapshot_hash: str,
    silver_content_hash: str,
    raw_uri: str,
    silver_uri: str,
    raw_observed_at: str,
    silver_observed_at: str,
    eligibility_as_of: date | str,
    requestable_code_count: int,
    requestable_code_hash: str,
) -> EtfBasicSilverSnapshotReference:
    payload = _normalize_etf_basic_silver_reference_payload(
        raw_snapshot_hash=raw_snapshot_hash,
        silver_content_hash=silver_content_hash,
        raw_uri=raw_uri,
        silver_uri=silver_uri,
        raw_observed_at=raw_observed_at,
        silver_observed_at=silver_observed_at,
        eligibility_as_of=eligibility_as_of,
        requestable_code_count=requestable_code_count,
        requestable_code_hash=requestable_code_hash,
    )
    return EtfBasicSilverSnapshotReference(
        **payload,
        reference_fingerprint=_etf_basic_reference_fingerprint(payload),
    ).validate_contract()


def build_etf_basic_silver_run_config(
    *,
    raw_snapshot_reference: EtfBasicRawSnapshotReference,
) -> dict[str, object]:
    """Serialize the one approved Basic Silver runtime input."""

    reference = raw_snapshot_reference.validate_contract()
    return {
        "ops": {
            "silver_etf_basic": {
                "config": {
                    "raw_snapshot_reference": reference.model_dump(),
                }
            }
        }
    }


def normalize_etf_basic_snapshot_rows(
    rows: Iterable[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Normalize source-shaped rows without changing source string values."""

    normalized_rows: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    expected_columns = set(ETF_BASIC_SOURCE_COLUMNS)
    for row_index, source_row in enumerate(rows):
        actual_columns = set(source_row)
        if actual_columns != expected_columns:
            missing = sorted(expected_columns - actual_columns)
            extra = sorted(actual_columns - expected_columns)
            raise ValueError(
                "ETF Basic row columns do not match the 14-field source contract: "
                f"row_index={row_index}, missing={missing}, extra={extra}."
            )

        normalized_row: dict[str, object] = {}
        for column in _ETF_BASIC_STRING_COLUMNS:
            value = source_row[column]
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"ETF Basic {column} must be VARCHAR or null; got {type(value).__name__}."
                )
            normalized_row[column] = value
        normalized_row["mgt_fee"] = _normalize_raw_double(source_row["mgt_fee"])

        ts_code = normalized_row["ts_code"]
        if not isinstance(ts_code, str) or not ts_code:
            raise ValueError("ETF Basic ts_code must be a non-empty VARCHAR.")
        if ts_code in seen_codes:
            raise ValueError(f"ETF Basic ts_code is duplicated: {ts_code}.")
        seen_codes.add(ts_code)

        list_status = normalized_row["list_status"]
        if list_status not in ETF_BASIC_LIST_STATUSES:
            raise ValueError(
                f"ETF Basic list_status is not registered: {list_status!r}."
            )
        suffix = _etf_basic_code_suffix(ts_code)
        if suffix not in ETF_BASIC_CODE_SUFFIXES:
            raise ValueError(f"ETF Basic ts_code suffix is not registered: {ts_code}.")
        exchange = normalized_row["exchange"]
        if suffix in ETF_BASIC_SILVER_SUFFIXES and exchange != suffix:
            raise ValueError(
                "ETF Basic exchange does not match the exchange code suffix: "
                f"ts_code={ts_code}, exchange={exchange!r}."
            )
        normalized_rows.append(normalized_row)

    return tuple(sorted(normalized_rows, key=lambda row: str(row["ts_code"])))


def compute_etf_basic_snapshot_hash(
    rows: Iterable[Mapping[str, object]],
) -> str:
    """Hash Raw business content using the post-Parquet DOUBLE representation."""

    normalized_rows = normalize_etf_basic_snapshot_rows(rows)
    canonical_rows = [
        [
            _canonical_raw_value(column, row[column])
            for column in ETF_BASIC_SOURCE_COLUMNS
        ]
        for row in normalized_rows
    ]
    return _sha256_json(canonical_rows, sort_keys=False)


def compute_etf_basic_silver_content_hash(
    rows: Iterable[Mapping[str, object]],
) -> str:
    """Hash Silver content with canonical DATE and DECIMAL representations."""

    normalized_rows = _normalize_etf_basic_silver_rows(rows)
    canonical_rows = [
        [
            _canonical_silver_value(column, row[column])
            for column in ETF_BASIC_SOURCE_COLUMNS
        ]
        for row in normalized_rows
    ]
    return _sha256_json(canonical_rows, sort_keys=False)


def classify_etf_basic_requestability(
    row: Mapping[str, object],
    *,
    eligibility_as_of: date,
) -> str | None:
    """Mirror the Prod serving requestability classification for one Silver row."""

    if isinstance(eligibility_as_of, datetime) or not isinstance(
        eligibility_as_of, date
    ):
        raise ValueError("eligibility_as_of must be a date.")  # noqa: TRY004

    ts_code = row.get("ts_code")
    if not isinstance(ts_code, str):
        return ETF_BASIC_REQUESTABILITY_NON_EXCHANGE_SUFFIX
    suffix = _etf_basic_code_suffix(ts_code)
    if suffix not in ETF_BASIC_SILVER_SUFFIXES:
        return ETF_BASIC_REQUESTABILITY_NON_EXCHANGE_SUFFIX
    if row.get("exchange") != suffix:
        return ETF_BASIC_REQUESTABILITY_EXCHANGE_MISMATCH
    if row.get("list_status") != "L":
        return ETF_BASIC_REQUESTABILITY_STATUS_NOT_LISTED
    list_date = row.get("list_date")
    if list_date is None:
        return ETF_BASIC_REQUESTABILITY_LIST_DATE_NULL
    if isinstance(list_date, datetime) or not isinstance(list_date, date):
        raise ValueError(  # noqa: TRY004
            "ETF Basic Silver list_date must be DATE or null."
        )
    if list_date > eligibility_as_of:
        return ETF_BASIC_REQUESTABILITY_LIST_DATE_AFTER_AS_OF
    return None


def compute_etf_requestable_target_hash(
    rows: Iterable[Mapping[str, object]],
) -> str:
    """Hash sorted ``ts_code/list_date/exchange`` targets like Prod does."""

    targets: list[dict[str, str]] = []
    seen_codes: set[str] = set()
    for row in rows:
        ts_code = row.get("ts_code")
        list_date = row.get("list_date")
        exchange = row.get("exchange")
        if not isinstance(ts_code, str) or not ts_code:
            raise ValueError("ETF request target ts_code must be a non-empty VARCHAR.")
        if ts_code in seen_codes:
            raise ValueError(f"ETF request target ts_code is duplicated: {ts_code}.")
        seen_codes.add(ts_code)
        if isinstance(list_date, datetime) or not isinstance(list_date, date):
            raise ValueError(  # noqa: TRY004
                "ETF request target list_date must be DATE."
            )
        if exchange not in ETF_BASIC_SILVER_SUFFIXES:
            raise ValueError("ETF request target exchange must be SH or SZ.")
        targets.append(
            {
                "ts_code": ts_code,
                "list_date": list_date.isoformat(),
                "exchange": exchange,
            }
        )
    targets.sort(key=lambda target: target["ts_code"])
    return _sha256_json(targets, sort_keys=True)


def _normalize_etf_basic_silver_reference_payload(
    *,
    raw_snapshot_hash: str,
    silver_content_hash: str,
    raw_uri: str,
    silver_uri: str,
    raw_observed_at: str,
    silver_observed_at: str,
    eligibility_as_of: date | str,
    requestable_code_count: int,
    requestable_code_hash: str,
) -> dict[str, object]:
    if (
        isinstance(requestable_code_count, bool)
        or not isinstance(requestable_code_count, int)
        or requestable_code_count < 0
    ):
        raise ValueError("requestable_code_count must be a non-negative integer.")
    return {
        "raw_snapshot_hash": _normalize_sha256(
            raw_snapshot_hash,
            field_name="raw_snapshot_hash",
        ),
        "silver_content_hash": _normalize_sha256(
            silver_content_hash,
            field_name="silver_content_hash",
        ),
        "raw_uri": _normalize_non_empty_string(raw_uri, field_name="raw_uri"),
        "silver_uri": _normalize_non_empty_string(
            silver_uri,
            field_name="silver_uri",
        ),
        "raw_observed_at": _normalize_timezone_datetime(
            raw_observed_at,
            field_name="raw_observed_at",
        ),
        "silver_observed_at": _normalize_timezone_datetime(
            silver_observed_at,
            field_name="silver_observed_at",
        ),
        "eligibility_as_of": _normalize_iso_date(
            eligibility_as_of,
            field_name="eligibility_as_of",
        ),
        "requestable_code_count": requestable_code_count,
        "requestable_code_hash": _normalize_sha256(
            requestable_code_hash,
            field_name="requestable_code_hash",
        ),
    }


def _normalize_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value


def _normalize_sha256(value: object, *, field_name: str) -> str:
    normalized = _normalize_non_empty_string(value, field_name=field_name)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256.")
    return normalized


def _normalize_timezone_datetime(value: object, *, field_name: str) -> str:
    normalized = _normalize_non_empty_string(value, field_name=field_name)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{field_name} must be ISO-8601.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset.")
    return parsed.isoformat()


def _normalize_iso_date(value: date | str, *, field_name: str) -> str:
    if isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a date, not datetime.")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must use YYYY-MM-DD format.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")
    return value


def _etf_basic_reference_fingerprint(payload: Mapping[str, object]) -> str:
    return _sha256_json(dict(payload), sort_keys=True)


def _normalize_etf_basic_silver_rows(
    rows: Iterable[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    normalized_rows: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    expected_columns = set(ETF_BASIC_SOURCE_COLUMNS)
    for row_index, source_row in enumerate(rows):
        actual_columns = set(source_row)
        if actual_columns != expected_columns:
            missing = sorted(expected_columns - actual_columns)
            extra = sorted(actual_columns - expected_columns)
            raise ValueError(
                "ETF Basic Silver row columns do not match the 14-field contract: "
                f"row_index={row_index}, missing={missing}, extra={extra}."
            )
        normalized_row = dict(source_row)
        ts_code = normalized_row["ts_code"]
        if not isinstance(ts_code, str) or not ts_code:
            raise ValueError("ETF Basic Silver ts_code must be a non-empty VARCHAR.")
        if ts_code in seen_codes:
            raise ValueError(f"ETF Basic Silver ts_code is duplicated: {ts_code}.")
        seen_codes.add(ts_code)
        for column in _ETF_BASIC_STRING_COLUMNS:
            if column in {"setup_date", "list_date"}:
                continue
            value = normalized_row[column]
            if value is not None and not isinstance(value, str):
                raise ValueError(f"ETF Basic Silver {column} must be VARCHAR or null.")
        for column in ("setup_date", "list_date"):
            value = normalized_row[column]
            if value is not None and (
                isinstance(value, datetime) or not isinstance(value, date)
            ):
                raise ValueError(f"ETF Basic Silver {column} must be DATE or null.")
        _canonical_decimal(normalized_row["mgt_fee"])
        normalized_rows.append(normalized_row)
    return tuple(sorted(normalized_rows, key=lambda row: str(row["ts_code"])))


def _normalize_raw_double(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("ETF Basic mgt_fee must be DOUBLE or null.")  # noqa: TRY004
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("ETF Basic mgt_fee must be finite.")
    return normalized


def _canonical_raw_value(column: str, value: object) -> object:
    if value is None:
        return None
    if column == "mgt_fee":
        return float(value).hex()
    return value


def _canonical_silver_value(column: str, value: object) -> object:
    if value is None:
        return None
    if column in {"setup_date", "list_date"}:
        return value.isoformat()  # type: ignore[union-attr]
    if column == "mgt_fee":
        return _canonical_decimal(value)
    return value


def _canonical_decimal(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(  # noqa: TRY004
            "ETF Basic Silver mgt_fee must be DECIMAL or null."
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("ETF Basic Silver mgt_fee must be finite.")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("ETF Basic Silver mgt_fee cannot be canonicalized.") from error
    if not number.is_finite():
        raise ValueError("ETF Basic Silver mgt_fee must be finite.")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _etf_basic_code_suffix(ts_code: str) -> str:
    return ts_code.rsplit(".", 1)[-1] if "." in ts_code else ""


def _sha256_json(value: object, *, sort_keys: bool) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=sort_keys,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ETF_BASIC_CODE_SUFFIXES",
    "ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT",
    "ETF_BASIC_LIST_STATUSES",
    "ETF_BASIC_PAGE_LIMIT",
    "ETF_BASIC_REQUESTABILITY_EXCHANGE_MISMATCH",
    "ETF_BASIC_REQUESTABILITY_LIST_DATE_AFTER_AS_OF",
    "ETF_BASIC_REQUESTABILITY_LIST_DATE_NULL",
    "ETF_BASIC_REQUESTABILITY_NON_EXCHANGE_SUFFIX",
    "ETF_BASIC_REQUESTABILITY_STATUS_NOT_LISTED",
    "ETF_BASIC_SILVER_SUFFIXES",
    "ETF_BASIC_SOURCE_API",
    "ETF_BASIC_SOURCE_COLUMNS",
    "RAW_ETF_BASIC_CHECKS",
    "SILVER_ETF_BASIC_CHECKS",
    "EtfBasicRawSnapshotReference",
    "EtfBasicSilverConfig",
    "EtfBasicSilverSnapshotReference",
    "build_etf_basic_raw_snapshot_reference",
    "build_etf_basic_silver_run_config",
    "build_etf_basic_silver_snapshot_reference",
    "classify_etf_basic_requestability",
    "compute_etf_basic_silver_content_hash",
    "compute_etf_basic_snapshot_hash",
    "compute_etf_requestable_target_hash",
    "normalize_etf_basic_snapshot_rows",
]
