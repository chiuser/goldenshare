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
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_stk_mins_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
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
        return (
            f"{self.source_ts_code}:{self.freq}:"
            f"{self.start_date}:{self.end_date}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_ts_code": self.source_ts_code,
            "freq": self.freq,
            "trade_dates": list(self.trade_dates),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "window_id": self.window_id,
        }


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
    if (
        lake == staging
        or staging.is_relative_to(lake)
        or lake.is_relative_to(staging)
    ):
        raise BseMinuteRecoveryError("recovery staging must be outside the formal lake root")
    if lake == Path("/Volumes/datasource/goldenshare-tushare-lake").resolve():
        raise BseMinuteRecoveryError("legacy lake root is forbidden for Dagster recovery")
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
        return {"path": str(path), "exists": False, "size_bytes": None, "mtime_ns": None}
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
                "INSERT INTO bse_scope VALUES ("
                + ", ".join("?" for _ in schema)
                + ")",
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
        self_aliases = sorted({source for source, _origin in active if source == latest})
        if len(bse_aliases) == 1:
            aliases[latest] = (bse_aliases[0], "bse_mapping")
        elif len(bse_aliases) > 1:
            failures[latest] = "multiple_active_bse_aliases"
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
          count(*) FILTER (WHERE trade_clock NOT IN ({expected_times})) AS invalid_time_count
        FROM mapped
        GROUP BY latest_ts_code
        ORDER BY latest_ts_code
        """
    ).fetchall()
    expected_count = EXPECTED_BAR_COUNT_BY_FREQ[freq]
    coverage: dict[str, tuple[tuple[str, ...], int, str]] = {}
    for latest, source_codes, row_count, distinct_time_count, invalid_time_count in rows:
        count = int(row_count)
        status = (
            "covered"
            if count == expected_count
            and int(distinct_time_count) == expected_count
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
        code for code, (_sources, _count, status) in coverage.items() if status == "covered"
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
            identity_rows = _active_identity_rows(connection, identity_path, scope.trade_date)
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
                sorted(code for code, (_sources, _count, status) in coverage.items() if status == "partial")
            )
            covered_codes = tuple(
                sorted(code for code, (_sources, _count, status) in coverage.items() if status == "covered")
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


def _source_windows(scope_rows: Sequence[Mapping[str, object]]) -> tuple[BseSourceWindow, ...]:
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
        connection.execute(copy_query_to_parquet("SELECT * FROM source_page", target_path))


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
            raise BseMinuteRecoveryError(f"source page escaped its window root: {page_path}")
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
    start_datetime = f"{window.start_date} 09:00:00"
    end_datetime = f"{window.end_date} 19:00:00"
    request_contract = {
        "api_name": "stk_mins",
        "ts_code": window.source_ts_code,
        "freq": f"{window.freq}min",
        "start_date": start_datetime,
        "end_date": end_datetime,
        "limit": SOURCE_PAGE_LIMIT,
        "fields": list(RAW_COLUMNS),
    }

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
            raise BseMinuteRecoveryError(f"source window appeared concurrently: {final_root}")
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
) -> tuple[int, tuple[str, ...], int]:
    missing_rows = tuple(
        row
        for row in scope_rows
        if str(row["trade_date"]) == trade_date
        and int(row["freq"]) == freq
        and row["coverage_status"] == "missing"
        and not row["reason_code"]
    )
    aliases = tuple(sorted(str(row["preferred_source_ts_code"]) for row in missing_rows))
    page_paths = tuple(
        Path(str(page["path"]))
        for sidecar in window_sidecars
        if int(sidecar["window"]["freq"]) == freq
        and trade_date in sidecar["window"]["trade_dates"]
        for page in sidecar.get("pages") or ()
    )
    if not page_paths:
        return 0, (), 0
    relation = _relation_for_paths(page_paths)
    aliases_sql = ", ".join(duckdb_string(value) for value in aliases)
    expected_times = ", ".join(
        duckdb_string(value) for value in _expected_session_times(freq)
    )
    rows = connection.execute(
        f"""
        SELECT
          upper(trim(CAST(ts_code AS VARCHAR))) AS source_ts_code,
          count(*) AS row_count,
          count(DISTINCT strftime(CAST(trade_time AS TIMESTAMP), '%H:%M:%S')) AS distinct_time_count,
          count(*) FILTER (
            WHERE strftime(CAST(trade_time AS TIMESTAMP), '%H:%M:%S') NOT IN ({expected_times})
          ) AS invalid_time_count,
          count(*) FILTER (
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR vol IS NULL OR amount IS NULL OR vol < 0 OR amount < 0
               OR high < greatest(open, close, low)
               OR low > least(open, close, high)
          ) AS invalid_value_count
        FROM {relation}
        WHERE CAST(trade_time AS DATE) = CAST({duckdb_string(trade_date)} AS DATE)
          AND upper(trim(CAST(ts_code AS VARCHAR))) IN ({aliases_sql})
        GROUP BY source_ts_code
        ORDER BY source_ts_code
        """
    ).fetchall()
    complete = tuple(
        str(source)
        for source, row_count, distinct_count, invalid_time, invalid_value in rows
        if int(row_count) == EXPECTED_BAR_COUNT_BY_FREQ[freq]
        and int(distinct_count) == EXPECTED_BAR_COUNT_BY_FREQ[freq]
        and int(invalid_time) == 0
        and int(invalid_value) == 0
    )
    total_rows = sum(int(row[1]) for row in rows)
    return total_rows, complete, len(rows)


def stage_bse_stk_mins_source_pages(
    *,
    plan_path: Path,
    tushare: TushareResource,
    duckdb_resource: DuckDBResource | None = None,
    output_path: Path | None = None,
    request_policy: TushareRequestPolicy | None = None,
    max_window_count: int | None = None,
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
    sidecars: list[dict[str, object]] = []
    failure_samples: list[dict[str, object]] = []
    for window in selected_windows:
        try:
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
                    returned_rows, complete_aliases, returned_count = _source_rows_for_scope(
                        connection=connection,
                        scope_rows=scope_rows,
                        window_sidecars=all_sidecars,
                        trade_date=trade_date,
                        freq=freq,
                    )
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
                    else:
                        mode = BseMinuteRecoveryMode.PARTIAL_BLOCKED
                        reason = "source_scope_partial"
                mode_rows.append(
                    {
                        "trade_date": trade_date,
                        "freq": freq,
                        "mode": mode.value,
                        "reason_code": reason,
                        "expected_latest_code_count": int(summary["expected_latest_code_count"]),
                        "canonical_existing_latest_code_count": int(
                            summary["canonical_existing_latest_code_count"]
                        ),
                        "missing_latest_code_count": int(summary["missing_latest_code_count"]),
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
        "should_stop": bool(
            incomplete_windows or failure_samples or blocked_mode_rows
        ),
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
    if frozen_bundle.get("scope_manifest_sha256") != plan.get(
        "scope_manifest_sha256"
    ):
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
    return root / "raw" / f"freq={freq}m" / f"trade_date={trade_date}" / "part-000.parquet"


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
                        SELECT {', '.join(RAW_COLUMNS)} FROM {existing_relation}
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
                if duplicate_count or scope_invalid_count or canonical_codes != expected_all_codes:
                    raise BseMinuteRecoveryError(
                        f"Raw candidate contract failed: {trade_date}:{freq}"
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
                    raise BseMinuteRecoveryError("candidate escaped the plan staging root")
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
                if duplicate_count or scope_invalid_count or canonical != expected:
                    raise BseMinuteRecoveryError("candidate content audit failed")
                target = raw_stk_mins_path(lake_root, freq, trade_date)
                if _non_bse_hash(
                    connection, read_parquet(target, hive_partitioning=False)
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
        raise BseMinuteRecoveryError("formal Raw promotion requires explicit confirmation")
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
    if audit.get("plan_hash") != plan["plan_hash"] or audit.get("bundle_hash") != bundle["bundle_hash"]:
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
    if checkpoint.get("plan_hash") != plan["plan_hash"] or checkpoint.get("bundle_hash") != bundle["bundle_hash"]:
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
            _assert_fingerprint_unchanged(
                interrupted_candidate["target_fingerprint"]
            )
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
            raise BseMinuteRecoveryError("candidate and formal Raw are not on one filesystem")
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
