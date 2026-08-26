"""Bounded BSE minute-history recovery planning and Raw candidate workflow.

This module is deliberately absent from Dagster definitions. R0 freezes source
facts under the staging root; R1 consumes only those frozen files. Formal Raw
promotion remains an explicit maintenance action.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from orchestrator.defs.assets import stk_mins as stk_mins_assets
from orchestrator.defs.checks.stk_mins_checks import (
    evaluate_silver_stk_mins_partition_diagnostics,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_stk_mins_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_STK_MINS_SCHEMA
from orchestrator.defs.tushare_request_policy import (
    BoundedCodePageRequestSession,
    TushareRequestPolicy,
)

SCHEMA_VERSION = 1
RECOVERY_KIND = "stk_mins_bse_history_recovery"
DEFAULT_RECOVERY_STAGING_ROOT = (
    Path(DEFAULT_LAKE_STAGING_ROOT) / "stk_mins_bse_recovery"
)
SOURCE_PAGE_LIMIT = 8_000
AUDIT_TIMEOUT_SECONDS = 300
SAMPLE_LIMIT = 20
SUPPORTED_FREQS = (1, 5, 15, 30, 60)
EXPECTED_BAR_COUNT_BY_FREQ = {1: 241, 5: 49, 15: 17, 30: 9, 60: 5}
RAW_COLUMNS = tuple(column.name for column in RAW_STK_MINS_SCHEMA)
RAW_COLUMN_TYPES = {column.name: column.type for column in RAW_STK_MINS_SCHEMA}


class BseMinuteRecoveryError(RuntimeError):
    """Raised before an unsafe recovery stage can continue."""


class BseMinuteRecoveryMode(str, Enum):
    UNCLASSIFIED_CANDIDATE = "unclassified_candidate"
    SOURCE_RECOVERABLE = "source_recoverable"
    SILVER_FALLBACK_RECOVERABLE = "silver_fallback_recoverable"
    SOURCE_EMPTY_SKIP = "source_empty_skip"
    SOURCE_UNUSABLE_SKIP = "source_unusable_skip"
    PARTIAL_BLOCKED = "partial_blocked"


@dataclass(frozen=True, slots=True, order=True)
class BseMinuteRecoveryScope:
    trade_date: str
    freq: int

    def __post_init__(self) -> None:
        normalized_date = _normalize_trade_date(self.trade_date)
        normalized_freq = int(self.freq)
        if normalized_freq not in SUPPORTED_FREQS:
            raise ValueError(f"Unsupported stk_mins frequency: {self.freq}")
        object.__setattr__(self, "trade_date", normalized_date)
        object.__setattr__(self, "freq", normalized_freq)

    @property
    def scope_id(self) -> str:
        return f"{self.trade_date}:{self.freq}"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BseSourceScopeCoverage:
    total_row_count: int
    complete_aliases: tuple[str, ...]
    canonical_session_complete_aliases: tuple[str, ...]
    returned_alias_count: int


@dataclass(frozen=True, slots=True)
class BseSourceWindow:
    source_ts_code: str
    freq: int
    trade_dates: tuple[str, ...]

    @property
    def start_date(self) -> str:
        return self.trade_dates[0]

    @property
    def end_date(self) -> str:
        return self.trade_dates[-1]

    @property
    def window_id(self) -> str:
        return f"{self.source_ts_code}:{self.freq}:{self.start_date}:{self.end_date}"

    def to_dict(self) -> dict[str, object]:
        return {
            "source_ts_code": self.source_ts_code,
            "freq": self.freq,
            "trade_dates": list(self.trade_dates),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "window_id": self.window_id,
        }


@dataclass(frozen=True, slots=True)
class BseOneMinuteFallbackEligibility:
    trade_date: str
    expected_latest_code_count: int
    raw_1m_returned_latest_code_count: int
    raw_1m_required_241_point_code_count: int
    raw_1m_allowed_source_time_code_count: int
    invalid_code_count: int
    invalid_code_samples: tuple[str, ...]
    duplicate_time_count: int
    invalid_time_row_count: int
    passed: bool
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["invalid_code_samples"] = list(self.invalid_code_samples)
        return payload


def _normalize_trade_date(value: str) -> str:
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise ValueError(f"Invalid trade date: {value!r}") from error


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BseMinuteRecoveryError(f"{label} is unreadable: {path}") from error
    if not isinstance(payload, dict):
        raise BseMinuteRecoveryError(f"{label} must be a JSON object")
    return payload


def _validate_roots(*, lake_root: Path, staging_root: Path) -> tuple[Path, Path]:
    lake = Path(lake_root).resolve()
    staging = Path(staging_root).resolve()
    if lake == staging or staging.is_relative_to(lake) or lake.is_relative_to(staging):
        raise BseMinuteRecoveryError(
            "recovery staging must be outside the formal lake root"
        )
    if lake == Path("/Volumes/datasource/goldenshare-tushare-lake").resolve():
        raise BseMinuteRecoveryError(
            "legacy lake root is forbidden for Dagster recovery"
        )
    return lake, staging


def _assert_output_outside_formal_lake(
    path: Path | None,
    *,
    lake_root: Path,
    label: str,
) -> None:
    if path is not None and Path(path).resolve().is_relative_to(lake_root.resolve()):
        raise BseMinuteRecoveryError(f"{label} must not be written inside formal lake")


def _file_fingerprint(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "size_bytes": None,
            "mtime_ns": None,
        }
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _assert_fingerprint_unchanged(fingerprint: Mapping[str, object]) -> None:
    path = Path(str(fingerprint["path"]))
    observed = _file_fingerprint(path)
    if observed != dict(fingerprint):
        raise BseMinuteRecoveryError(f"formal target fingerprint changed: {path}")


def _expected_session_times(freq: int) -> tuple[str, ...]:
    if freq == 1:
        morning_step = afternoon_step = 1
    else:
        morning_step = afternoon_step = freq

    values: list[str] = ["09:30:00"]
    current = datetime(2000, 1, 1, 9, 30, tzinfo=timezone.utc) + timedelta(
        minutes=morning_step
    )
    morning_end = datetime(2000, 1, 1, 11, 30, tzinfo=timezone.utc)
    while current <= morning_end:
        values.append(current.strftime("%H:%M:%S"))
        current += timedelta(minutes=morning_step)
    current = datetime(2000, 1, 1, 13, 0, tzinfo=timezone.utc) + timedelta(
        minutes=afternoon_step
    )
    afternoon_end = datetime(2000, 1, 1, 15, 0, tzinfo=timezone.utc)
    while current <= afternoon_end:
        values.append(current.strftime("%H:%M:%S"))
        current += timedelta(minutes=afternoon_step)
    expected_count = EXPECTED_BAR_COUNT_BY_FREQ[freq]
    if len(values) != expected_count:
        raise AssertionError(f"session contract mismatch for {freq}m: {len(values)}")
    return tuple(values)


def _allowed_raw_source_times(freq: int) -> tuple[str, ...]:
    """Return canonical bars plus source-faithful post-close rows through 15:30."""

    values = list(_expected_session_times(freq))
    current = datetime(2000, 1, 1, 15, 0, tzinfo=timezone.utc) + timedelta(minutes=freq)
    source_end = datetime(2000, 1, 1, 15, 30, tzinfo=timezone.utc)
    while current <= source_end:
        values.append(current.strftime("%H:%M:%S"))
        current += timedelta(minutes=freq)
    return tuple(values)


def _relation_for_paths(paths: Sequence[Path]) -> str:
    normalized = tuple(Path(path).resolve() for path in paths)
    if not normalized:
        raise BseMinuteRecoveryError("at least one parquet path is required")
    values = ", ".join(duckdb_string(path) for path in normalized)
    return f"read_parquet([{values}], hive_partitioning=false, union_by_name=false)"


def _scope_manifest_schema() -> tuple[tuple[str, str], ...]:
    return (
        ("trade_date", "VARCHAR"),
        ("freq", "INTEGER"),
        ("latest_ts_code", "VARCHAR"),
        ("preferred_source_ts_code", "VARCHAR"),
        ("alias_rule", "VARCHAR"),
        ("existing_source_ts_code", "VARCHAR"),
        ("existing_row_count", "BIGINT"),
        ("coverage_status", "VARCHAR"),
        ("reason_code", "VARCHAR"),
    )


def _write_scope_manifest(
    *,
    duckdb_resource: DuckDBResource,
    rows: Sequence[Mapping[str, object]],
    target_path: Path,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_name(f".{target_path.name}.{uuid4().hex}.tmp")
    schema = _scope_manifest_schema()
    try:
        with duckdb_resource.connect() as connection:
            connection.execute(
                "CREATE TEMP TABLE bse_scope ("
                + ", ".join(f'"{name}" {type_name}' for name, type_name in schema)
                + ")"
            )
            connection.executemany(
                "INSERT INTO bse_scope VALUES (" + ", ".join("?" for _ in schema) + ")",
                [[row.get(name) for name, _ in schema] for row in rows],
            )
            connection.execute(
                copy_query_to_parquet(
                    "SELECT * FROM bse_scope ORDER BY trade_date, freq, latest_ts_code",
                    temporary,
                )
            )
        os.replace(temporary, target_path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_expected_latest_codes(connection, daily_path: Path) -> tuple[str, ...]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code
        FROM {read_parquet(daily_path, hive_partitioning=False)}
        WHERE upper(trim(CAST(ts_code AS VARCHAR))) LIKE '%.BJ'
        ORDER BY ts_code
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _active_identity_rows(connection, identity_path: Path, trade_date: str):
    return connection.execute(
        f"""
        SELECT
          upper(trim(CAST(latest_ts_code AS VARCHAR))) AS latest_ts_code,
          upper(trim(CAST(source_ts_code AS VARCHAR))) AS source_ts_code,
          lower(trim(CAST(identity_source AS VARCHAR))) AS identity_source
        FROM {read_parquet(identity_path, hive_partitioning=False)}
        WHERE CAST({duckdb_string(trade_date)} AS DATE) >= CAST(valid_from AS DATE)
          AND (valid_to IS NULL OR CAST({duckdb_string(trade_date)} AS DATE) < CAST(valid_to AS DATE))
        """
    ).fetchall()


def _select_aliases(
    *,
    expected_latest_codes: Sequence[str],
    identity_rows: Sequence[Sequence[object]],
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    by_latest: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for latest, source, identity_source in identity_rows:
        by_latest[str(latest)].append((str(source), str(identity_source)))

    aliases: dict[str, tuple[str, str]] = {}
    failures: dict[str, str] = {}
    for latest in expected_latest_codes:
        active = by_latest.get(latest, [])
        bse_aliases = sorted(
            {source for source, origin in active if origin == "bse_mapping"}
        )
        namechange_aliases = sorted(
            {
                source
                for source, origin in active
                if origin == "namechange" and source != latest
            }
        )
        self_aliases = sorted(
            {source for source, _origin in active if source == latest}
        )
        if len(bse_aliases) == 1:
            aliases[latest] = (bse_aliases[0], "bse_mapping")
        elif len(bse_aliases) > 1:
            failures[latest] = "multiple_active_bse_aliases"
        elif len(namechange_aliases) == 1:
            aliases[latest] = (namechange_aliases[0], "namechange")
        elif len(namechange_aliases) > 1:
            failures[latest] = "multiple_active_namechange_aliases"
        elif len(self_aliases) == 1:
            aliases[latest] = (self_aliases[0], "self_mapping")
        elif len(self_aliases) > 1:
            failures[latest] = "multiple_active_self_aliases"
        else:
            failures[latest] = "missing_active_source_alias"
    return aliases, failures


def _existing_coverage(
    *,
    connection,
    raw_path: Path,
    identity_path: Path,
    trade_date: str,
    freq: int,
    expected_latest_codes: Sequence[str],
) -> dict[str, tuple[tuple[str, ...], int, str]]:
    expected_values = ", ".join(duckdb_string(code) for code in expected_latest_codes)
    expected_times = ", ".join(
        duckdb_string(value) for value in _expected_session_times(freq)
    )
    allowed_source_times = ", ".join(
        duckdb_string(value) for value in _allowed_raw_source_times(freq)
    )
    rows = connection.execute(
        f"""
        WITH identity AS (
          SELECT
            upper(trim(CAST(source_ts_code AS VARCHAR))) AS source_ts_code,
            upper(trim(CAST(latest_ts_code AS VARCHAR))) AS latest_ts_code
          FROM {read_parquet(identity_path, hive_partitioning=False)}
          WHERE CAST({duckdb_string(trade_date)} AS DATE) >= CAST(valid_from AS DATE)
            AND (valid_to IS NULL OR CAST({duckdb_string(trade_date)} AS DATE) < CAST(valid_to AS DATE))
        ), mapped AS (
          SELECT
            identity.latest_ts_code,
            upper(trim(CAST(raw.ts_code AS VARCHAR))) AS source_ts_code,
            strftime(CAST(raw.trade_time AS TIMESTAMP), '%H:%M:%S') AS trade_clock
          FROM {read_parquet(raw_path, hive_partitioning=False)} AS raw
          JOIN identity
            ON upper(trim(CAST(raw.ts_code AS VARCHAR))) = identity.source_ts_code
          WHERE identity.latest_ts_code IN ({expected_values})
            AND CAST(raw.freq AS INTEGER) = {freq}
            AND CAST(raw.trade_time AS DATE) = CAST({duckdb_string(trade_date)} AS DATE)
        )
        SELECT
          latest_ts_code,
          list_sort(list_distinct(list(source_ts_code))) AS source_codes,
          count(*) AS row_count,
          count(DISTINCT trade_clock) AS distinct_time_count,
          count(DISTINCT trade_clock) FILTER (
            WHERE trade_clock IN ({expected_times})
          ) AS required_time_count,
          count(*) FILTER (
            WHERE trade_clock NOT IN ({allowed_source_times})
          ) AS invalid_time_count
        FROM mapped
        GROUP BY latest_ts_code
        ORDER BY latest_ts_code
        """
    ).fetchall()
    expected_count = EXPECTED_BAR_COUNT_BY_FREQ[freq]
    coverage: dict[str, tuple[tuple[str, ...], int, str]] = {}
    for (
        latest,
        source_codes,
        row_count,
        distinct_time_count,
        required_time_count,
        invalid_time_count,
    ) in rows:
        count = int(row_count)
        status = (
            "covered"
            if count == int(distinct_time_count)
            and int(required_time_count) == expected_count
            and int(invalid_time_count) == 0
            else "partial"
        )
        coverage[str(latest)] = (
            tuple(str(value) for value in (source_codes or ())),
            count,
            status,
        )
    return coverage


def _fallback_fact(
    *,
    connection,
    lake_root: Path,
    identity_path: Path,
    trade_date: str,
    expected_latest_codes: Sequence[str],
) -> dict[str, object]:
    raw_1m_path = raw_stk_mins_path(lake_root, 1, trade_date)
    if not raw_1m_path.is_file() or not expected_latest_codes:
        return {
            "raw_1m_expected_code_count": len(expected_latest_codes),
            "raw_1m_complete_code_count": 0,
            "raw_1m_241_point_code_count": 0,
            "raw_1m_exact_time_set_code_count": 0,
            "raw_1m_invalid_code_count": len(expected_latest_codes),
            "fallback_eligibility_status": "blocked",
        }
    coverage = _existing_coverage(
        connection=connection,
        raw_path=raw_1m_path,
        identity_path=identity_path,
        trade_date=trade_date,
        freq=1,
        expected_latest_codes=expected_latest_codes,
    )
    complete_codes = tuple(
        code
        for code, (_sources, _count, status) in coverage.items()
        if status == "covered"
    )
    complete_count = len(complete_codes)
    expected_count = len(expected_latest_codes)
    invalid_count = expected_count - complete_count
    return {
        "raw_1m_expected_code_count": expected_count,
        "raw_1m_complete_code_count": complete_count,
        "raw_1m_241_point_code_count": complete_count,
        "raw_1m_exact_time_set_code_count": complete_count,
        "raw_1m_invalid_code_count": invalid_count,
        "fallback_eligibility_status": (
            "candidate" if invalid_count == 0 else "blocked"
        ),
    }


def audit_bse_one_minute_fallback_eligibility(
    *,
    lake_root: Path,
    trade_date: str,
    expected_latest_codes: Sequence[str],
    duckdb_resource: DuckDBResource | None = None,
) -> BseOneMinuteFallbackEligibility:
    """Prove that every expected BSE code has the canonical 241-point 1m base."""

    started_at = perf_counter()
    normalized_date = _normalize_trade_date(trade_date)
    expected_codes = tuple(
        sorted({str(code).strip().upper() for code in expected_latest_codes})
    )
    if not expected_codes or any(not code.endswith(".BJ") for code in expected_codes):
        raise BseMinuteRecoveryError(
            "fallback eligibility requires a non-empty canonical BSE code set"
        )
    raw_path = raw_stk_mins_path(lake_root, 1, normalized_date)
    identity_path = silver_stock_identity_map_path(lake_root)
    suspend_path = silver_stock_suspend_daily_path(lake_root, normalized_date)
    required_paths = (raw_path, identity_path, suspend_path)
    if any(not path.is_file() for path in required_paths):
        missing = next(path for path in required_paths if not path.is_file())
        raise BseMinuteRecoveryError(
            f"fallback eligibility input is missing: {missing}"
        )

    resource = duckdb_resource or DuckDBResource()
    expected_values = ", ".join(f"({duckdb_string(code)})" for code in expected_codes)
    required_times = ", ".join(
        duckdb_string(value) for value in _expected_session_times(1)
    )
    allowed_times = ", ".join(
        duckdb_string(value) for value in _allowed_raw_source_times(1)
    )
    with resource.connect() as connection:
        observed_schema = tuple(
            (str(row[0]), str(row[1]).upper())
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM {read_parquet(raw_path, hive_partitioning=False)}"
            ).fetchall()
        )
        expected_schema = tuple(
            (column, RAW_COLUMN_TYPES[column]) for column in RAW_COLUMNS
        )
        if observed_schema != expected_schema:
            raise BseMinuteRecoveryError(
                f"fallback eligibility Raw 1m schema mismatch: {normalized_date}"
            )
        rows = connection.execute(
            f"""
            WITH expected(latest_ts_code) AS (VALUES {expected_values}),
            identity AS (
              SELECT DISTINCT
                upper(trim(CAST(source_ts_code AS VARCHAR))) AS source_ts_code,
                upper(trim(CAST(latest_ts_code AS VARCHAR))) AS latest_ts_code
              FROM {read_parquet(identity_path, hive_partitioning=False)}
              WHERE CAST({duckdb_string(normalized_date)} AS DATE) >= CAST(valid_from AS DATE)
                AND (valid_to IS NULL OR CAST({duckdb_string(normalized_date)} AS DATE) < CAST(valid_to AS DATE))
            ), full_day_suspend AS (
              SELECT DISTINCT upper(trim(CAST(ts_code AS VARCHAR))) AS latest_ts_code
              FROM {read_parquet(suspend_path, hive_partitioning=False)}
              WHERE CAST(trade_date AS DATE) = CAST({duckdb_string(normalized_date)} AS DATE)
                AND suspend_type = 'S'
                AND suspend_timing IS NULL
            ), source AS (
              SELECT
                upper(trim(CAST(raw.ts_code AS VARCHAR))) AS source_ts_code,
                identity.latest_ts_code,
                strftime(CAST(raw.trade_time AS TIMESTAMP), '%H:%M:%S') AS trade_clock,
                CAST(raw.freq AS INTEGER) AS freq,
                CAST(raw.trade_time AS DATE) AS trade_date
              FROM {read_parquet(raw_path, hive_partitioning=False)} AS raw
              LEFT JOIN identity
                ON upper(trim(CAST(raw.ts_code AS VARCHAR))) = identity.source_ts_code
              WHERE upper(trim(CAST(raw.ts_code AS VARCHAR))) LIKE '%.BJ'
                AND NOT EXISTS (
                  SELECT 1
                  FROM full_day_suspend
                  WHERE full_day_suspend.latest_ts_code = identity.latest_ts_code
                )
            ), per_code AS (
              SELECT
                expected.latest_ts_code,
                count(source.trade_clock) AS row_count,
                count(DISTINCT source.trade_clock) AS distinct_time_count,
                count(DISTINCT source.trade_clock) FILTER (
                  WHERE source.trade_clock IN ({required_times})
                ) AS required_time_count,
                count(*) FILTER (
                  WHERE source.trade_clock IS NOT NULL
                    AND source.trade_clock NOT IN ({allowed_times})
                ) AS invalid_time_count
              FROM expected
              LEFT JOIN source
                ON source.latest_ts_code = expected.latest_ts_code
               AND source.freq = 1
               AND source.trade_date = CAST({duckdb_string(normalized_date)} AS DATE)
              GROUP BY expected.latest_ts_code
            ), global_invalid AS (
              SELECT
                count(*) FILTER (
                  WHERE latest_ts_code IS NULL
                     OR latest_ts_code NOT IN (SELECT latest_ts_code FROM expected)
                     OR freq != 1
                     OR trade_date != CAST({duckdb_string(normalized_date)} AS DATE)
                ) AS invalid_row_count,
                count(*) FILTER (
                  WHERE trade_clock NOT IN ({allowed_times})
                ) AS invalid_time_row_count
              FROM source
            )
            SELECT
              latest_ts_code,
              row_count,
              distinct_time_count,
              required_time_count,
              invalid_time_count,
              (SELECT invalid_row_count FROM global_invalid),
              (SELECT invalid_time_row_count FROM global_invalid)
            FROM per_code
            ORDER BY latest_ts_code
            """
        ).fetchall()

    returned_count = sum(1 for row in rows if int(row[1]) > 0)
    required_count = sum(1 for row in rows if int(row[3]) == 241)
    allowed_count = sum(
        1
        for row in rows
        if int(row[1]) > 0 and int(row[1]) == int(row[2]) and int(row[4]) == 0
    )
    duplicate_time_count = sum(max(int(row[1]) - int(row[2]), 0) for row in rows)
    global_invalid_row_count = int(rows[0][5] or 0)
    invalid_time_row_count = int(rows[0][6] or 0)
    invalid_codes = tuple(
        str(row[0])
        for row in rows
        if not (
            int(row[1]) > 0
            and int(row[1]) == int(row[2])
            and int(row[3]) == 241
            and int(row[4]) == 0
        )
    )
    invalid_code_count = len(invalid_codes) + global_invalid_row_count
    passed = (
        len(expected_codes) == returned_count == required_count == allowed_count
        and invalid_code_count == 0
        and duplicate_time_count == 0
        and invalid_time_row_count == 0
    )
    return BseOneMinuteFallbackEligibility(
        trade_date=normalized_date,
        expected_latest_code_count=len(expected_codes),
        raw_1m_returned_latest_code_count=returned_count,
        raw_1m_required_241_point_code_count=required_count,
        raw_1m_allowed_source_time_code_count=allowed_count,
        invalid_code_count=invalid_code_count,
        invalid_code_samples=invalid_codes[:SAMPLE_LIMIT],
        duplicate_time_count=duplicate_time_count,
        invalid_time_row_count=invalid_time_row_count,
        passed=passed,
        elapsed_ms=round((perf_counter() - started_at) * 1000, 3),
    )


def plan_bse_stk_mins_history_recovery(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    staging_root: Path = DEFAULT_RECOVERY_STAGING_ROOT,
    scopes: Sequence[BseMinuteRecoveryScope],
    duckdb_resource: DuckDBResource | None = None,
    output_path: Path | None = None,
) -> dict[str, object]:
    """R0A: build an immutable, read-only recovery scope plan."""

    started_at = perf_counter()
    lake, staging = _validate_roots(lake_root=lake_root, staging_root=staging_root)
    selected_scopes = tuple(sorted(set(scopes)))
    if not selected_scopes:
        raise BseMinuteRecoveryError("at least one explicit recovery scope is required")
    _assert_output_outside_formal_lake(
        output_path,
        lake_root=lake,
        label="scope plan report",
    )
    identity_path = silver_stock_identity_map_path(lake)
    if not identity_path.is_file():
        raise BseMinuteRecoveryError(f"identity map is missing: {identity_path}")
    resource = duckdb_resource or DuckDBResource()
    manifest_rows: list[dict[str, object]] = []
    scope_summaries: list[dict[str, object]] = []
    stop_reasons: list[str] = []

    with resource.connect() as connection:
        for scope in selected_scopes:
            daily_path = silver_stock_daily_path(lake, scope.trade_date)
            raw_path = raw_stk_mins_path(lake, scope.freq, scope.trade_date)
            if not daily_path.is_file() or not raw_path.is_file():
                stop_reasons.append(f"missing_required_file:{scope.scope_id}")
                continue
            expected = _load_expected_latest_codes(connection, daily_path)
            if not expected:
                stop_reasons.append(f"empty_expected_bse_set:{scope.scope_id}")
                continue
            identity_rows = _active_identity_rows(
                connection, identity_path, scope.trade_date
            )
            aliases, alias_failures = _select_aliases(
                expected_latest_codes=expected,
                identity_rows=identity_rows,
            )
            coverage = _existing_coverage(
                connection=connection,
                raw_path=raw_path,
                identity_path=identity_path,
                trade_date=scope.trade_date,
                freq=scope.freq,
                expected_latest_codes=expected,
            )
            partial_codes = tuple(
                sorted(
                    code
                    for code, (_sources, _count, status) in coverage.items()
                    if status == "partial"
                )
            )
            covered_codes = tuple(
                sorted(
                    code
                    for code, (_sources, _count, status) in coverage.items()
                    if status == "covered"
                )
            )
            missing_codes = tuple(sorted(set(expected) - set(coverage)))
            if not missing_codes and not partial_codes:
                stop_reasons.append(f"scope_has_no_missing_codes:{scope.scope_id}")
            if partial_codes:
                stop_reasons.append(f"existing_partial_code_day:{scope.scope_id}")
            if alias_failures:
                stop_reasons.append(f"identity_mapping_failure:{scope.scope_id}")

            for latest in expected:
                sources, row_count, coverage_status = coverage.get(
                    latest, ((), 0, "missing")
                )
                preferred_source, alias_rule = aliases.get(latest, ("", "blocked"))
                reason_code = alias_failures.get(latest, "")
                if coverage_status == "partial":
                    reason_code = "existing_partial_code_day"
                manifest_rows.append(
                    {
                        "trade_date": scope.trade_date,
                        "freq": scope.freq,
                        "latest_ts_code": latest,
                        "preferred_source_ts_code": preferred_source,
                        "alias_rule": alias_rule,
                        "existing_source_ts_code": ",".join(sources),
                        "existing_row_count": row_count,
                        "coverage_status": coverage_status,
                        "reason_code": reason_code,
                    }
                )

            fallback = _fallback_fact(
                connection=connection,
                lake_root=lake,
                identity_path=identity_path,
                trade_date=scope.trade_date,
                expected_latest_codes=expected,
            )
            mode = (
                BseMinuteRecoveryMode.PARTIAL_BLOCKED.value
                if alias_failures or partial_codes
                else BseMinuteRecoveryMode.UNCLASSIFIED_CANDIDATE.value
            )
            summary = {
                "trade_date": scope.trade_date,
                "freq": scope.freq,
                "mode": mode,
                "expected_latest_code_count": len(expected),
                "expected_latest_code_hash": _hash_payload(expected),
                "canonical_existing_latest_code_count": len(covered_codes),
                "missing_latest_code_count": len(missing_codes),
                "missing_latest_code_hash": _hash_payload(missing_codes),
                "missing_latest_code_samples": list(missing_codes[:SAMPLE_LIMIT]),
                "partial_existing_code_count": len(partial_codes),
                "partial_existing_code_samples": list(partial_codes[:SAMPLE_LIMIT]),
                "identity_failure_count": len(alias_failures),
                "identity_failure_samples": list(sorted(alias_failures)[:SAMPLE_LIMIT]),
                "raw_target_fingerprint": _file_fingerprint(raw_path),
                "daily_source_fingerprint": _file_fingerprint(daily_path),
                **fallback,
            }
            scope_summaries.append(summary)

    logical_scope_hash = _hash_payload(manifest_rows)
    frozen_payload = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "lake_root": str(lake),
        "staging_root": str(staging),
        "identity_map_fingerprint": _file_fingerprint(identity_path),
        "selected_scopes": [scope.to_dict() for scope in selected_scopes],
        "scope_summaries": scope_summaries,
        "logical_scope_hash": logical_scope_hash,
        "source_request_budget": {
            "minimum_interval_seconds": 0.13,
            "max_retries": 3,
            "backoff_seconds": [1, 2, 4],
            "max_requests": 1_200,
            "max_elapsed_seconds": 300,
        },
        "audit_timeout_seconds": AUDIT_TIMEOUT_SECONDS,
        "planned_event_count": 0,
    }
    plan_hash = _hash_payload(frozen_payload)
    plan_root = staging / f"plan_hash={plan_hash}"
    scope_manifest_path = plan_root / "scope.parquet"
    _write_scope_manifest(
        duckdb_resource=resource,
        rows=manifest_rows,
        target_path=scope_manifest_path,
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "stage": "r0a_scope_plan",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan_hash,
        "frozen_payload": frozen_payload,
        "scope_manifest_path": str(scope_manifest_path),
        "scope_manifest_sha256": _sha256_file(scope_manifest_path),
        "scope_row_count": len(manifest_rows),
        "should_stop": bool(stop_reasons),
        "stop_reason_codes": sorted(set(stop_reasons)),
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
    }
    plan_path = plan_root / "scope-plan.json"
    _atomic_write_json(plan_path, payload)
    payload["plan_path"] = str(plan_path)
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def load_bse_stk_mins_recovery_plan(path: Path) -> dict[str, Any]:
    payload = _load_json(path, label="BSE recovery plan")
    if payload.get("recovery_kind") != RECOVERY_KIND:
        raise BseMinuteRecoveryError("unexpected recovery plan kind")
    frozen_payload = payload.get("frozen_payload")
    if not isinstance(frozen_payload, dict):
        raise BseMinuteRecoveryError("recovery plan frozen_payload is missing")
    if payload.get("plan_hash") != _hash_payload(frozen_payload):
        raise BseMinuteRecoveryError("recovery plan hash mismatch")
    scope_path = Path(str(payload.get("scope_manifest_path") or ""))
    if not scope_path.is_file():
        raise BseMinuteRecoveryError("recovery scope manifest is missing")
    if payload.get("scope_manifest_sha256") != _sha256_file(scope_path):
        raise BseMinuteRecoveryError("recovery scope manifest hash mismatch")
    return payload


def _scope_rows_for_plan(plan: Mapping[str, Any], resource: DuckDBResource):
    scope_path = Path(str(plan["scope_manifest_path"]))
    with resource.connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM {read_parquet(scope_path, hive_partitioning=False)} "
            "ORDER BY trade_date, freq, latest_ts_code"
        ).fetchall()
        columns = tuple(column[0] for column in connection.description)
    return tuple(dict(zip(columns, row, strict=True)) for row in rows)


def _source_windows(
    scope_rows: Sequence[Mapping[str, object]],
) -> tuple[BseSourceWindow, ...]:
    requested_dates: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in scope_rows:
        if row.get("coverage_status") != "missing" or row.get("reason_code"):
            continue
        source_code = str(row.get("preferred_source_ts_code") or "")
        if not source_code:
            continue
        requested_dates[(source_code, int(row["freq"]))].add(str(row["trade_date"]))

    windows: list[BseSourceWindow] = []
    for (source_code, freq), values in sorted(requested_dates.items()):
        ordered = sorted(date.fromisoformat(value) for value in values)
        current: list[date] = []
        for value in ordered:
            if current and (value - current[-1]).days > 4:
                windows.append(
                    BseSourceWindow(
                        source_ts_code=source_code,
                        freq=freq,
                        trade_dates=tuple(item.isoformat() for item in current),
                    )
                )
                current = []
            current.append(value)
        if current:
            windows.append(
                BseSourceWindow(
                    source_ts_code=source_code,
                    freq=freq,
                    trade_dates=tuple(item.isoformat() for item in current),
                )
            )
    return tuple(windows)


def _window_root(plan_root: Path, window: BseSourceWindow) -> Path:
    window_hash = _hash_payload(window.to_dict())[:16]
    return (
        plan_root
        / "source"
        / f"freq={window.freq}"
        / f"source_ts_code={window.source_ts_code}"
        / f"window={window.start_date}_{window.end_date}_{window_hash}"
    )


def _source_request_contract(window: BseSourceWindow) -> dict[str, object]:
    return {
        "api_name": "stk_mins",
        "ts_code": window.source_ts_code,
        "freq": f"{window.freq}min",
        "start_date": f"{window.start_date} 09:00:00",
        "end_date": f"{window.end_date} 19:00:00",
        "limit": SOURCE_PAGE_LIMIT,
        "fields": list(RAW_COLUMNS),
    }


def _write_raw_page(
    *,
    resource: DuckDBResource,
    rows: Sequence[Mapping[str, object]],
    target_path: Path,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with resource.connect() as connection:
        connection.execute(
            "CREATE TEMP TABLE source_page ("
            + ", ".join(
                f'"{column}" {RAW_COLUMN_TYPES[column]}' for column in RAW_COLUMNS
            )
            + ")"
        )
        connection.executemany(
            "INSERT INTO source_page VALUES ("
            + ", ".join("?" for _ in RAW_COLUMNS)
            + ")",
            [[row.get(column) for column in RAW_COLUMNS] for row in rows],
        )
        connection.execute(
            copy_query_to_parquet("SELECT * FROM source_page", target_path)
        )


def _validate_staged_window(
    *,
    plan_hash: str,
    root: Path,
    window: BseSourceWindow,
) -> dict[str, Any] | None:
    sidecar_path = root / "request.json"
    if not root.exists():
        return None
    if not root.is_dir() or not sidecar_path.is_file():
        raise BseMinuteRecoveryError(f"partial source window exists: {root}")
    payload = _load_json(sidecar_path, label="source window sidecar")
    if (
        payload.get("status") != "complete"
        or payload.get("plan_hash") != plan_hash
        or payload.get("window") != window.to_dict()
    ):
        raise BseMinuteRecoveryError(f"source window sidecar contract mismatch: {root}")
    for page in payload.get("pages") or ():
        page_path = Path(str(page["path"])).resolve()
        if not page_path.is_relative_to(root.resolve()):
            raise BseMinuteRecoveryError(
                f"source page escaped its window root: {page_path}"
            )
        if not page_path.is_file() or page.get("sha256") != _sha256_file(page_path):
            raise BseMinuteRecoveryError(f"source page hash mismatch: {page_path}")
    return payload


def _stage_source_window(
    *,
    plan_hash: str,
    plan_root: Path,
    window: BseSourceWindow,
    session: BoundedCodePageRequestSession,
    tushare: TushareResource,
    resource: DuckDBResource,
) -> dict[str, object]:
    final_root = _window_root(plan_root, window)
    existing = _validate_staged_window(
        plan_hash=plan_hash,
        root=final_root,
        window=window,
    )
    if existing is not None:
        return dict(existing)

    temporary = final_root.with_name(f".{final_root.name}.{uuid4().hex}.tmp")
    temporary.mkdir(parents=True)
    pages: list[dict[str, object]] = []
    expected_dates = set(window.trade_dates)
    request_contract = _source_request_contract(window)
    start_datetime = str(request_contract["start_date"])
    end_datetime = str(request_contract["end_date"])

    def request_page(offset: int):
        result = tushare.call(
            "stk_mins",
            {
                "ts_code": window.source_ts_code,
                "freq": f"{window.freq}min",
                "start_date": start_datetime,
                "end_date": end_datetime,
                "limit": SOURCE_PAGE_LIMIT,
                "offset": offset,
            },
            RAW_COLUMNS,
        )
        if result.columns != RAW_COLUMNS and (result.columns or result.rows):
            raise BseMinuteRecoveryError(
                f"stk_mins source columns changed for {window.window_id}"
            )
        return result

    def consume_page(offset: int, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        normalized: list[dict[str, object]] = []
        for row in rows:
            trade_date = str(row.get("trade_time") or "")[:10]
            if not window.start_date <= trade_date <= window.end_date:
                raise BseMinuteRecoveryError(
                    f"source returned a date outside the request window for {window.window_id}"
                )
            if trade_date not in expected_dates:
                continue
            normalized.append(
                stk_mins_assets._normalize_tushare_stk_mins_row(
                    row,
                    requested_ts_code=window.source_ts_code,
                    requested_freq=window.freq,
                    partition_key=trade_date,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                )
            )
        page_path = temporary / f"offset={offset:08d}" / "part-000.parquet"
        _write_raw_page(resource=resource, rows=normalized, target_path=page_path)
        pages.append(
            {
                "offset": offset,
                "row_count": len(normalized),
                "path": str(page_path),
                "sha256": _sha256_file(page_path),
                "key_hash": _hash_payload(
                    sorted(
                        (str(row["ts_code"]), str(row["trade_time"]))
                        for row in normalized
                    )
                ),
            }
        )

    try:
        request = session.execute_pages(
            request_page=request_page,
            extract_rows=lambda result: result.rows,
            page_size=SOURCE_PAGE_LIMIT,
            scope=window.window_id,
            row_key=lambda row: (str(row.get("ts_code")), str(row.get("trade_time"))),
            consume_page=consume_page,
            retain_rows=False,
        )
        if request.failed_pages or request.budget_exceeded:
            reason = request.budget_reason or "source_request_failed"
            raise BseMinuteRecoveryError(f"{reason}: {window.window_id}")
        final_pages = []
        for page in pages:
            relative = Path(str(page["path"])).relative_to(temporary)
            final_page = final_root / relative
            final_pages.append({**page, "path": str(final_page)})
        payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "status": "complete",
            "plan_hash": plan_hash,
            "window": window.to_dict(),
            "request_contract": request_contract,
            "request_count": request.request_count,
            "page_count": request.page_count,
            "retry_count": request.retry_count,
            "elapsed_ms": round(request.elapsed_ms, 3),
            "row_count": sum(int(page["row_count"]) for page in pages),
            "pages": final_pages,
        }
        _atomic_write_json(temporary / "request.json", payload)
        if final_root.exists():
            raise BseMinuteRecoveryError(
                f"source window appeared concurrently: {final_root}"
            )
        final_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, final_root)
        return payload
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _source_rows_for_scope(
    *,
    connection,
    scope_rows: Sequence[Mapping[str, object]],
    window_sidecars: Sequence[Mapping[str, object]],
    trade_date: str,
    freq: int,
) -> BseSourceScopeCoverage:
    missing_rows = tuple(
        row
        for row in scope_rows
        if str(row["trade_date"]) == trade_date
        and int(row["freq"]) == freq
        and row["coverage_status"] == "missing"
        and not row["reason_code"]
    )
    aliases = tuple(
        sorted(str(row["preferred_source_ts_code"]) for row in missing_rows)
    )
    page_paths = tuple(
        Path(str(page["path"]))
        for sidecar in window_sidecars
        if int(sidecar["window"]["freq"]) == freq
        and trade_date in sidecar["window"]["trade_dates"]
        for page in sidecar.get("pages") or ()
    )
    if not page_paths:
        return BseSourceScopeCoverage(0, (), (), 0)
    relation = _relation_for_paths(page_paths)
    aliases_sql = ", ".join(duckdb_string(value) for value in aliases)
    expected_times = ", ".join(
        duckdb_string(value) for value in _expected_session_times(freq)
    )
    allowed_source_times = ", ".join(
        duckdb_string(value) for value in _allowed_raw_source_times(freq)
    )
    rows = connection.execute(
        f"""
        SELECT
          upper(trim(CAST(ts_code AS VARCHAR))) AS source_ts_code,
          count(*) AS row_count,
          count(DISTINCT strftime(CAST(trade_time AS TIMESTAMP), '%H:%M:%S')) AS distinct_time_count,
          count(DISTINCT strftime(CAST(trade_time AS TIMESTAMP), '%H:%M:%S')) FILTER (
            WHERE strftime(CAST(trade_time AS TIMESTAMP), '%H:%M:%S') IN ({expected_times})
          ) AS required_time_count,
          count(*) FILTER (
            WHERE strftime(CAST(trade_time AS TIMESTAMP), '%H:%M:%S') NOT IN ({allowed_source_times})
          ) AS invalid_time_count,
          count(*) FILTER (
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR vol IS NULL OR amount IS NULL OR vol < 0 OR amount < 0
               OR high < greatest(open, close, low)
               OR low > least(open, close, high)
          ) AS invalid_value_count,
          count(*) FILTER (
            WHERE strftime(CAST(trade_time AS TIMESTAMP), '%H:%M:%S') IN ({expected_times})
              AND (
                open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                OR vol IS NULL OR amount IS NULL OR vol < 0 OR amount < 0
                OR high < greatest(open, close, low)
                OR low > least(open, close, high)
              )
          ) AS invalid_required_value_count
        FROM {relation}
        WHERE CAST(trade_time AS DATE) = CAST({duckdb_string(trade_date)} AS DATE)
          AND upper(trim(CAST(ts_code AS VARCHAR))) IN ({aliases_sql})
        GROUP BY source_ts_code
        ORDER BY source_ts_code
        """
    ).fetchall()
    complete = tuple(
        str(source)
        for (
            source,
            row_count,
            distinct_count,
            required_time_count,
            invalid_time,
            invalid_value,
            _invalid_required_value,
        ) in rows
        if int(row_count) == int(distinct_count)
        and int(required_time_count) == EXPECTED_BAR_COUNT_BY_FREQ[freq]
        and int(invalid_time) == 0
        and int(invalid_value) == 0
    )
    canonical_session_complete = tuple(
        str(source)
        for (
            source,
            row_count,
            distinct_count,
            required_time_count,
            invalid_time,
            _invalid_value,
            invalid_required_value,
        ) in rows
        if int(row_count) == int(distinct_count)
        and int(required_time_count) == EXPECTED_BAR_COUNT_BY_FREQ[freq]
        and int(invalid_time) == 0
        and int(invalid_required_value) == 0
    )
    total_rows = sum(int(row[1]) for row in rows)
    return BseSourceScopeCoverage(
        total_row_count=total_rows,
        complete_aliases=complete,
        canonical_session_complete_aliases=canonical_session_complete,
        returned_alias_count=len(rows),
    )


def _source_window_from_payload(payload: Mapping[str, object]) -> BseSourceWindow:
    dates = payload.get("trade_dates")
    if not isinstance(dates, list) or not dates:
        raise BseMinuteRecoveryError("source window trade_dates are missing")
    window = BseSourceWindow(
        source_ts_code=str(payload.get("source_ts_code") or ""),
        freq=int(payload.get("freq") or 0),
        trade_dates=tuple(str(value) for value in dates),
    )
    if payload != window.to_dict():
        raise BseMinuteRecoveryError(
            f"source window payload is not canonical: {window.window_id}"
        )
    return window


def _load_reusable_source_windows(
    *,
    plan_path: Path,
    bundle_path: Path,
) -> tuple[str, dict[str, tuple[Path, dict[str, object]]]]:
    plan = load_bse_stk_mins_recovery_plan(plan_path)
    payload = _load_json(bundle_path, label="reusable BSE source bundle")
    frozen = payload.get("frozen_bundle")
    if not isinstance(frozen, dict):
        raise BseMinuteRecoveryError("reusable source bundle frozen payload is missing")
    if (
        payload.get("stage") != "r0b_source_bundle"
        or payload.get("plan_hash") != plan.get("plan_hash")
        or int(payload.get("incomplete_window_count") or 0) != 0
        or int(payload.get("completed_window_count") or 0)
        != int(payload.get("expected_window_count") or -1)
        or payload.get("failure_samples")
        or not payload.get("bundle_hash")
        or payload.get("bundle_hash") != _hash_payload(frozen)
    ):
        raise BseMinuteRecoveryError("reusable source bundle is not complete")
    _assert_source_bundle_matches_plan(plan, payload)

    plan_root = Path(str(plan["scope_manifest_path"])).parent
    reusable: dict[str, tuple[Path, dict[str, object]]] = {}
    for raw_sidecar in frozen.get("source_windows") or ():
        if not isinstance(raw_sidecar, dict):
            raise BseMinuteRecoveryError("reusable source window sidecar is invalid")
        window_payload = raw_sidecar.get("window")
        if not isinstance(window_payload, dict):
            raise BseMinuteRecoveryError("reusable source window payload is invalid")
        window = _source_window_from_payload(window_payload)
        root = _window_root(plan_root, window)
        observed = _validate_staged_window(
            plan_hash=str(plan["plan_hash"]),
            root=root,
            window=window,
        )
        if observed is None:
            raise BseMinuteRecoveryError(
                f"reusable source window is missing: {window.window_id}"
            )
        if observed.get("request_contract") != _source_request_contract(window):
            raise BseMinuteRecoveryError(
                f"reusable source request contract changed: {window.window_id}"
            )
        key = _hash_payload(window.to_dict())
        if key in reusable:
            raise BseMinuteRecoveryError(
                f"duplicate reusable source window: {window.window_id}"
            )
        reusable[key] = (root, observed)
    if len(reusable) != int(payload["expected_window_count"]):
        raise BseMinuteRecoveryError("reusable source window count mismatch")
    return str(plan["plan_hash"]), reusable


def _carry_forward_source_window(
    *,
    plan_hash: str,
    reused_plan_hash: str,
    plan_root: Path,
    window: BseSourceWindow,
    old_root: Path,
    sidecar: Mapping[str, object],
) -> dict[str, object]:
    final_root = _window_root(plan_root, window)
    existing = _validate_staged_window(
        plan_hash=plan_hash,
        root=final_root,
        window=window,
    )
    if existing is not None:
        return dict(existing)
    if sidecar.get("request_contract") != _source_request_contract(window):
        raise BseMinuteRecoveryError(
            f"carried source request contract changed: {window.window_id}"
        )

    temporary = final_root.with_name(f".{final_root.name}.{uuid4().hex}.tmp")
    temporary.mkdir(parents=True)
    pages: list[dict[str, object]] = []
    try:
        for raw_page in sidecar.get("pages") or ():
            page = dict(raw_page)
            source_path = Path(str(page["path"])).resolve()
            relative = source_path.relative_to(old_root.resolve())
            temporary_path = temporary / relative
            temporary_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source_path, temporary_path)
            except OSError:
                shutil.copy2(source_path, temporary_path)
            if _sha256_file(temporary_path) != page.get("sha256"):
                raise BseMinuteRecoveryError(
                    f"carried source page hash mismatch: {window.window_id}"
                )
            pages.append(
                {
                    **page,
                    "path": str(final_root / relative),
                }
            )
        payload = {
            **dict(sidecar),
            "plan_hash": plan_hash,
            "pages": pages,
            "reused_from_plan_hash": reused_plan_hash,
            "reused_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write_json(temporary / "request.json", payload)
        if final_root.exists():
            raise BseMinuteRecoveryError(
                f"source window appeared concurrently: {final_root}"
            )
        final_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, final_root)
        return payload
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def stage_bse_stk_mins_source_pages(
    *,
    plan_path: Path,
    tushare: TushareResource,
    duckdb_resource: DuckDBResource | None = None,
    output_path: Path | None = None,
    request_policy: TushareRequestPolicy | None = None,
    max_window_count: int | None = None,
    reuse_plan_path: Path | None = None,
    reuse_source_bundle_path: Path | None = None,
) -> dict[str, object]:
    """R0B: freeze missing source rows under staging; never write formal Raw."""

    started_at = perf_counter()
    plan = load_bse_stk_mins_recovery_plan(plan_path)
    if plan.get("should_stop"):
        raise BseMinuteRecoveryError("scope plan has stop reasons")
    resource = duckdb_resource or DuckDBResource()
    lake_root = Path(str(plan["frozen_payload"]["lake_root"]))
    _assert_output_outside_formal_lake(
        output_path,
        lake_root=lake_root,
        label="source bundle report",
    )
    scope_rows = _scope_rows_for_plan(plan, resource)
    windows = _source_windows(scope_rows)
    if max_window_count is not None and max_window_count <= 0:
        raise ValueError("max_window_count must be positive when provided")
    selected_windows = windows[:max_window_count] if max_window_count else windows
    policy = request_policy or TushareRequestPolicy(
        minimum_interval_seconds=0.13,
        max_retries=3,
        backoff_base_seconds=1.0,
        backoff_multiplier=2.0,
        max_backoff_seconds=8.0,
        max_requests=1_200,
        max_elapsed_seconds=300.0,
    )
    session = BoundedCodePageRequestSession(policy=policy)
    plan_hash = str(plan["plan_hash"])
    plan_root = Path(str(plan["scope_manifest_path"])).parent
    if (reuse_plan_path is None) != (reuse_source_bundle_path is None):
        raise ValueError(
            "reuse_plan_path and reuse_source_bundle_path must be provided together"
        )
    reused_plan_hash = ""
    reusable_windows: dict[str, tuple[Path, dict[str, object]]] = {}
    if reuse_plan_path is not None and reuse_source_bundle_path is not None:
        reused_plan_hash, reusable_windows = _load_reusable_source_windows(
            plan_path=reuse_plan_path,
            bundle_path=reuse_source_bundle_path,
        )
        if reused_plan_hash == plan_hash:
            raise BseMinuteRecoveryError("source reuse requires a different plan hash")
    sidecars: list[dict[str, object]] = []
    failure_samples: list[dict[str, object]] = []
    reused_window_count = 0
    preexisting_window_count = 0
    requested_window_count = 0
    for window in selected_windows:
        try:
            existing = _validate_staged_window(
                plan_hash=plan_hash,
                root=_window_root(plan_root, window),
                window=window,
            )
            if existing is not None:
                sidecars.append(dict(existing))
                preexisting_window_count += 1
                continue
            reusable = reusable_windows.get(_hash_payload(window.to_dict()))
            if reusable is not None:
                old_root, old_sidecar = reusable
                sidecars.append(
                    _carry_forward_source_window(
                        plan_hash=plan_hash,
                        reused_plan_hash=reused_plan_hash,
                        plan_root=plan_root,
                        window=window,
                        old_root=old_root,
                        sidecar=old_sidecar,
                    )
                )
                reused_window_count += 1
                continue
            requested_window_count += 1
            sidecars.append(
                _stage_source_window(
                    plan_hash=plan_hash,
                    plan_root=plan_root,
                    window=window,
                    session=session,
                    tushare=tushare,
                    resource=resource,
                )
            )
        except Exception as error:  # noqa: BLE001 - bounded report retains the stop fact.
            failure_samples.append(
                {
                    "window_id": window.window_id,
                    "error_type": type(error).__name__,
                    "reason": str(error)[:300],
                }
            )
            break

    all_sidecars: list[dict[str, object]] = []
    incomplete_windows: list[str] = []
    for window in windows:
        observed = _validate_staged_window(
            plan_hash=plan_hash,
            root=_window_root(plan_root, window),
            window=window,
        )
        if observed is None:
            incomplete_windows.append(window.window_id)
        else:
            all_sidecars.append(dict(observed))

    mode_rows: list[dict[str, object]] = []
    if not incomplete_windows:
        with resource.connect() as connection:
            for summary in plan["frozen_payload"]["scope_summaries"]:
                trade_date = str(summary["trade_date"])
                freq = int(summary["freq"])
                if summary["mode"] == BseMinuteRecoveryMode.PARTIAL_BLOCKED.value:
                    mode = BseMinuteRecoveryMode.PARTIAL_BLOCKED
                    reason = "scope_plan_blocked"
                    returned_count = 0
                    returned_rows = 0
                else:
                    coverage = _source_rows_for_scope(
                        connection=connection,
                        scope_rows=scope_rows,
                        window_sidecars=all_sidecars,
                        trade_date=trade_date,
                        freq=freq,
                    )
                    returned_rows = coverage.total_row_count
                    complete_aliases = coverage.complete_aliases
                    returned_count = coverage.returned_alias_count
                    expected_missing = int(summary["missing_latest_code_count"])
                    if returned_count == 0:
                        if (
                            freq != 1
                            and summary["fallback_eligibility_status"] == "candidate"
                        ):
                            mode = BseMinuteRecoveryMode.SILVER_FALLBACK_RECOVERABLE
                            reason = "source_empty_complete_1m_fallback"
                        else:
                            mode = BseMinuteRecoveryMode.SOURCE_EMPTY_SKIP
                            reason = "source_empty"
                    elif len(complete_aliases) == expected_missing:
                        mode = BseMinuteRecoveryMode.SOURCE_RECOVERABLE
                        reason = "missing_source_scope_complete"
                    elif (
                        freq != 1
                        and summary["fallback_eligibility_status"] == "candidate"
                    ):
                        mode = BseMinuteRecoveryMode.SILVER_FALLBACK_RECOVERABLE
                        reason = "source_partial_complete_1m_fallback"
                    elif (
                        freq == 1
                        and len(coverage.canonical_session_complete_aliases)
                        == expected_missing
                    ):
                        mode = BseMinuteRecoveryMode.SOURCE_UNUSABLE_SKIP
                        reason = "source_optional_tail_invalid"
                    else:
                        mode = BseMinuteRecoveryMode.PARTIAL_BLOCKED
                        reason = "source_scope_partial"
                mode_rows.append(
                    {
                        "trade_date": trade_date,
                        "freq": freq,
                        "mode": mode.value,
                        "reason_code": reason,
                        "expected_latest_code_count": int(
                            summary["expected_latest_code_count"]
                        ),
                        "canonical_existing_latest_code_count": int(
                            summary["canonical_existing_latest_code_count"]
                        ),
                        "missing_latest_code_count": int(
                            summary["missing_latest_code_count"]
                        ),
                        "returned_source_code_count": returned_count,
                        "returned_source_row_count": returned_rows,
                    }
                )

    frozen_bundle = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "plan_hash": plan_hash,
        "scope_manifest_sha256": plan["scope_manifest_sha256"],
        "source_windows": all_sidecars,
        "mode_rows": mode_rows,
    }
    blocked_mode_rows = tuple(
        row
        for row in mode_rows
        if row["mode"] == BseMinuteRecoveryMode.PARTIAL_BLOCKED.value
    )
    bundle_hash = _hash_payload(frozen_bundle) if not incomplete_windows else None
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "stage": "r0b_source_bundle",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan_hash,
        "bundle_hash": bundle_hash,
        "frozen_bundle": frozen_bundle,
        "expected_window_count": len(windows),
        "completed_window_count": len(all_sidecars),
        "incomplete_window_count": len(incomplete_windows),
        "incomplete_window_samples": incomplete_windows[:SAMPLE_LIMIT],
        "request_count": session.request_count,
        "retry_count": session.retry_count,
        "preexisting_window_count": preexisting_window_count,
        "reused_window_count": reused_window_count,
        "requested_window_count": requested_window_count,
        "reused_from_plan_hash": reused_plan_hash or None,
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
        "failure_samples": failure_samples[:SAMPLE_LIMIT],
        "blocked_mode_count": len(blocked_mode_rows),
        "blocked_mode_samples": [
            {
                "trade_date": row["trade_date"],
                "freq": row["freq"],
                "reason_code": row["reason_code"],
            }
            for row in blocked_mode_rows[:SAMPLE_LIMIT]
        ],
        "should_stop": bool(incomplete_windows or failure_samples or blocked_mode_rows),
    }
    bundle_path = plan_root / "source-bundle.json"
    _atomic_write_json(bundle_path, payload)
    payload["bundle_path"] = str(bundle_path)
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def load_bse_stk_mins_source_bundle(path: Path) -> dict[str, Any]:
    payload = _load_json(path, label="BSE source bundle")
    if payload.get("should_stop") or not payload.get("bundle_hash"):
        raise BseMinuteRecoveryError("source bundle is incomplete")
    frozen = payload.get("frozen_bundle")
    if not isinstance(frozen, dict) or payload["bundle_hash"] != _hash_payload(frozen):
        raise BseMinuteRecoveryError("source bundle hash mismatch")
    for sidecar in frozen.get("source_windows") or ():
        for page in sidecar.get("pages") or ():
            page_path = Path(str(page["path"]))
            if not page_path.is_file() or page["sha256"] != _sha256_file(page_path):
                raise BseMinuteRecoveryError(f"source bundle page changed: {page_path}")
    return payload


def _assert_source_bundle_matches_plan(
    plan: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> None:
    frozen_bundle = bundle.get("frozen_bundle") or {}
    if bundle.get("plan_hash") != plan.get("plan_hash"):
        raise BseMinuteRecoveryError("source bundle belongs to a different plan")
    if frozen_bundle.get("scope_manifest_sha256") != plan.get("scope_manifest_sha256"):
        raise BseMinuteRecoveryError("source bundle scope manifest hash mismatch")
    plan_root = Path(str(plan["scope_manifest_path"])).parent.resolve()
    for sidecar in frozen_bundle.get("source_windows") or ():
        for page in sidecar.get("pages") or ():
            page_path = Path(str(page["path"])).resolve()
            if not page_path.is_relative_to(plan_root / "source"):
                raise BseMinuteRecoveryError(
                    f"source bundle page escaped the plan staging root: {page_path}"
                )


def _candidate_path(plan: Mapping[str, Any], trade_date: str, freq: int) -> Path:
    root = Path(str(plan["scope_manifest_path"])).parent
    return (
        root / "raw" / f"freq={freq}m" / f"trade_date={trade_date}" / "part-000.parquet"
    )


def _source_page_paths_for_scope(
    bundle: Mapping[str, Any], *, trade_date: str, freq: int
) -> tuple[Path, ...]:
    return tuple(
        Path(str(page["path"]))
        for sidecar in bundle["frozen_bundle"]["source_windows"]
        if int(sidecar["window"]["freq"]) == freq
        and trade_date in sidecar["window"]["trade_dates"]
        for page in sidecar.get("pages") or ()
    )


def _scope_manifest_relation(plan: Mapping[str, Any]) -> str:
    return read_parquet(Path(str(plan["scope_manifest_path"])), hive_partitioning=False)


def _candidate_stats(connection, relation: str, *, trade_date: str, freq: int):
    row = connection.execute(
        f"""
        SELECT
          count(*) AS row_count,
          count(*) - count(DISTINCT struct_pack(ts_code := ts_code, freq := freq, trade_time := trade_time)) AS duplicate_count,
          count(*) FILTER (
            WHERE CAST(freq AS INTEGER) != {freq}
               OR CAST(trade_time AS DATE) != CAST({duckdb_string(trade_date)} AS DATE)
          ) AS scope_invalid_count
        FROM {relation}
        """
    ).fetchone()
    return tuple(int(value or 0) for value in row)


def _non_bse_hash(connection, relation: str) -> tuple[int, int, int]:
    columns = ", ".join(f'"{column}"' for column in RAW_COLUMNS)
    row = connection.execute(
        f"""
        SELECT
          count(*),
          coalesce(sum(CAST(hash({columns}) AS HUGEINT)), 0),
          coalesce(bit_xor(hash({columns})), 0)
        FROM {relation}
        WHERE upper(trim(CAST(ts_code AS VARCHAR))) NOT LIKE '%.BJ'
        """
    ).fetchone()
    return tuple(int(value or 0) for value in row)


def _canonical_bse_codes(
    connection,
    relation: str,
    *,
    identity_path: Path,
    trade_date: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        f"""
        WITH identity AS (
          SELECT
            upper(trim(CAST(source_ts_code AS VARCHAR))) AS source_ts_code,
            upper(trim(CAST(latest_ts_code AS VARCHAR))) AS latest_ts_code
          FROM {read_parquet(identity_path, hive_partitioning=False)}
          WHERE CAST({duckdb_string(trade_date)} AS DATE) >= CAST(valid_from AS DATE)
            AND (valid_to IS NULL OR CAST({duckdb_string(trade_date)} AS DATE) < CAST(valid_to AS DATE))
        )
        SELECT DISTINCT identity.latest_ts_code
        FROM {relation} AS candidate
        JOIN identity
          ON upper(trim(CAST(candidate.ts_code AS VARCHAR))) = identity.source_ts_code
        WHERE identity.latest_ts_code LIKE '%.BJ'
        ORDER BY identity.latest_ts_code
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _assert_raw_candidate_bse_code_contract(
    *,
    existing_codes: Sequence[str],
    candidate_codes: Sequence[str],
    expected_codes: Sequence[str],
) -> None:
    existing = set(existing_codes)
    candidate = set(candidate_codes)
    expected = set(expected_codes)
    missing_expected = tuple(sorted(expected - candidate))
    existing_extras = existing - expected
    candidate_extras = candidate - expected
    introduced_extras = tuple(sorted(candidate_extras - existing_extras))
    removed_extras = tuple(sorted(existing_extras - candidate_extras))
    if missing_expected or introduced_extras or removed_extras:
        raise BseMinuteRecoveryError(
            "Raw candidate BSE code contract failed: "
            f"missing_expected={missing_expected[:SAMPLE_LIMIT]},"
            f"introduced_extras={introduced_extras[:SAMPLE_LIMIT]},"
            f"removed_extras={removed_extras[:SAMPLE_LIMIT]}"
        )


def build_bse_raw_recovery_candidates(
    *,
    plan_path: Path,
    bundle_path: Path,
    duckdb_resource: DuckDBResource | None = None,
    output_path: Path | None = None,
) -> dict[str, object]:
    """R1: build Raw candidates exclusively from the frozen source bundle."""

    started_at = perf_counter()
    plan = load_bse_stk_mins_recovery_plan(plan_path)
    bundle = load_bse_stk_mins_source_bundle(bundle_path)
    _assert_source_bundle_matches_plan(plan, bundle)
    resource = duckdb_resource or DuckDBResource()
    lake_root = Path(str(plan["frozen_payload"]["lake_root"]))
    _assert_output_outside_formal_lake(
        output_path,
        lake_root=lake_root,
        label="Raw candidate report",
    )
    identity_path = silver_stock_identity_map_path(lake_root)
    scope_relation = _scope_manifest_relation(plan)
    candidates: list[dict[str, object]] = []
    failure_samples: list[dict[str, object]] = []

    with resource.connect() as connection:
        for mode_row in bundle["frozen_bundle"]["mode_rows"]:
            if mode_row["mode"] != BseMinuteRecoveryMode.SOURCE_RECOVERABLE.value:
                continue
            trade_date = str(mode_row["trade_date"])
            freq = int(mode_row["freq"])
            target_path = raw_stk_mins_path(lake_root, freq, trade_date)
            summary = next(
                item
                for item in plan["frozen_payload"]["scope_summaries"]
                if item["trade_date"] == trade_date and int(item["freq"]) == freq
            )
            _assert_fingerprint_unchanged(summary["raw_target_fingerprint"])
            source_paths = _source_page_paths_for_scope(
                bundle, trade_date=trade_date, freq=freq
            )
            if not source_paths:
                raise BseMinuteRecoveryError(
                    f"source-recoverable scope has no staged rows: {trade_date}:{freq}"
                )
            source_relation = _relation_for_paths(source_paths)
            existing_relation = read_parquet(target_path, hive_partitioning=False)
            scope_rows = connection.execute(
                f"""
                SELECT latest_ts_code, preferred_source_ts_code
                FROM {scope_relation}
                WHERE trade_date = {duckdb_string(trade_date)}
                  AND freq = {freq}
                  AND coverage_status = 'missing'
                  AND reason_code = ''
                ORDER BY latest_ts_code
                """
            ).fetchall()
            missing_aliases = tuple(str(row[1]) for row in scope_rows)
            alias_values = ", ".join(duckdb_string(value) for value in missing_aliases)
            overlap_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM {source_relation} AS source
                    JOIN {existing_relation} AS existing
                      ON source.ts_code = existing.ts_code
                     AND source.freq = existing.freq
                     AND source.trade_time = existing.trade_time
                    WHERE CAST(source.trade_time AS DATE) = CAST({duckdb_string(trade_date)} AS DATE)
                      AND source.ts_code IN ({alias_values})
                    """
                ).fetchone()[0]
            )
            if overlap_count:
                raise BseMinuteRecoveryError(
                    f"staged source overlaps existing Raw keys: {trade_date}:{freq}"
                )
            selected_source = (
                f"SELECT {', '.join(RAW_COLUMNS)} FROM {source_relation} "
                f"WHERE CAST(trade_time AS DATE)=CAST({duckdb_string(trade_date)} AS DATE) "
                f"AND CAST(freq AS INTEGER)={freq} AND ts_code IN ({alias_values})"
            )
            candidate_path = _candidate_path(plan, trade_date, freq)
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = candidate_path.with_name(
                f".{candidate_path.name}.{uuid4().hex}.tmp"
            )
            try:
                connection.execute(
                    copy_query_to_parquet(
                        f"""
                        SELECT {", ".join(RAW_COLUMNS)} FROM {existing_relation}
                        UNION ALL
                        {selected_source}
                        """,
                        temporary,
                    )
                )
                candidate_relation = read_parquet(temporary, hive_partitioning=False)
                row_count, duplicate_count, scope_invalid_count = _candidate_stats(
                    connection,
                    candidate_relation,
                    trade_date=trade_date,
                    freq=freq,
                )
                expected_codes = tuple(str(row[0]) for row in scope_rows)
                expected_all = connection.execute(
                    f"""
                    SELECT latest_ts_code
                    FROM {scope_relation}
                    WHERE trade_date={duckdb_string(trade_date)} AND freq={freq}
                    ORDER BY latest_ts_code
                    """
                ).fetchall()
                expected_all_codes = tuple(str(row[0]) for row in expected_all)
                canonical_codes = _canonical_bse_codes(
                    connection,
                    candidate_relation,
                    identity_path=identity_path,
                    trade_date=trade_date,
                )
                existing_canonical_codes = _canonical_bse_codes(
                    connection,
                    existing_relation,
                    identity_path=identity_path,
                    trade_date=trade_date,
                )
                if duplicate_count or scope_invalid_count:
                    raise BseMinuteRecoveryError(
                        f"Raw candidate contract failed: {trade_date}:{freq}"
                    )
                _assert_raw_candidate_bse_code_contract(
                    existing_codes=existing_canonical_codes,
                    candidate_codes=canonical_codes,
                    expected_codes=expected_all_codes,
                )
                if _non_bse_hash(connection, existing_relation) != _non_bse_hash(
                    connection, candidate_relation
                ):
                    raise BseMinuteRecoveryError(
                        f"Raw candidate changed non-BSE rows: {trade_date}:{freq}"
                    )
                os.replace(temporary, candidate_path)
                candidates.append(
                    {
                        "trade_date": trade_date,
                        "freq": freq,
                        "path": str(candidate_path),
                        "sha256": _sha256_file(candidate_path),
                        "row_count": row_count,
                        "missing_latest_code_count": len(expected_codes),
                        "target_fingerprint": summary["raw_target_fingerprint"],
                    }
                )
            except Exception as error:  # noqa: BLE001 - report bounded candidate failure.
                temporary.unlink(missing_ok=True)
                failure_samples.append(
                    {
                        "trade_date": trade_date,
                        "freq": freq,
                        "error_type": type(error).__name__,
                        "reason": str(error)[:300],
                    }
                )
                break

    candidate_report_hash = _hash_payload(
        {
            "plan_hash": plan["plan_hash"],
            "bundle_hash": bundle["bundle_hash"],
            "candidates": candidates,
        }
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "stage": "r1_raw_candidates",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan["plan_hash"],
        "bundle_hash": bundle["bundle_hash"],
        "candidate_report_hash": candidate_report_hash,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "failure_samples": failure_samples,
        "should_stop": bool(failure_samples),
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
    }
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def audit_bse_raw_recovery_candidates(
    *,
    plan_path: Path,
    bundle_path: Path,
    candidate_report_path: Path,
    duckdb_resource: DuckDBResource | None = None,
    output_path: Path | None = None,
) -> dict[str, object]:
    """Re-read R1 candidates and prove their frozen contracts."""

    started_at = perf_counter()
    plan = load_bse_stk_mins_recovery_plan(plan_path)
    bundle = load_bse_stk_mins_source_bundle(bundle_path)
    _assert_source_bundle_matches_plan(plan, bundle)
    report = _load_json(candidate_report_path, label="Raw candidate report")
    failures: list[dict[str, object]] = []
    if report.get("should_stop"):
        failures.append({"reason_code": "candidate_report_not_green"})
    if report.get("plan_hash") != plan["plan_hash"]:
        failures.append({"reason_code": "candidate_plan_hash_mismatch"})
    if report.get("bundle_hash") != bundle["bundle_hash"]:
        failures.append({"reason_code": "candidate_bundle_hash_mismatch"})
    observed_candidate_report_hash = _hash_payload(
        {
            "plan_hash": report.get("plan_hash"),
            "bundle_hash": report.get("bundle_hash"),
            "candidates": report.get("candidates") or [],
        }
    )
    if report.get("candidate_report_hash") != observed_candidate_report_hash:
        failures.append({"reason_code": "candidate_report_hash_mismatch"})
    expected_candidate_count = sum(
        1
        for row in bundle["frozen_bundle"]["mode_rows"]
        if row["mode"] == BseMinuteRecoveryMode.SOURCE_RECOVERABLE.value
    )
    if int(report.get("candidate_count") or 0) != expected_candidate_count:
        failures.append({"reason_code": "candidate_scope_count_mismatch"})
    resource = duckdb_resource or DuckDBResource()
    lake_root = Path(str(plan["frozen_payload"]["lake_root"]))
    _assert_output_outside_formal_lake(
        output_path,
        lake_root=lake_root,
        label="Raw candidate audit report",
    )
    identity_path = silver_stock_identity_map_path(lake_root)
    scope_relation = _scope_manifest_relation(plan)
    candidate_root = Path(str(plan["scope_manifest_path"])).parent.resolve() / "raw"
    audited: list[dict[str, object]] = []
    with resource.connect() as connection:
        for candidate in report.get("candidates") or ():
            try:
                path = Path(str(candidate["path"]))
                if not path.resolve().is_relative_to(candidate_root):
                    raise BseMinuteRecoveryError(
                        "candidate escaped the plan staging root"
                    )
                if not path.is_file() or candidate["sha256"] != _sha256_file(path):
                    raise BseMinuteRecoveryError("candidate hash changed")
                _assert_fingerprint_unchanged(candidate["target_fingerprint"])
                trade_date = str(candidate["trade_date"])
                freq = int(candidate["freq"])
                relation = read_parquet(path, hive_partitioning=False)
                observed_schema = tuple(
                    (str(row[0]), str(row[1]).upper())
                    for row in connection.execute(
                        f"DESCRIBE SELECT * FROM {relation}"
                    ).fetchall()
                )
                expected_schema = tuple(
                    (column, RAW_COLUMN_TYPES[column]) for column in RAW_COLUMNS
                )
                if observed_schema != expected_schema:
                    raise BseMinuteRecoveryError("candidate schema mismatch")
                row_count, duplicate_count, scope_invalid_count = _candidate_stats(
                    connection, relation, trade_date=trade_date, freq=freq
                )
                expected_rows = connection.execute(
                    f"""
                    SELECT latest_ts_code FROM {scope_relation}
                    WHERE trade_date={duckdb_string(trade_date)} AND freq={freq}
                    ORDER BY latest_ts_code
                    """
                ).fetchall()
                expected = tuple(str(row[0]) for row in expected_rows)
                canonical = _canonical_bse_codes(
                    connection,
                    relation,
                    identity_path=identity_path,
                    trade_date=trade_date,
                )
                target = raw_stk_mins_path(lake_root, freq, trade_date)
                target_relation = read_parquet(target, hive_partitioning=False)
                existing_canonical = _canonical_bse_codes(
                    connection,
                    target_relation,
                    identity_path=identity_path,
                    trade_date=trade_date,
                )
                if duplicate_count or scope_invalid_count:
                    raise BseMinuteRecoveryError("candidate content audit failed")
                _assert_raw_candidate_bse_code_contract(
                    existing_codes=existing_canonical,
                    candidate_codes=canonical,
                    expected_codes=expected,
                )
                if _non_bse_hash(
                    connection, target_relation
                ) != _non_bse_hash(connection, relation):
                    raise BseMinuteRecoveryError("candidate non-BSE hash changed")
                audited.append(
                    {
                        "trade_date": trade_date,
                        "freq": freq,
                        "path": str(path),
                        "sha256": candidate["sha256"],
                        "row_count": row_count,
                        "target_fingerprint": candidate["target_fingerprint"],
                    }
                )
            except Exception as error:  # noqa: BLE001 - audit records bounded samples.
                failures.append(
                    {
                        "path": str(candidate.get("path")),
                        "error_type": type(error).__name__,
                        "reason": str(error)[:300],
                    }
                )
                break
    audit_hash = _hash_payload(
        {
            "plan_hash": plan["plan_hash"],
            "bundle_hash": bundle["bundle_hash"],
            "candidate_report_hash": report.get("candidate_report_hash"),
            "audited_candidates": audited,
        }
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "stage": "r1_raw_candidate_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan["plan_hash"],
        "bundle_hash": bundle["bundle_hash"],
        "candidate_report_hash": report.get("candidate_report_hash"),
        "audit_hash": audit_hash,
        "audited_candidate_count": len(audited),
        "audited_candidates": audited,
        "failure_samples": failures[:SAMPLE_LIMIT],
        "should_stop": bool(failures),
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
    }
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def promote_bse_raw_recovery_candidates(
    *,
    plan_path: Path,
    bundle_path: Path,
    audit_report_path: Path,
    confirm: bool,
    checkpoint_path: Path,
    output_path: Path | None = None,
) -> dict[str, object]:
    """Explicitly promote audited R1 candidates into formal Raw."""

    if not confirm:
        raise BseMinuteRecoveryError(
            "formal Raw promotion requires explicit confirmation"
        )
    plan = load_bse_stk_mins_recovery_plan(plan_path)
    bundle = load_bse_stk_mins_source_bundle(bundle_path)
    _assert_source_bundle_matches_plan(plan, bundle)
    lake_root = Path(str(plan["frozen_payload"]["lake_root"]))
    _assert_output_outside_formal_lake(
        output_path,
        lake_root=lake_root,
        label="Raw promotion report",
    )
    plan_root = Path(str(plan["scope_manifest_path"])).parent.resolve()
    if not checkpoint_path.resolve().is_relative_to(plan_root):
        raise BseMinuteRecoveryError(
            "Raw promotion checkpoint must remain under the plan staging root"
        )
    audit = _load_json(audit_report_path, label="Raw candidate audit")
    if audit.get("should_stop"):
        raise BseMinuteRecoveryError("Raw candidate audit is not green")
    if (
        audit.get("plan_hash") != plan["plan_hash"]
        or audit.get("bundle_hash") != bundle["bundle_hash"]
    ):
        raise BseMinuteRecoveryError("Raw candidate audit identity mismatch")
    observed_audit_hash = _hash_payload(
        {
            "plan_hash": audit.get("plan_hash"),
            "bundle_hash": audit.get("bundle_hash"),
            "candidate_report_hash": audit.get("candidate_report_hash"),
            "audited_candidates": audit.get("audited_candidates") or [],
        }
    )
    if audit.get("audit_hash") != observed_audit_hash:
        raise BseMinuteRecoveryError("Raw candidate audit hash mismatch")
    checkpoint = (
        _load_json(checkpoint_path, label="Raw promotion checkpoint")
        if checkpoint_path.is_file()
        else {
            "plan_hash": plan["plan_hash"],
            "bundle_hash": bundle["bundle_hash"],
            "promoted": [],
            "in_progress": None,
        }
    )
    if (
        checkpoint.get("plan_hash") != plan["plan_hash"]
        or checkpoint.get("bundle_hash") != bundle["bundle_hash"]
    ):
        raise BseMinuteRecoveryError("Raw promotion checkpoint identity mismatch")
    promoted = list(checkpoint.get("promoted") or ())
    completed = {(row["trade_date"], int(row["freq"])) for row in promoted}
    audited_candidates = {
        (str(candidate["trade_date"]), int(candidate["freq"])): candidate
        for candidate in audit.get("audited_candidates") or ()
    }
    in_progress = checkpoint.get("in_progress")
    if in_progress:
        interrupted_key = (
            str(in_progress["trade_date"]),
            int(in_progress["freq"]),
        )
        interrupted_target = raw_stk_mins_path(
            lake_root,
            interrupted_key[1],
            interrupted_key[0],
        )
        interrupted_candidate = audited_candidates.get(interrupted_key)
        if interrupted_candidate is None:
            raise BseMinuteRecoveryError(
                "an interrupted Raw promotion is absent from the frozen audit"
            )
        interrupted_source = Path(str(interrupted_candidate["path"]))
        target_is_promoted = (
            interrupted_target.is_file()
            and _sha256_file(interrupted_target) == in_progress["sha256"]
        )
        source_is_pending = (
            interrupted_source.is_file()
            and _sha256_file(interrupted_source) == in_progress["sha256"]
        )
        if target_is_promoted:
            promoted.append(
                {
                    "trade_date": interrupted_key[0],
                    "freq": interrupted_key[1],
                    "path": str(interrupted_target),
                    "sha256": in_progress["sha256"],
                }
            )
            completed.add(interrupted_key)
        elif source_is_pending:
            _assert_fingerprint_unchanged(interrupted_candidate["target_fingerprint"])
        else:
            raise BseMinuteRecoveryError(
                "an interrupted Raw promotion cannot be reconciled from source/target hashes"
            )
        _atomic_write_json(
            checkpoint_path,
            {
                "plan_hash": plan["plan_hash"],
                "bundle_hash": bundle["bundle_hash"],
                "promoted": promoted,
                "in_progress": None,
            },
        )
    for candidate in audit.get("audited_candidates") or ():
        key = (str(candidate["trade_date"]), int(candidate["freq"]))
        if key in completed:
            continue
        source = Path(str(candidate["path"]))
        if not source.is_file() or candidate["sha256"] != _sha256_file(source):
            raise BseMinuteRecoveryError(f"candidate changed before promote: {source}")
        _assert_fingerprint_unchanged(candidate["target_fingerprint"])
        target = raw_stk_mins_path(lake_root, key[1], key[0])
        if source.stat().st_dev != target.parent.stat().st_dev:
            raise BseMinuteRecoveryError(
                "candidate and formal Raw are not on one filesystem"
            )
        _atomic_write_json(
            checkpoint_path,
            {
                "plan_hash": plan["plan_hash"],
                "bundle_hash": bundle["bundle_hash"],
                "promoted": promoted,
                "in_progress": {
                    "trade_date": key[0],
                    "freq": key[1],
                    "sha256": candidate["sha256"],
                    "candidate_path": str(source),
                },
            },
        )
        os.replace(source, target)
        if _sha256_file(target) != candidate["sha256"]:
            raise BseMinuteRecoveryError(f"promoted Raw hash mismatch: {target}")
        promoted_row = {
            "trade_date": key[0],
            "freq": key[1],
            "path": str(target),
            "sha256": _sha256_file(target),
        }
        promoted.append(promoted_row)
        _atomic_write_json(
            checkpoint_path,
            {
                "plan_hash": plan["plan_hash"],
                "bundle_hash": bundle["bundle_hash"],
                "promoted": promoted,
                "in_progress": None,
            },
        )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "stage": "r1_raw_promote",
        "plan_hash": plan["plan_hash"],
        "bundle_hash": bundle["bundle_hash"],
        "promoted_count": len(promoted),
        "promoted": promoted,
        "should_stop": False,
    }
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def _load_r1_raw_promote_report(
    *,
    path: Path,
    plan: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    report = _load_json(path, label="R1 Raw promote report")
    if report.get("stage") != "r1_raw_promote" or report.get("should_stop"):
        raise BseMinuteRecoveryError("R1 Raw promote report is not complete")
    if report.get("plan_hash") != plan.get("plan_hash") or report.get(
        "bundle_hash"
    ) != bundle.get("bundle_hash"):
        raise BseMinuteRecoveryError("R1 Raw promote report identity mismatch")
    expected = {
        (str(row["trade_date"]), int(row["freq"]))
        for row in bundle["frozen_bundle"]["mode_rows"]
        if row["mode"] == BseMinuteRecoveryMode.SOURCE_RECOVERABLE.value
    }
    promoted_rows = tuple(report.get("promoted") or ())
    observed = {(str(row["trade_date"]), int(row["freq"])) for row in promoted_rows}
    if observed != expected or int(report.get("promoted_count") or 0) != len(expected):
        raise BseMinuteRecoveryError("R1 Raw promoted scope set is incomplete")
    lake_root = Path(str(plan["frozen_payload"]["lake_root"]))
    for row in promoted_rows:
        target = raw_stk_mins_path(
            lake_root,
            int(row["freq"]),
            str(row["trade_date"]),
        )
        if not target.is_file() or _sha256_file(target) != row.get("sha256"):
            raise BseMinuteRecoveryError(f"R1 promoted Raw changed: {target}")
    frozen = {
        "plan_hash": report.get("plan_hash"),
        "bundle_hash": report.get("bundle_hash"),
        "promoted": list(promoted_rows),
    }
    return report, _hash_payload(frozen)


def _r2_affected_keys(bundle: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (
                str(row["trade_date"]),
                int(row["freq"]),
            )
            for row in bundle["frozen_bundle"]["mode_rows"]
            if row["mode"]
            in {
                BseMinuteRecoveryMode.SOURCE_RECOVERABLE.value,
                BseMinuteRecoveryMode.SILVER_FALLBACK_RECOVERABLE.value,
            }
        )
    )


def _r2_file_fingerprints(
    *,
    lake_root: Path,
    trade_date: str,
) -> tuple[dict[str, object], dict[str, object]]:
    input_paths: dict[str, Path] = {
        **{
            f"raw_stk_mins:{freq}": raw_stk_mins_path(lake_root, freq, trade_date)
            for freq in SUPPORTED_FREQS
        },
        "silver_stock_identity_map": silver_stock_identity_map_path(lake_root),
        "silver_stock_daily": silver_stock_daily_path(lake_root, trade_date),
        "silver_stock_suspend_daily": silver_stock_suspend_daily_path(
            lake_root, trade_date
        ),
        "silver_stock_lifecycle": silver_stock_lifecycle_path(lake_root),
    }
    target_paths = {
        f"silver_stk_mins:{freq}": silver_stk_mins_path(lake_root, freq, trade_date)
        for freq in SUPPORTED_FREQS
    }
    input_fingerprints = {
        label: _file_fingerprint(path) for label, path in input_paths.items()
    }
    target_fingerprints = {
        label: _file_fingerprint(path) for label, path in target_paths.items()
    }
    for label, fingerprint in {
        **input_fingerprints,
        **target_fingerprints,
    }.items():
        if (
            not fingerprint.get("exists")
            or int(fingerprint.get("size_bytes") or 0) <= 0
        ):
            raise BseMinuteRecoveryError(
                f"R2 requires an existing non-empty file: {trade_date}:{label}"
            )
    return input_fingerprints, target_fingerprints


def _assert_fingerprint_set_unchanged(
    fingerprints: Mapping[str, object],
) -> None:
    for value in fingerprints.values():
        if not isinstance(value, Mapping):
            raise BseMinuteRecoveryError("invalid R2 fingerprint entry")
        _assert_fingerprint_unchanged(value)


def _silver_candidate_path(plan: Mapping[str, Any], trade_date: str, freq: int) -> Path:
    root = Path(str(plan["scope_manifest_path"])).parent
    return (
        root
        / "silver"
        / f"freq={freq}"
        / f"trade_date={trade_date}"
        / "part-000.parquet"
    )


def _restrict_silver_candidate_to_bse_scope(
    connection,
    *,
    target_path: Path,
    candidate_path: Path,
) -> None:
    """Keep formal non-BSE rows and take only recomputed BSE rows."""

    columns = ", ".join(
        f'"{column}"' for column in stk_mins_assets.STK_MINS_SILVER_COLUMNS
    )
    scoped_path = candidate_path.with_name(
        f".{candidate_path.name}.{uuid4().hex}.bse-scope.tmp"
    )
    scoped_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT {columns}
                FROM {read_parquet(target_path, hive_partitioning=False)}
                WHERE upper(trim(ts_code)) NOT LIKE '%.BJ'
                UNION ALL
                SELECT {columns}
                FROM {read_parquet(candidate_path, hive_partitioning=False)}
                WHERE upper(trim(ts_code)) LIKE '%.BJ'
                ORDER BY ts_code, trade_time
                """,
                scoped_path,
            )
        )
        os.replace(scoped_path, candidate_path)
    finally:
        scoped_path.unlink(missing_ok=True)


def _silver_relation_schema(connection, relation: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    )


def _silver_canonical_hash(connection, path: Path) -> tuple[str, int]:
    relation = read_parquet(path, hive_partitioning=False)
    columns = ", ".join(
        f'"{column}"' for column in stk_mins_assets.STK_MINS_SILVER_COLUMNS
    )
    row = connection.execute(
        f"""
        SELECT
          count(*) AS row_count,
          coalesce(sum(CAST(hash({columns}) AS HUGEINT)), 0) AS hash_sum,
          coalesce(bit_xor(hash({columns})), 0) AS hash_xor
        FROM {relation}
        """
    ).fetchone()
    schema = _silver_relation_schema(connection, relation)
    payload = {
        "schema": schema,
        "row_count": int(row[0] or 0),
        "hash_sum": str(row[1] or 0),
        "hash_xor": str(row[2] or 0),
    }
    return _hash_payload(payload), int(row[0] or 0)


def _silver_affected_codes(
    connection,
    *,
    old_path: Path,
    new_path: Path,
) -> tuple[str, ...]:
    key_columns = {"ts_code", "trade_time"}
    value_columns = tuple(
        column
        for column in stk_mins_assets.STK_MINS_SILVER_COLUMNS
        if column not in key_columns
    )
    value_changed = " OR ".join(
        f'old."{column}" IS DISTINCT FROM new."{column}"' for column in value_columns
    )
    rows = connection.execute(
        f"""
        WITH old AS (
          SELECT *, true AS present
          FROM {read_parquet(old_path, hive_partitioning=False)}
        ), new AS (
          SELECT *, true AS present
          FROM {read_parquet(new_path, hive_partitioning=False)}
        )
        SELECT DISTINCT coalesce(old.ts_code, new.ts_code) AS ts_code
        FROM old
        FULL OUTER JOIN new
          ON old.ts_code = new.ts_code
         AND old.trade_time = new.trade_time
        WHERE old.present IS NULL
           OR new.present IS NULL
           OR {value_changed}
        ORDER BY ts_code
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _assert_coarse_fallback_scopes_absent(
    *,
    connection,
    lake_root: Path,
    identity_path: Path,
    scope_relation: str,
    bundle: Mapping[str, Any],
    trade_date: str,
) -> None:
    for row in bundle["frozen_bundle"]["mode_rows"]:
        if str(row["trade_date"]) != trade_date or int(row["freq"]) == 1:
            continue
        if (
            row["mode"]
            != BseMinuteRecoveryMode.SILVER_FALLBACK_RECOVERABLE.value
        ):
            continue
        freq = int(row["freq"])
        missing_codes = tuple(
            str(value[0])
            for value in connection.execute(
                f"""
                SELECT latest_ts_code
                FROM {scope_relation}
                WHERE trade_date = {duckdb_string(trade_date)}
                  AND freq = {freq}
                  AND coverage_status = 'missing'
                  AND reason_code = ''
                ORDER BY latest_ts_code
                """
            ).fetchall()
        )
        if not missing_codes:
            raise BseMinuteRecoveryError(
                f"coarse fallback scope has no frozen missing codes: {trade_date}:{freq}"
            )
        coverage = _existing_coverage(
            connection=connection,
            raw_path=raw_stk_mins_path(lake_root, freq, trade_date),
            identity_path=identity_path,
            trade_date=trade_date,
            freq=freq,
            expected_latest_codes=missing_codes,
        )
        if coverage:
            samples = sorted(coverage)[:SAMPLE_LIMIT]
            raise BseMinuteRecoveryError(
                "coarse fallback target contains existing BSE code-days: "
                f"{trade_date}:{freq}:{samples}"
            )


def _r2_checkpoint_path(plan: Mapping[str, Any], name: str) -> Path:
    return Path(str(plan["scope_manifest_path"])).parent / name


def _load_or_initialize_r2_checkpoint(
    *,
    path: Path,
    plan_hash: str,
    bundle_hash: str,
    raw_promote_hash: str,
    row_field: str,
) -> dict[str, Any]:
    checkpoint = (
        _load_json(path, label=f"R2 {row_field} checkpoint")
        if path.is_file()
        else {
            "plan_hash": plan_hash,
            "bundle_hash": bundle_hash,
            "raw_promote_hash": raw_promote_hash,
            row_field: [],
        }
    )
    if (
        checkpoint.get("plan_hash") != plan_hash
        or checkpoint.get("bundle_hash") != bundle_hash
        or checkpoint.get("raw_promote_hash") != raw_promote_hash
    ):
        raise BseMinuteRecoveryError(f"R2 {row_field} checkpoint identity mismatch")
    if not isinstance(checkpoint.get(row_field), list):
        raise BseMinuteRecoveryError(f"R2 {row_field} checkpoint rows are invalid")
    return checkpoint


def build_bse_silver_recovery_candidates(
    *,
    plan_path: Path,
    bundle_path: Path,
    raw_promote_report_path: Path,
    duckdb_resource: DuckDBResource | None = None,
    max_date_count: int | None = None,
    output_path: Path | None = None,
) -> dict[str, object]:
    """R2: rebuild the exact recoverable Silver date/frequency scopes."""

    started_at = perf_counter()
    if max_date_count is not None and max_date_count <= 0:
        raise ValueError("max_date_count must be positive")
    plan = load_bse_stk_mins_recovery_plan(plan_path)
    bundle = load_bse_stk_mins_source_bundle(bundle_path)
    _assert_source_bundle_matches_plan(plan, bundle)
    _raw_report, raw_promote_hash = _load_r1_raw_promote_report(
        path=raw_promote_report_path,
        plan=plan,
        bundle=bundle,
    )
    lake_root = Path(str(plan["frozen_payload"]["lake_root"]))
    _assert_output_outside_formal_lake(
        output_path,
        lake_root=lake_root,
        label="Silver candidate report",
    )
    affected_keys = _r2_affected_keys(bundle)
    affected_dates = tuple(sorted({trade_date for trade_date, _freq in affected_keys}))
    frequencies_by_date = {
        trade_date: tuple(
            freq for date, freq in affected_keys if date == trade_date
        )
        for trade_date in affected_dates
    }
    fallback_keys = {
        (str(row["trade_date"]), int(row["freq"]))
        for row in bundle["frozen_bundle"]["mode_rows"]
        if row["mode"]
        == BseMinuteRecoveryMode.SILVER_FALLBACK_RECOVERABLE.value
    }
    expected_candidate_count = len(affected_keys)
    candidate_root = Path(str(plan["scope_manifest_path"])).parent / "silver"
    checkpoint_path = _r2_checkpoint_path(plan, "silver-candidate-checkpoint.json")
    checkpoint = _load_or_initialize_r2_checkpoint(
        path=checkpoint_path,
        plan_hash=str(plan["plan_hash"]),
        bundle_hash=str(bundle["bundle_hash"]),
        raw_promote_hash=raw_promote_hash,
        row_field="candidates",
    )
    candidates = list(checkpoint["candidates"])
    completed = {(str(row["trade_date"]), int(row["freq"])) for row in candidates}
    expected_keys = set(affected_keys)
    if not completed.issubset(expected_keys):
        raise BseMinuteRecoveryError("Silver candidate checkpoint escaped R2 scope")
    for row in candidates:
        path = Path(str(row["path"]))
        if not path.resolve().is_relative_to(candidate_root.resolve()):
            raise BseMinuteRecoveryError("Silver candidate escaped plan staging root")
        if _file_fingerprint(path) != row.get("candidate_fingerprint"):
            raise BseMinuteRecoveryError(
                f"checkpointed Silver candidate changed: {path}"
            )
        _assert_fingerprint_set_unchanged(row["input_fingerprints"])
        _assert_fingerprint_unchanged(row["target_fingerprint"])

    pending_dates = tuple(
        trade_date
        for trade_date in affected_dates
        if any(
            (trade_date, freq) not in completed
            for freq in frequencies_by_date[trade_date]
        )
    )
    selected_dates = (
        pending_dates[:max_date_count] if max_date_count is not None else pending_dates
    )
    resource = duckdb_resource or DuckDBResource()
    failures: list[dict[str, object]] = []
    identity_path = silver_stock_identity_map_path(lake_root)

    with resource.connect() as connection:
        for trade_date in selected_dates:
            try:
                input_fingerprints, target_fingerprints = _r2_file_fingerprints(
                    lake_root=lake_root,
                    trade_date=trade_date,
                )
                expected_codes = _load_expected_latest_codes(
                    connection,
                    silver_stock_daily_path(lake_root, trade_date),
                )
                date_frequencies = frequencies_by_date[trade_date]
                date_fallback_keys = {
                    (trade_date, freq)
                    for freq in date_frequencies
                    if (trade_date, freq) in fallback_keys
                }
                eligibility = None
                if date_fallback_keys:
                    eligibility = audit_bse_one_minute_fallback_eligibility(
                        lake_root=lake_root,
                        trade_date=trade_date,
                        expected_latest_codes=expected_codes,
                        duckdb_resource=resource,
                    )
                    if not eligibility.passed:
                        raise BseMinuteRecoveryError(
                            "1m fallback eligibility failed: "
                            f"{trade_date}:{eligibility.to_dict()}"
                        )
                    _assert_coarse_fallback_scopes_absent(
                        connection=connection,
                        lake_root=lake_root,
                        identity_path=identity_path,
                        scope_relation=_scope_manifest_relation(plan),
                        bundle=bundle,
                        trade_date=trade_date,
                    )
                for freq in date_frequencies:
                    key = (trade_date, freq)
                    if key in completed:
                        continue
                    target_path = silver_stk_mins_path(lake_root, freq, trade_date)
                    candidate_path = _silver_candidate_path(plan, trade_date, freq)
                    if candidate_path.exists():
                        candidate_path.unlink()
                    write_result = stk_mins_assets.write_silver_stk_mins_partition(
                        lake_root=lake_root,
                        duckdb=resource,
                        freq=freq,
                        partition_key=trade_date,
                        output_path_override=candidate_path,
                    )
                    _restrict_silver_candidate_to_bse_scope(
                        connection,
                        target_path=target_path,
                        candidate_path=candidate_path,
                    )
                    diagnostics = evaluate_silver_stk_mins_partition_diagnostics(
                        lake_root=lake_root,
                        duckdb=resource,
                        freq=freq,
                        partition_key=trade_date,
                        silver_path=candidate_path,
                    )
                    if not diagnostics.passed:
                        raise BseMinuteRecoveryError(
                            "Silver candidate failed current diagnostics: "
                            f"{trade_date}:{freq}:{list(diagnostics.failed_rule_names)}"
                        )
                    _assert_fingerprint_set_unchanged(input_fingerprints)
                    target_fingerprint = target_fingerprints[f"silver_stk_mins:{freq}"]
                    _assert_fingerprint_unchanged(target_fingerprint)
                    old_hash, old_row_count = _silver_canonical_hash(
                        connection, target_path
                    )
                    new_hash, new_row_count = _silver_canonical_hash(
                        connection, candidate_path
                    )
                    affected_codes = _silver_affected_codes(
                        connection,
                        old_path=target_path,
                        new_path=candidate_path,
                    )
                    non_bse_codes = tuple(
                        code for code in affected_codes if not code.endswith(".BJ")
                    )
                    if non_bse_codes:
                        raise BseMinuteRecoveryError(
                            "Silver candidate changed non-BSE codes: "
                            f"{trade_date}:{freq}:{non_bse_codes[:SAMPLE_LIMIT]}"
                        )
                    changed = old_hash != new_hash
                    if changed != bool(affected_codes):
                        raise BseMinuteRecoveryError(
                            f"Silver candidate hash/diff mismatch: {trade_date}:{freq}"
                        )
                    candidate_row: dict[str, object] = {
                        "trade_date": trade_date,
                        "freq": freq,
                        "path": str(candidate_path),
                        "sha256": _sha256_file(candidate_path),
                        "candidate_fingerprint": _file_fingerprint(candidate_path),
                        "input_fingerprints": input_fingerprints,
                        "target_fingerprint": target_fingerprint,
                        "old_canonical_hash": old_hash,
                        "new_canonical_hash": new_hash,
                        "old_row_count": old_row_count,
                        "new_row_count": new_row_count,
                        "changed": changed,
                        "affected_latest_code_count": len(affected_codes),
                        "affected_latest_code_hash": _hash_payload(affected_codes),
                        "eligibility": (
                            eligibility.to_dict() if eligibility is not None else None
                        ),
                        "write_result": {
                            "source_row_count": write_result.source_row_count,
                            "mapped_row_count": write_result.mapped_row_count,
                            "duplicate_removed_count": write_result.duplicate_removed_count,
                            "full_day_suspend_deleted_row_count": write_result.full_day_suspend_deleted_row_count,
                            "price_correction_row_count": write_result.price_correction_row_count,
                            "recomputed_row_count": write_result.recomputed_row_count,
                            "missing_source_fallback_row_count": write_result.missing_source_fallback_row_count,
                            "vol_amount_normalized_row_count": write_result.vol_amount_normalized_row_count,
                            "row_count": write_result.row_count,
                        },
                        "diagnostics": diagnostics.to_dict(),
                    }
                    candidates.append(candidate_row)
                    completed.add(key)
                    _atomic_write_json(
                        checkpoint_path,
                        {
                            "plan_hash": plan["plan_hash"],
                            "bundle_hash": bundle["bundle_hash"],
                            "raw_promote_hash": raw_promote_hash,
                            "candidates": candidates,
                        },
                    )
            except Exception as error:  # noqa: BLE001 - bounded R2 failure report.
                failures.append(
                    {
                        "trade_date": trade_date,
                        "error_type": type(error).__name__,
                        "reason": str(error)[:500],
                    }
                )
                break

    candidates.sort(key=lambda row: (str(row["trade_date"]), int(row["freq"])))
    complete = len(candidates) == expected_candidate_count and not failures
    candidate_report_hash = _hash_payload(
        {
            "plan_hash": plan["plan_hash"],
            "bundle_hash": bundle["bundle_hash"],
            "raw_promote_hash": raw_promote_hash,
            "candidates": candidates,
        }
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "stage": "r2_silver_candidates",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan["plan_hash"],
        "bundle_hash": bundle["bundle_hash"],
        "raw_promote_hash": raw_promote_hash,
        "candidate_report_hash": candidate_report_hash,
        "affected_date_count": len(affected_dates),
        "affected_scope_count": len(affected_keys),
        "expected_candidate_count": expected_candidate_count,
        "candidate_count": len(candidates),
        "changed_candidate_count": sum(bool(row["changed"]) for row in candidates),
        "candidates": candidates,
        "complete": complete,
        "failure_samples": failures[:SAMPLE_LIMIT],
        "should_stop": bool(failures),
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
    }
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def audit_bse_silver_recovery_candidates(
    *,
    plan_path: Path,
    bundle_path: Path,
    raw_promote_report_path: Path,
    candidate_report_path: Path,
    duckdb_resource: DuckDBResource | None = None,
    max_candidate_count: int | None = None,
    output_path: Path | None = None,
) -> dict[str, object]:
    """R2: re-read bounded Silver candidates and freeze only real changes."""

    started_at = perf_counter()
    if max_candidate_count is not None and max_candidate_count <= 0:
        raise ValueError("max_candidate_count must be positive")
    plan = load_bse_stk_mins_recovery_plan(plan_path)
    bundle = load_bse_stk_mins_source_bundle(bundle_path)
    _assert_source_bundle_matches_plan(plan, bundle)
    _raw_report, raw_promote_hash = _load_r1_raw_promote_report(
        path=raw_promote_report_path,
        plan=plan,
        bundle=bundle,
    )
    report = _load_json(candidate_report_path, label="Silver candidate report")
    if report.get("should_stop") or report.get("complete") is not True:
        raise BseMinuteRecoveryError("Silver candidate report is not complete")
    if (
        report.get("plan_hash") != plan["plan_hash"]
        or report.get("bundle_hash") != bundle["bundle_hash"]
        or report.get("raw_promote_hash") != raw_promote_hash
    ):
        raise BseMinuteRecoveryError("Silver candidate report identity mismatch")
    observed_report_hash = _hash_payload(
        {
            "plan_hash": report.get("plan_hash"),
            "bundle_hash": report.get("bundle_hash"),
            "raw_promote_hash": report.get("raw_promote_hash"),
            "candidates": report.get("candidates") or [],
        }
    )
    if report.get("candidate_report_hash") != observed_report_hash:
        raise BseMinuteRecoveryError("Silver candidate report hash mismatch")
    lake_root = Path(str(plan["frozen_payload"]["lake_root"]))
    _assert_output_outside_formal_lake(
        output_path,
        lake_root=lake_root,
        label="Silver candidate audit report",
    )
    checkpoint_path = _r2_checkpoint_path(plan, "silver-audit-checkpoint.json")
    checkpoint = _load_or_initialize_r2_checkpoint(
        path=checkpoint_path,
        plan_hash=str(plan["plan_hash"]),
        bundle_hash=str(bundle["bundle_hash"]),
        raw_promote_hash=raw_promote_hash,
        row_field="audited_candidates",
    )
    if checkpoint.get("candidate_report_hash") not in {
        None,
        report["candidate_report_hash"],
    }:
        raise BseMinuteRecoveryError("Silver audit checkpoint candidate mismatch")
    audited = list(checkpoint["audited_candidates"])
    completed = {(str(row["trade_date"]), int(row["freq"])) for row in audited}
    candidates = tuple(report.get("candidates") or ())
    pending = tuple(
        row
        for row in candidates
        if (str(row["trade_date"]), int(row["freq"])) not in completed
    )
    selected = (
        pending[:max_candidate_count] if max_candidate_count is not None else pending
    )
    resource = duckdb_resource or DuckDBResource()
    failures: list[dict[str, object]] = []
    with resource.connect() as connection:
        for candidate in selected:
            if perf_counter() - started_at > AUDIT_TIMEOUT_SECONDS:
                failures.append({"reason_code": "audit_timeout"})
                break
            try:
                trade_date = str(candidate["trade_date"])
                freq = int(candidate["freq"])
                candidate_path = Path(str(candidate["path"]))
                if (
                    not candidate_path.is_file()
                    or _sha256_file(candidate_path) != candidate["sha256"]
                ):
                    raise BseMinuteRecoveryError("Silver candidate hash changed")
                _assert_fingerprint_set_unchanged(candidate["input_fingerprints"])
                _assert_fingerprint_unchanged(candidate["target_fingerprint"])
                diagnostics = evaluate_silver_stk_mins_partition_diagnostics(
                    lake_root=lake_root,
                    duckdb=resource,
                    freq=freq,
                    partition_key=trade_date,
                    silver_path=candidate_path,
                )
                if not diagnostics.passed:
                    raise BseMinuteRecoveryError(
                        f"Silver candidate diagnostics changed: {list(diagnostics.failed_rule_names)}"
                    )
                target_path = silver_stk_mins_path(lake_root, freq, trade_date)
                old_hash, old_count = _silver_canonical_hash(connection, target_path)
                new_hash, new_count = _silver_canonical_hash(connection, candidate_path)
                affected_codes = _silver_affected_codes(
                    connection,
                    old_path=target_path,
                    new_path=candidate_path,
                )
                if any(not code.endswith(".BJ") for code in affected_codes):
                    raise BseMinuteRecoveryError("Silver audit found non-BSE changes")
                observed = {
                    "old_canonical_hash": old_hash,
                    "new_canonical_hash": new_hash,
                    "old_row_count": old_count,
                    "new_row_count": new_count,
                    "changed": old_hash != new_hash,
                    "affected_latest_code_count": len(affected_codes),
                    "affected_latest_code_hash": _hash_payload(affected_codes),
                }
                for field, value in observed.items():
                    if candidate.get(field) != value:
                        raise BseMinuteRecoveryError(
                            f"Silver candidate audit field changed: {field}"
                        )
                audited_row = dict(candidate)
                audited_row["diagnostics"] = diagnostics.to_dict()
                audited.append(audited_row)
                completed.add((trade_date, freq))
                _atomic_write_json(
                    checkpoint_path,
                    {
                        "plan_hash": plan["plan_hash"],
                        "bundle_hash": bundle["bundle_hash"],
                        "raw_promote_hash": raw_promote_hash,
                        "candidate_report_hash": report["candidate_report_hash"],
                        "audited_candidates": audited,
                    },
                )
            except Exception as error:  # noqa: BLE001 - bounded audit report.
                failures.append(
                    {
                        "path": str(candidate.get("path")),
                        "error_type": type(error).__name__,
                        "reason": str(error)[:500],
                    }
                )
                break

    audited.sort(key=lambda row: (str(row["trade_date"]), int(row["freq"])))
    complete = len(audited) == len(candidates) and not failures
    changed_rows = tuple(
        {
            "trade_date": row["trade_date"],
            "freq": row["freq"],
            "candidate_path": row["path"],
            "candidate_sha256": row["sha256"],
            "target_fingerprint": row["target_fingerprint"],
            "old_canonical_hash": row["old_canonical_hash"],
            "new_canonical_hash": row["new_canonical_hash"],
            "old_row_count": row["old_row_count"],
            "new_row_count": row["new_row_count"],
            "affected_latest_code_count": row["affected_latest_code_count"],
            "affected_latest_code_hash": row["affected_latest_code_hash"],
        }
        for row in audited
        if row["changed"]
    )
    audit_hash = _hash_payload(
        {
            "plan_hash": plan["plan_hash"],
            "bundle_hash": bundle["bundle_hash"],
            "raw_promote_hash": raw_promote_hash,
            "candidate_report_hash": report["candidate_report_hash"],
            "audited_candidates": audited,
            "changed_silver_rows": changed_rows,
        }
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "stage": "r2_silver_candidate_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan["plan_hash"],
        "bundle_hash": bundle["bundle_hash"],
        "raw_promote_hash": raw_promote_hash,
        "candidate_report_hash": report["candidate_report_hash"],
        "audit_hash": audit_hash,
        "expected_candidate_count": len(candidates),
        "audited_candidate_count": len(audited),
        "changed_silver_count": len(changed_rows),
        "audited_candidates": audited,
        "changed_silver_rows": list(changed_rows),
        "complete": complete,
        "failure_samples": failures[:SAMPLE_LIMIT],
        "should_stop": bool(failures),
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
    }
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def promote_bse_silver_recovery_candidates(
    *,
    plan_path: Path,
    bundle_path: Path,
    raw_promote_report_path: Path,
    audit_report_path: Path,
    confirm: bool,
    checkpoint_path: Path,
    changed_manifest_path: Path,
    duckdb_resource: DuckDBResource | None = None,
    output_path: Path | None = None,
) -> dict[str, object]:
    """R2: promote only hash-changing Silver candidates and freeze their manifest."""

    if not confirm:
        raise BseMinuteRecoveryError(
            "formal Silver promotion requires explicit confirmation"
        )
    started_at = perf_counter()
    plan = load_bse_stk_mins_recovery_plan(plan_path)
    bundle = load_bse_stk_mins_source_bundle(bundle_path)
    _assert_source_bundle_matches_plan(plan, bundle)
    _raw_report, raw_promote_hash = _load_r1_raw_promote_report(
        path=raw_promote_report_path,
        plan=plan,
        bundle=bundle,
    )
    lake_root = Path(str(plan["frozen_payload"]["lake_root"]))
    plan_root = Path(str(plan["scope_manifest_path"])).parent.resolve()
    for path, label in (
        (checkpoint_path, "Silver promote checkpoint"),
        (changed_manifest_path, "changed Silver manifest"),
    ):
        if not path.resolve().is_relative_to(plan_root):
            raise BseMinuteRecoveryError(f"{label} must remain under plan staging")
    _assert_output_outside_formal_lake(
        output_path,
        lake_root=lake_root,
        label="Silver promotion report",
    )
    audit = _load_json(audit_report_path, label="Silver candidate audit")
    if audit.get("should_stop") or audit.get("complete") is not True:
        raise BseMinuteRecoveryError("Silver candidate audit is not complete")
    if (
        audit.get("plan_hash") != plan["plan_hash"]
        or audit.get("bundle_hash") != bundle["bundle_hash"]
        or audit.get("raw_promote_hash") != raw_promote_hash
    ):
        raise BseMinuteRecoveryError("Silver candidate audit identity mismatch")
    observed_audit_hash = _hash_payload(
        {
            "plan_hash": audit.get("plan_hash"),
            "bundle_hash": audit.get("bundle_hash"),
            "raw_promote_hash": audit.get("raw_promote_hash"),
            "candidate_report_hash": audit.get("candidate_report_hash"),
            "audited_candidates": audit.get("audited_candidates") or [],
            "changed_silver_rows": audit.get("changed_silver_rows") or [],
        }
    )
    if audit.get("audit_hash") != observed_audit_hash:
        raise BseMinuteRecoveryError("Silver candidate audit hash mismatch")
    changed_rows = tuple(audit.get("changed_silver_rows") or ())
    checkpoint = (
        _load_json(checkpoint_path, label="Silver promotion checkpoint")
        if checkpoint_path.is_file()
        else {
            "plan_hash": plan["plan_hash"],
            "bundle_hash": bundle["bundle_hash"],
            "raw_promote_hash": raw_promote_hash,
            "audit_hash": audit["audit_hash"],
            "promoted": [],
            "in_progress": None,
        }
    )
    if (
        checkpoint.get("plan_hash") != plan["plan_hash"]
        or checkpoint.get("bundle_hash") != bundle["bundle_hash"]
        or checkpoint.get("raw_promote_hash") != raw_promote_hash
        or checkpoint.get("audit_hash") != audit["audit_hash"]
    ):
        raise BseMinuteRecoveryError("Silver promotion checkpoint identity mismatch")
    promoted = list(checkpoint.get("promoted") or ())
    completed = {(str(row["trade_date"]), int(row["freq"])) for row in promoted}
    changed_by_key = {
        (str(row["trade_date"]), int(row["freq"])): row for row in changed_rows
    }
    resource = duckdb_resource or DuckDBResource()
    in_progress = checkpoint.get("in_progress")
    if in_progress:
        key = (str(in_progress["trade_date"]), int(in_progress["freq"]))
        changed = changed_by_key.get(key)
        if changed is None:
            raise BseMinuteRecoveryError(
                "interrupted Silver promotion is absent from frozen audit"
            )
        target = silver_stk_mins_path(lake_root, key[1], key[0])
        candidate = Path(str(changed["candidate_path"]))
        target_promoted = (
            target.is_file() and _sha256_file(target) == in_progress["sha256"]
        )
        candidate_pending = (
            candidate.is_file() and _sha256_file(candidate) == in_progress["sha256"]
        )
        if target_promoted:
            promoted.append(
                {
                    "trade_date": key[0],
                    "freq": key[1],
                    "path": str(target),
                    "sha256": in_progress["sha256"],
                    "new_canonical_hash": changed["new_canonical_hash"],
                }
            )
            completed.add(key)
        elif candidate_pending:
            _assert_fingerprint_unchanged(changed["target_fingerprint"])
        else:
            raise BseMinuteRecoveryError(
                "interrupted Silver promotion cannot be reconciled"
            )
        _atomic_write_json(
            checkpoint_path,
            {
                "plan_hash": plan["plan_hash"],
                "bundle_hash": bundle["bundle_hash"],
                "raw_promote_hash": raw_promote_hash,
                "audit_hash": audit["audit_hash"],
                "promoted": promoted,
                "in_progress": None,
            },
        )

    for changed in changed_rows:
        key = (str(changed["trade_date"]), int(changed["freq"]))
        if key in completed:
            continue
        candidate = Path(str(changed["candidate_path"]))
        if (
            not candidate.is_file()
            or _sha256_file(candidate) != changed["candidate_sha256"]
        ):
            raise BseMinuteRecoveryError(f"Silver candidate changed: {candidate}")
        _assert_fingerprint_unchanged(changed["target_fingerprint"])
        target = silver_stk_mins_path(lake_root, key[1], key[0])
        if candidate.stat().st_dev != target.parent.stat().st_dev:
            raise BseMinuteRecoveryError(
                "Silver candidate and formal target are not on one filesystem"
            )
        _atomic_write_json(
            checkpoint_path,
            {
                "plan_hash": plan["plan_hash"],
                "bundle_hash": bundle["bundle_hash"],
                "raw_promote_hash": raw_promote_hash,
                "audit_hash": audit["audit_hash"],
                "promoted": promoted,
                "in_progress": {
                    "trade_date": key[0],
                    "freq": key[1],
                    "sha256": changed["candidate_sha256"],
                },
            },
        )
        os.replace(candidate, target)
        if _sha256_file(target) != changed["candidate_sha256"]:
            raise BseMinuteRecoveryError(f"promoted Silver hash mismatch: {target}")
        with resource.connect() as connection:
            canonical_hash, _row_count = _silver_canonical_hash(connection, target)
        if canonical_hash != changed["new_canonical_hash"]:
            raise BseMinuteRecoveryError(
                f"promoted Silver canonical hash mismatch: {target}"
            )
        promoted.append(
            {
                "trade_date": key[0],
                "freq": key[1],
                "path": str(target),
                "sha256": changed["candidate_sha256"],
                "new_canonical_hash": canonical_hash,
            }
        )
        completed.add(key)
        _atomic_write_json(
            checkpoint_path,
            {
                "plan_hash": plan["plan_hash"],
                "bundle_hash": bundle["bundle_hash"],
                "raw_promote_hash": raw_promote_hash,
                "audit_hash": audit["audit_hash"],
                "promoted": promoted,
                "in_progress": None,
            },
        )

    with resource.connect() as connection:
        for row in audit.get("audited_candidates") or ():
            key = (str(row["trade_date"]), int(row["freq"]))
            target = silver_stk_mins_path(lake_root, key[1], key[0])
            canonical_hash, _row_count = _silver_canonical_hash(connection, target)
            expected_hash = row["new_canonical_hash"]
            if canonical_hash != expected_hash:
                raise BseMinuteRecoveryError(
                    f"formal Silver post-promote mismatch: {target}"
                )
            candidate = Path(str(row["path"]))
            candidate.unlink(missing_ok=True)

    frozen_manifest = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "stage": "r2_actual_changed_silver_manifest",
        "plan_hash": plan["plan_hash"],
        "bundle_hash": bundle["bundle_hash"],
        "raw_promote_hash": raw_promote_hash,
        "audit_hash": audit["audit_hash"],
        "changed_silver_count": len(changed_rows),
        "changed_silver_rows": [
            {
                "trade_date": row["trade_date"],
                "freq": row["freq"],
                "path": str(
                    silver_stk_mins_path(
                        lake_root, int(row["freq"]), str(row["trade_date"])
                    )
                ),
                "old_canonical_hash": row["old_canonical_hash"],
                "new_canonical_hash": row["new_canonical_hash"],
                "old_row_count": row["old_row_count"],
                "new_row_count": row["new_row_count"],
                "affected_latest_code_count": row["affected_latest_code_count"],
                "affected_latest_code_hash": row["affected_latest_code_hash"],
            }
            for row in changed_rows
        ],
    }
    manifest_payload = {
        **frozen_manifest,
        "manifest_hash": _hash_payload(frozen_manifest),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "should_stop": False,
    }
    _atomic_write_json(changed_manifest_path, manifest_payload)
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": RECOVERY_KIND,
        "stage": "r2_silver_promote",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan["plan_hash"],
        "bundle_hash": bundle["bundle_hash"],
        "raw_promote_hash": raw_promote_hash,
        "audit_hash": audit["audit_hash"],
        "promoted_count": len(promoted),
        "promoted": promoted,
        "changed_manifest_path": str(changed_manifest_path),
        "changed_manifest_hash": manifest_payload["manifest_hash"],
        "should_stop": False,
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
    }
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def parse_scope_file(path: Path) -> tuple[BseMinuteRecoveryScope, ...]:
    payload = _load_json(path, label="BSE recovery scope file")
    rows = payload.get("scopes")
    if not isinstance(rows, list):
        raise BseMinuteRecoveryError("scope file must contain a scopes list")
    return tuple(
        BseMinuteRecoveryScope(
            trade_date=str(row["trade_date"]),
            freq=int(row["freq"]),
        )
        for row in rows
    )
