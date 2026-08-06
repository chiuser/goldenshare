"""Recoverable source staging and read-only audit for major-index minute Bootstrap."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from time import perf_counter, sleep
from uuid import uuid4

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsDatePlan,
    MajorIndexMinsSourcePlan,
    MajorIndexMinsSourceWindow,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.major_index_mins_raw_writer import (
    MajorIndexMinsFetchResult,
    fetch_major_index_mins_window,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_BOOTSTRAP_REQUEST_CHUNK_SIZE,
    MAJOR_INDEX_MINS_RAW_COLUMN_TYPES,
    MAJOR_INDEX_MINS_SCOPE_REVISION,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    major_index_mins_exchange_for_code,
    major_index_mins_session_times,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


_SAMPLE_LIMIT = 20


class MajorIndexMinsBootstrapStageError(RuntimeError):
    """Raised when source staging cannot continue without losing provenance."""


@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourceStageReport:
    generated_at: str
    staging_root: str
    date_plan_fingerprint: str
    source_plan_fingerprint: str
    expected_window_count: int
    completed_window_count: int
    written_window_count: int
    skipped_window_count: int
    request_count: int
    page_count: int
    retry_count: int
    source_row_count: int
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    elapsed_ms: float
    failure_samples: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "failure_samples": [dict(value) for value in self.failure_samples],
            "writes": {
                "source_staging": self.written_window_count,
                "formal_lake": 0,
                "dagster_db": 0,
                "dagster_events": 0,
            },
        }


@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourceStagingAudit:
    generated_at: str
    staging_root: str
    date_plan_fingerprint: str
    source_plan_fingerprint: str
    expected_window_count: int
    complete_window_count: int
    missing_window_count: int
    invalid_window_count: int
    expected_row_count: int
    source_row_count: int
    row_count_mismatch_count: int
    duplicate_key_count: int
    identity_invalid_count: int
    numeric_invalid_count: int
    missing_session_row_count: int
    extra_session_row_count: int
    opening_ohlc_sentinel_count: int
    other_ohlc_invalid_count: int
    staging_residual_count: int
    request_count: int
    page_count: int
    retry_count: int
    ready: bool
    stop_reason_codes: tuple[str, ...]
    elapsed_ms: float
    failure_samples: tuple[Mapping[str, object], ...]
    sentinel_samples: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "failure_samples": [dict(value) for value in self.failure_samples],
            "sentinel_samples": [dict(value) for value in self.sentinel_samples],
            "writes": {
                "source_staging": 0,
                "formal_lake": 0,
                "dagster_db": 0,
                "dagster_events": 0,
            },
        }


def source_staging_plan_root(
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
) -> Path:
    return (
        staging_root
        / "_major_index_mins_source"
        / f"scope_revision={MAJOR_INDEX_MINS_SCOPE_REVISION}"
        / f"plan_fingerprint={date_plan.fingerprint}"
    )


def source_window_directory(
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    window: MajorIndexMinsSourceWindow,
) -> Path:
    return (
        source_staging_plan_root(staging_root, date_plan)
        / f"freq={window.source_freq}"
        / f"ts_code={window.ts_code}"
        / f"window_id={window.window_id}"
    )


def source_window_parquet_path(
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    window: MajorIndexMinsSourceWindow,
) -> Path:
    return source_window_directory(staging_root, date_plan, window) / "part-000.parquet"


def source_window_sidecar_path(
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    window: MajorIndexMinsSourceWindow,
) -> Path:
    return source_window_directory(staging_root, date_plan, window) / "request.json"


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


def _create_source_table(connection) -> None:
    columns = ", ".join(
        f'"{column}" {MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column]}'
        for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
    )
    connection.execute(f"CREATE TEMP TABLE bootstrap_source_rows ({columns})")


def _write_fetch_result(
    *,
    duckdb_resource: DuckDBResource,
    result: MajorIndexMinsFetchResult,
    target_path: Path,
) -> None:
    with duckdb_resource.connect() as connection:
        _create_source_table(connection)
        columns = ", ".join(f'"{value}"' for value in MAJOR_INDEX_MINS_SOURCE_COLUMNS)
        placeholders = ", ".join("?" for _ in MAJOR_INDEX_MINS_SOURCE_COLUMNS)
        connection.executemany(
            f"INSERT INTO bootstrap_source_rows ({columns}) VALUES ({placeholders})",
            [
                tuple(row[column] for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS)
                for row in result.rows
            ],
        )
        connection.execute(
            copy_query_to_parquet(
                f"SELECT {columns} FROM bootstrap_source_rows ORDER BY ts_code, trade_time",
                target_path,
            )
        )
        description = connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(target_path, hive_partitioning=False)}"
        ).fetchall()
        observed = tuple((str(row[0]), str(row[1]).upper()) for row in description)
        expected = tuple(
            (column, MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column])
            for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
        )
        row_count = int(
            connection.execute(
                f"SELECT count(*) FROM {read_parquet(target_path, hive_partitioning=False)}"
            ).fetchone()[0]
            or 0
        )
    if observed != expected or row_count != len(result.rows):
        raise MajorIndexMinsBootstrapStageError(
            "source staging readback does not match fetched rows"
        )


def _sidecar_payload(
    *,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    window: MajorIndexMinsSourceWindow,
    result: MajorIndexMinsFetchResult,
    parquet_path: Path,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "scope_revision": MAJOR_INDEX_MINS_SCOPE_REVISION,
        "date_plan_fingerprint": date_plan.fingerprint,
        "source_plan_fingerprint": source_plan.fingerprint,
        "window": window.to_dict(),
        "fields": list(MAJOR_INDEX_MINS_SOURCE_COLUMNS),
        "source_row_count": len(result.rows),
        "request_count": result.request_count,
        "page_count": result.page_count,
        "retry_count": result.retry_count,
        "elapsed_ms": round(result.elapsed_ms, 3),
        "scope_hash": result.source_revision.scope_hash,
        "request_hash": result.source_revision.request_hash,
        "result_hash": result.source_revision.result_hash,
        "source_revision": result.source_revision.revision,
        "parquet_size_bytes": parquet_path.stat().st_size,
        "parquet_sha256": _sha256_file(parquet_path),
    }


def _load_completed_sidecar(
    *,
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    window: MajorIndexMinsSourceWindow,
    verify_hash: bool,
) -> Mapping[str, object] | None:
    parquet_path = source_window_parquet_path(staging_root, date_plan, window)
    sidecar_path = source_window_sidecar_path(staging_root, date_plan, window)
    if not parquet_path.exists() and not sidecar_path.exists():
        return None
    if not parquet_path.is_file() or not sidecar_path.is_file():
        raise MajorIndexMinsBootstrapStageError(
            f"partial source staging window exists: {window.window_id}"
        )
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MajorIndexMinsBootstrapStageError(
            f"source staging sidecar is unreadable: {window.window_id}"
        ) from error
    expected_window = window.to_dict()
    if (
        payload.get("status") != "complete"
        or payload.get("scope_revision") != MAJOR_INDEX_MINS_SCOPE_REVISION
        or payload.get("date_plan_fingerprint") != date_plan.fingerprint
        or payload.get("source_plan_fingerprint") != source_plan.fingerprint
        or payload.get("window") != expected_window
        or tuple(payload.get("fields") or ()) != MAJOR_INDEX_MINS_SOURCE_COLUMNS
    ):
        raise MajorIndexMinsBootstrapStageError(
            f"source staging sidecar contract mismatch: {window.window_id}"
        )
    if verify_hash and payload.get("parquet_sha256") != _sha256_file(parquet_path):
        raise MajorIndexMinsBootstrapStageError(
            f"source staging parquet hash mismatch: {window.window_id}"
        )
    return payload


def stage_source_windows(
    *,
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    tushare: TushareResource,
    duckdb_resource: DuckDBResource,
    output_path: Path,
    request_policy_factory: Callable[[], TushareRequestPolicy] | None = None,
    sleep_fn: Callable[[float], None] = sleep,
) -> MajorIndexMinsSourceStageReport:
    """Request each missing window once and atomically retain it for later audits."""

    started_at = perf_counter()
    if not source_plan.windows or source_plan.expected_row_count <= 0:
        raise MajorIndexMinsBootstrapStageError("source staging plan is empty")
    staging_root.mkdir(parents=True, exist_ok=True)
    policy_factory = request_policy_factory or (
        lambda: TushareRequestPolicy(
            minimum_interval_seconds=0.13,
            max_retries=3,
            max_requests=2,
            max_elapsed_seconds=120,
        )
    )
    written = 0
    skipped = 0
    request_count = 0
    page_count = 0
    retry_count = 0
    source_row_count = 0
    failure_samples: list[Mapping[str, object]] = []
    last_request_started_at: float | None = None

    def build_report(*, stopped: bool) -> MajorIndexMinsSourceStageReport:
        reasons = ("source_staging_failed",) if stopped else ()
        return MajorIndexMinsSourceStageReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            staging_root=str(staging_root),
            date_plan_fingerprint=date_plan.fingerprint,
            source_plan_fingerprint=source_plan.fingerprint,
            expected_window_count=len(source_plan.windows),
            completed_window_count=written + skipped,
            written_window_count=written,
            skipped_window_count=skipped,
            request_count=request_count,
            page_count=page_count,
            retry_count=retry_count,
            source_row_count=source_row_count,
            should_stop=stopped,
            stop_reason_codes=reasons,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            failure_samples=tuple(failure_samples[:_SAMPLE_LIMIT]),
        )

    for index, window in enumerate(source_plan.windows):
        try:
            existing = _load_completed_sidecar(
                staging_root=staging_root,
                date_plan=date_plan,
                source_plan=source_plan,
                window=window,
                verify_hash=True,
            )
            if existing is not None:
                skipped += 1
                source_row_count += int(existing["source_row_count"])
                continue
            policy = policy_factory()
            if last_request_started_at is not None:
                wait_seconds = max(
                    policy.minimum_interval_seconds
                    - (perf_counter() - last_request_started_at),
                    0.0,
                )
                if wait_seconds:
                    sleep_fn(wait_seconds)
            last_request_started_at = perf_counter()
            result = fetch_major_index_mins_window(
                tushare=tushare,
                ts_codes=(window.ts_code,),
                source_freq=window.source_freq,
                start_datetime=window.start_datetime,
                end_datetime=window.end_datetime,
                request_policy=policy,
            )
            final_directory = source_window_directory(staging_root, date_plan, window)
            final_directory.parent.mkdir(parents=True, exist_ok=True)
            temporary_directory = final_directory.with_name(
                f".{final_directory.name}.{uuid4().hex}.tmp"
            )
            temporary_directory.mkdir()
            try:
                temporary_parquet = temporary_directory / "part-000.parquet"
                _write_fetch_result(
                    duckdb_resource=duckdb_resource,
                    result=result,
                    target_path=temporary_parquet,
                )
                payload = _sidecar_payload(
                    date_plan=date_plan,
                    source_plan=source_plan,
                    window=window,
                    result=result,
                    parquet_path=temporary_parquet,
                )
                (temporary_directory / "request.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                if final_directory.exists():
                    raise MajorIndexMinsBootstrapStageError(
                        f"source staging window appeared during write: {window.window_id}"
                    )
                os.replace(temporary_directory, final_directory)
            finally:
                shutil.rmtree(temporary_directory, ignore_errors=True)
            written += 1
            request_count += result.request_count
            page_count += result.page_count
            retry_count += result.retry_count
            source_row_count += len(result.rows)
        except Exception as error:  # noqa: BLE001 - checkpoint and stop this approved batch.
            failure_samples.append(
                {
                    "window_id": window.window_id,
                    "ts_code": window.ts_code,
                    "source_freq": window.source_freq,
                    "start_date": window.trade_dates[0],
                    "end_date": window.trade_dates[-1],
                    "error_type": type(error).__name__,
                }
            )
            report = build_report(stopped=True)
            _atomic_write_json(output_path, report.to_dict())
            return report
        if (index + 1) % MAJOR_INDEX_MINS_BOOTSTRAP_REQUEST_CHUNK_SIZE == 0:
            _atomic_write_json(output_path, build_report(stopped=False).to_dict())

    report = build_report(stopped=False)
    _atomic_write_json(output_path, report.to_dict())
    return report


def _expected_timestamps(window: MajorIndexMinsSourceWindow) -> set[str]:
    exchange = major_index_mins_exchange_for_code(window.ts_code)
    return {
        f"{trade_date} {source_time}"
        for trade_date in window.trade_dates
        for source_time in major_index_mins_session_times(
            exchange=exchange,
            source_freq=window.source_freq,
        )
    }


def audit_source_staging(
    *,
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    duckdb_resource: DuckDBResource,
) -> MajorIndexMinsSourceStagingAudit:
    """Audit all staged source windows without issuing any source request."""

    started_at = perf_counter()
    complete = 0
    missing = 0
    invalid = 0
    source_rows = 0
    row_mismatches = 0
    duplicates = 0
    identity_invalid = 0
    numeric_invalid = 0
    missing_sessions = 0
    extra_sessions = 0
    sentinel_count = 0
    other_ohlc_invalid = 0
    request_count = 0
    page_count = 0
    retry_count = 0
    failure_samples: list[Mapping[str, object]] = []
    sentinel_samples: list[Mapping[str, object]] = []
    plan_root = source_staging_plan_root(staging_root, date_plan)
    residual_paths = (
        tuple(
            path
            for path in plan_root.rglob("*")
            if path.name.startswith(".") and path.name.endswith(".tmp")
        )
        if plan_root.exists()
        else ()
    )

    with duckdb_resource.connect() as connection:
        for window in source_plan.windows:
            try:
                sidecar = _load_completed_sidecar(
                    staging_root=staging_root,
                    date_plan=date_plan,
                    source_plan=source_plan,
                    window=window,
                    verify_hash=True,
                )
                if sidecar is None:
                    missing += 1
                    continue
                path = source_window_parquet_path(staging_root, date_plan, window)
                relation = read_parquet(path, hive_partitioning=False)
                description = connection.execute(
                    f"DESCRIBE SELECT * FROM {relation}"
                ).fetchall()
                observed = tuple(
                    (str(row[0]), str(row[1]).upper()) for row in description
                )
                expected_schema = tuple(
                    (column, MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column])
                    for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
                )
                if observed != expected_schema:
                    raise MajorIndexMinsBootstrapStageError("schema_mismatch")
                expected_exchange = major_index_mins_exchange_for_code(window.ts_code)
                (
                    row_count,
                    duplicate_count,
                    identity_count,
                    numeric_count,
                    opening_sentinel_count,
                    other_ohlc_count,
                ) = connection.execute(
                    f"""
                    SELECT
                      count(*),
                      count(*) - count(DISTINCT (ts_code, freq, trade_time)),
                      count(*) FILTER (
                        WHERE ts_code IS NULL OR ts_code <> ?
                           OR freq IS NULL OR freq <> ?
                           OR exchange IS NULL
                           OR lower(trim(exchange)) = 'nan'
                           OR exchange <> ?
                           OR CAST(trade_time AS DATE) NOT BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
                      ),
                      count(*) FILTER (
                        WHERE open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
                           OR vol IS NULL OR amount IS NULL
                           OR NOT isfinite(open) OR NOT isfinite(close)
                           OR NOT isfinite(high) OR NOT isfinite(low)
                           OR NOT isfinite(vol) OR NOT isfinite(amount)
                           OR open < 0 OR close < 0 OR high < 0 OR low < 0
                           OR vol < 0 OR amount < 0
                      ),
                      count(*) FILTER (
                        WHERE CAST(trade_time AS TIME) = TIME '09:30:00'
                          AND high = 0 AND low = 0 AND open = close AND open > 0
                      ),
                      count(*) FILTER (
                        WHERE (high < greatest(open, close, low)
                           OR low > least(open, close, high))
                          AND NOT (
                            CAST(trade_time AS TIME) = TIME '09:30:00'
                            AND high = 0 AND low = 0 AND open = close AND open > 0
                          )
                      )
                    FROM {relation}
                    """,
                    [
                        window.ts_code,
                        window.source_freq,
                        expected_exchange,
                        window.trade_dates[0],
                        window.trade_dates[-1],
                    ],
                ).fetchone()
                actual_timestamps = {
                    str(row[0])
                    for row in connection.execute(
                        f"SELECT strftime(trade_time, '%Y-%m-%d %H:%M:%S') FROM {relation}"
                    ).fetchall()
                }
                expected_timestamps = _expected_timestamps(window)
                row_count = int(row_count or 0)
                source_rows += row_count
                duplicates += int(duplicate_count or 0)
                identity_invalid += int(identity_count or 0)
                numeric_invalid += int(numeric_count or 0)
                sentinel_count += int(opening_sentinel_count or 0)
                other_ohlc_invalid += int(other_ohlc_count or 0)
                missing_sessions += len(expected_timestamps - actual_timestamps)
                extra_sessions += len(actual_timestamps - expected_timestamps)
                row_mismatches += int(
                    row_count != window.expected_row_count
                    or row_count != int(sidecar["source_row_count"])
                )
                request_count += int(sidecar["request_count"])
                page_count += int(sidecar["page_count"])
                retry_count += int(sidecar["retry_count"])
                if opening_sentinel_count and len(sentinel_samples) < _SAMPLE_LIMIT:
                    rows = connection.execute(
                        f"""
                        SELECT ts_code, freq,
                               strftime(trade_time, '%Y-%m-%d %H:%M:%S'),
                               open, close, high, low
                        FROM {relation}
                        WHERE CAST(trade_time AS TIME) = TIME '09:30:00'
                          AND high = 0 AND low = 0 AND open = close AND open > 0
                        LIMIT ?
                        """,
                        [_SAMPLE_LIMIT - len(sentinel_samples)],
                    ).fetchall()
                    sentinel_samples.extend(
                        {
                            "ts_code": row[0],
                            "source_freq": row[1],
                            "trade_time": row[2],
                            "open": row[3],
                            "close": row[4],
                            "high": row[5],
                            "low": row[6],
                        }
                        for row in rows
                    )
                complete += 1
            except Exception as error:  # noqa: BLE001 - collect all bounded failures.
                invalid += 1
                if len(failure_samples) < _SAMPLE_LIMIT:
                    failure_samples.append(
                        {
                            "window_id": window.window_id,
                            "ts_code": window.ts_code,
                            "source_freq": window.source_freq,
                            "error_type": type(error).__name__,
                        }
                    )

    stop_reasons: list[str] = []
    if missing:
        stop_reasons.append("source_staging_incomplete")
    if invalid:
        stop_reasons.append("source_staging_invalid")
    if row_mismatches or source_rows != source_plan.expected_row_count:
        stop_reasons.append("source_row_count_mismatch")
    if duplicates:
        stop_reasons.append("source_duplicate_key")
    if identity_invalid:
        stop_reasons.append("source_identity_invalid")
    if numeric_invalid:
        stop_reasons.append("source_numeric_invalid")
    if missing_sessions or extra_sessions:
        stop_reasons.append("source_session_grid_mismatch")
    if sentinel_count:
        stop_reasons.append("source_ohlc_policy_required")
    if other_ohlc_invalid:
        stop_reasons.append("source_ohlc_invalid")
    if residual_paths:
        stop_reasons.append("source_staging_residual")
    return MajorIndexMinsSourceStagingAudit(
        generated_at=datetime.now(timezone.utc).isoformat(),
        staging_root=str(staging_root),
        date_plan_fingerprint=date_plan.fingerprint,
        source_plan_fingerprint=source_plan.fingerprint,
        expected_window_count=len(source_plan.windows),
        complete_window_count=complete,
        missing_window_count=missing,
        invalid_window_count=invalid,
        expected_row_count=source_plan.expected_row_count,
        source_row_count=source_rows,
        row_count_mismatch_count=row_mismatches,
        duplicate_key_count=duplicates,
        identity_invalid_count=identity_invalid,
        numeric_invalid_count=numeric_invalid,
        missing_session_row_count=missing_sessions,
        extra_session_row_count=extra_sessions,
        opening_ohlc_sentinel_count=sentinel_count,
        other_ohlc_invalid_count=other_ohlc_invalid,
        staging_residual_count=len(residual_paths),
        request_count=request_count,
        page_count=page_count,
        retry_count=retry_count,
        ready=not stop_reasons,
        stop_reason_codes=tuple(stop_reasons),
        elapsed_ms=(perf_counter() - started_at) * 1000,
        failure_samples=tuple(
            (
                *failure_samples,
                *(
                    {
                        "error_type": "staging_residual",
                        "path": str(path),
                    }
                    for path in residual_paths[:_SAMPLE_LIMIT]
                ),
            )[:_SAMPLE_LIMIT]
        ),
        sentinel_samples=tuple(sentinel_samples),
    )


def write_source_staging_audit(
    report: MajorIndexMinsSourceStagingAudit,
    output_path: Path,
) -> None:
    _atomic_write_json(output_path, report.to_dict())


__all__ = [
    "MajorIndexMinsBootstrapStageError",
    "MajorIndexMinsSourceStageReport",
    "MajorIndexMinsSourceStagingAudit",
    "audit_source_staging",
    "source_staging_plan_root",
    "source_window_directory",
    "source_window_parquet_path",
    "source_window_sidecar_path",
    "stage_source_windows",
    "write_source_staging_audit",
]
