"""Bounded Silver repair for source-empty index minute frequencies.

This module is an explicit maintenance entry point.  It is not a Dagster
asset, job, or sensor and is intentionally separate from the normal Silver
asset path, whose Raw dependencies remain unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4
import os

from orchestrator.defs.assets.index_mins_silver import (
    IndexMinsSilverValidationError,
    IndexMinsSilverWriteResult,
    _assert_schema,
    _native_source_sql,
    _native_output_sql,
    _validate_existing_target,
    _validate_relation,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.configs import normalize_iso_trade_date
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_FALLBACK_FREQS,
    INDEX_MINS_FALLBACK_SOURCE_FREQ,
    fallback_source_times_for_index_mins,
    fallback_target_times_for_index_mins_freq,
    normalize_index_mins_codes,
    normalize_index_mins_silver_freq,
)


@dataclass(frozen=True, slots=True)
class IndexMinsSilverFallbackRequest:
    """Audited source-empty scope for one bounded repair operation."""

    partition_key: str
    target_frequencies: tuple[int, ...]
    source_empty_frequencies: tuple[int, ...]
    effective_codes: tuple[str, ...]
    source_revision: str
    source_empty_reason: str


@dataclass(frozen=True, slots=True)
class IndexMinsSilverFallbackReadiness:
    """Read-only state for one audited fallback repair scope."""

    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    reason_code: str
    reason: str
    source_row_count: int
    checked_row_count: int
    missing_target_frequencies: tuple[int, ...]
    source_revision: str


def validate_silver_index_mins_source_empty_fallback(
    *,
    connection,
    lake_root: Path,
    request: IndexMinsSilverFallbackRequest,
) -> IndexMinsSilverFallbackReadiness:
    """Validate a fallback scope without writing files."""

    normalized_request = _normalize_request(request)
    source_path = raw_index_mins_path(
        lake_root,
        INDEX_MINS_FALLBACK_SOURCE_FREQ,
        normalized_request.partition_key,
    )
    if not source_path.exists():
        raise FileNotFoundError(f"Missing 5min Raw fallback source: {source_path}")
    _assert_schema(
        connection,
        source_path,
        RAW_INDEX_MINS_SCHEMA,
        label="index_mins 5min Raw fallback source",
    )
    source_sql = _native_source_sql(read_parquet(source_path, hive_partitioning=False))
    source_validation = _validate_relation(
        connection,
        relation_sql=source_sql,
        expected_freq=INDEX_MINS_FALLBACK_SOURCE_FREQ,
        partition_key=normalized_request.partition_key,
        require_null_vwap=False,
    )
    _validate_declared_source_empty(
        connection=connection,
        lake_root=lake_root,
        request=normalized_request,
    )
    _require_source_contract(
        connection=connection,
        source_sql=source_sql,
        source_validation=source_validation,
        request=normalized_request,
    )
    computed_revision = _source_revision(
        connection=connection,
        source_sql=source_sql,
        partition_key=normalized_request.partition_key,
    )
    if computed_revision != normalized_request.source_revision:
        raise IndexMinsSilverValidationError(
            "index_mins fallback source revision mismatch: "
            f"expected={normalized_request.source_revision}, actual={computed_revision}."
        )

    missing_frequencies: list[int] = []
    existing_frequencies: list[int] = []
    checked_row_count = source_validation.row_count
    for frequency in normalized_request.target_frequencies:
        target_path = silver_index_mins_path(
            lake_root,
            frequency,
            normalized_request.partition_key,
        )
        if not target_path.exists():
            missing_frequencies.append(frequency)
            continue
        existing_frequencies.append(frequency)
        expected_row_count = len(normalized_request.effective_codes) * len(
            fallback_target_times_for_index_mins_freq(frequency)
        )
        validation = _validate_existing_target(
            connection,
            target_path=target_path,
            relation_sql=read_parquet(target_path, hive_partitioning=False),
            expected_freq=f"{frequency}min",
            partition_key=normalized_request.partition_key,
            expected_row_count=expected_row_count,
            require_null_vwap=True,
        )
        checked_row_count += validation.row_count

    if missing_frequencies:
        partial = bool(existing_frequencies)
        return IndexMinsSilverFallbackReadiness(
            trade_date=normalized_request.partition_key,
            ready=False,
            materialized=partial,
            checks_passed=False,
            reason_code="fallback_target_partial"
            if partial
            else "fallback_target_missing",
            reason=(
                "index_mins fallback target frequencies are partially materialized"
                if partial
                else "index_mins fallback target frequencies are missing"
            ),
            source_row_count=source_validation.row_count,
            checked_row_count=checked_row_count,
            missing_target_frequencies=tuple(missing_frequencies),
            source_revision=computed_revision,
        )
    return IndexMinsSilverFallbackReadiness(
        trade_date=normalized_request.partition_key,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason_code="ready_after_source_empty_fallback",
        reason="index_mins fallback targets are ready",
        source_row_count=source_validation.row_count,
        checked_row_count=checked_row_count,
        missing_target_frequencies=(),
        source_revision=computed_revision,
    )


def compute_index_mins_fallback_source_revision(
    *,
    connection,
    lake_root: Path,
    partition_key: str,
) -> str:
    """Compute the deterministic revision for an audited 5min Raw partition."""

    normalized_partition = normalize_iso_trade_date(
        partition_key,
        field_name="partition_key",
    )
    source_path = raw_index_mins_path(
        lake_root,
        INDEX_MINS_FALLBACK_SOURCE_FREQ,
        normalized_partition,
    )
    if not source_path.exists():
        raise FileNotFoundError(f"Missing 5min Raw fallback source: {source_path}")
    _assert_schema(
        connection,
        source_path,
        RAW_INDEX_MINS_SCHEMA,
        label="index_mins 5min Raw fallback source",
    )
    source_sql = _native_source_sql(read_parquet(source_path, hive_partitioning=False))
    source_validation = _validate_relation(
        connection,
        relation_sql=source_sql,
        expected_freq=INDEX_MINS_FALLBACK_SOURCE_FREQ,
        partition_key=normalized_partition,
        require_null_vwap=False,
    )
    if source_validation.row_count <= 0:
        raise IndexMinsSilverValidationError(
            "index_mins 5min Raw fallback source is empty."
        )
    if source_validation.duplicate_key_count or source_validation.invalid_row_count:
        raise IndexMinsSilverValidationError(
            "index_mins 5min Raw fallback source failed core contract: "
            f"duplicate_key_count={source_validation.duplicate_key_count}, "
            f"invalid_row_count={source_validation.invalid_row_count}."
        )
    return _source_revision(
        connection=connection,
        source_sql=source_sql,
        partition_key=normalized_partition,
    )


def repair_silver_index_mins_source_empty(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    request: IndexMinsSilverFallbackRequest,
) -> tuple[IndexMinsSilverWriteResult, ...]:
    """Rebuild source-empty Silver frequencies from the same-day 5m Raw file."""

    del duckdb  # Use the repository-wide configured connection helper.
    normalized_request = _normalize_request(request)
    source_path = raw_index_mins_path(
        lake_root,
        INDEX_MINS_FALLBACK_SOURCE_FREQ,
        normalized_request.partition_key,
    )
    target_paths = tuple(
        silver_index_mins_path(lake_root, frequency, normalized_request.partition_key)
        for frequency in normalized_request.target_frequencies
    )
    if not source_path.exists():
        raise FileNotFoundError(
            f"Missing 5min Raw source for index_mins Silver fallback: {source_path}"
        )

    started_at = perf_counter()
    staged_paths: list[Path] = []
    backup_paths: dict[Path, Path] = {}
    promoted_targets: list[Path] = []
    try:
        with connect_configured_duckdb() as connection:
            _validate_declared_source_empty(
                connection=connection,
                lake_root=lake_root,
                request=normalized_request,
            )
            _assert_schema(
                connection,
                source_path,
                RAW_INDEX_MINS_SCHEMA,
                label="index_mins 5min Raw fallback source",
            )
            source_sql = _native_source_sql(
                read_parquet(source_path, hive_partitioning=False)
            )
            source_validation = _validate_relation(
                connection,
                relation_sql=source_sql,
                expected_freq=INDEX_MINS_FALLBACK_SOURCE_FREQ,
                partition_key=normalized_request.partition_key,
                require_null_vwap=False,
            )
            _require_source_contract(
                connection=connection,
                source_sql=source_sql,
                source_validation=source_validation,
                request=normalized_request,
            )
            computed_revision = _source_revision(
                connection=connection,
                source_sql=source_sql,
                partition_key=normalized_request.partition_key,
            )
            if computed_revision != normalized_request.source_revision:
                raise IndexMinsSilverValidationError(
                    "index_mins fallback source revision mismatch: "
                    f"expected={normalized_request.source_revision}, "
                    f"actual={computed_revision}."
                )

            results: list[IndexMinsSilverWriteResult] = []
            for frequency, target_path in zip(
                normalized_request.target_frequencies,
                target_paths,
                strict=True,
            ):
                diagnostics = _fallback_diagnostics(
                    connection=connection,
                    source_sql=source_sql,
                    partition_key=normalized_request.partition_key,
                    frequency=frequency,
                    code_count=len(normalized_request.effective_codes),
                )
                _require_fallback_diagnostics(
                    diagnostics=diagnostics,
                    frequency=frequency,
                    partition_key=normalized_request.partition_key,
                )
                output_sql = _fallback_output_sql(
                    source_sql=source_sql,
                    partition_key=normalized_request.partition_key,
                    frequency=frequency,
                )
                target_path.parent.mkdir(parents=True, exist_ok=True)
                staging_path = target_path.with_name(
                    f"{target_path.name}.fallback-{uuid4().hex}.tmp"
                )
                staged_paths.append(staging_path)
                connection.execute(copy_query_to_parquet(output_sql, staging_path))
                staging_validation = _validate_existing_target(
                    connection,
                    target_path=staging_path,
                    relation_sql=read_parquet(staging_path, hive_partitioning=False),
                    expected_freq=f"{frequency}min",
                    partition_key=normalized_request.partition_key,
                    expected_row_count=diagnostics["expected_output_row_count"],
                    require_null_vwap=True,
                )
                results.append(
                    IndexMinsSilverWriteResult(
                        silver_file_path=target_path,
                        source_file_path=source_path,
                        partition_key=normalized_request.partition_key,
                        silver_freq=f"{frequency}min",
                        source_freq=INDEX_MINS_FALLBACK_SOURCE_FREQ,
                        source_row_count=source_validation.row_count,
                        written_row_count=staging_validation.row_count,
                        expected_window_count=diagnostics["expected_window_count"],
                        generated_window_count=diagnostics["generated_window_count"],
                        incomplete_window_count=diagnostics["incomplete_window_count"],
                        exchange_mismatch_window_count=diagnostics[
                            "exchange_mismatch_window_count"
                        ],
                        duplicate_key_count=staging_validation.duplicate_key_count,
                        invalid_row_count=staging_validation.invalid_row_count,
                        elapsed_ms=0.0,
                        write_mode="bounded_repair_atomic_replace",
                        source_mode="derived_fallback",
                        source_empty_reason=normalized_request.source_empty_reason,
                        lower_source_row_count=source_validation.row_count,
                        derived_row_count=staging_validation.row_count,
                        source_revision=computed_revision,
                    )
                )

            _promote_staged_files(
                staged_paths=staged_paths,
                target_paths=target_paths,
                backup_paths=backup_paths,
                promoted_targets=promoted_targets,
            )
            elapsed_ms = (perf_counter() - started_at) * 1000
            for backup_path in backup_paths.values():
                if backup_path.exists():
                    backup_path.unlink()
            return tuple(
                _with_elapsed(result, elapsed_ms=elapsed_ms) for result in results
            )
    finally:
        for staging_path in staged_paths:
            if staging_path.exists():
                staging_path.unlink()
        for backup_path in backup_paths.values():
            if backup_path.exists():
                backup_path.unlink()


def reconcile_silver_index_mins_native_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    frequency: int | str,
    partition_key: str,
    expected_source_revision: str | None = None,
) -> IndexMinsSilverWriteResult:
    """Replace a fallback Silver file after native source data reappears."""

    del duckdb
    normalized_partition = normalize_iso_trade_date(
        partition_key,
        field_name="partition_key",
    )
    normalized_frequency = normalize_index_mins_silver_freq(frequency)
    numeric_frequency = int(normalized_frequency[:-3])
    if numeric_frequency not in INDEX_MINS_FALLBACK_FREQS:
        raise ValueError(
            "index_mins native reconcile only supports frequencies 15, 30 and 60."
        )
    source_path = raw_index_mins_path(
        lake_root, normalized_frequency, normalized_partition
    )
    target_path = silver_index_mins_path(
        lake_root, normalized_frequency, normalized_partition
    )
    if not source_path.exists():
        raise FileNotFoundError(f"Missing native index_mins Raw source: {source_path}")

    started_at = perf_counter()
    staging_path: Path | None = None
    backup_paths: dict[Path, Path] = {}
    promoted_targets: list[Path] = []
    try:
        with connect_configured_duckdb() as connection:
            _assert_schema(
                connection,
                source_path,
                RAW_INDEX_MINS_SCHEMA,
                label="index_mins native reconcile source",
            )
            source_sql = _native_source_sql(
                read_parquet(source_path, hive_partitioning=False)
            )
            source_validation = _validate_relation(
                connection,
                relation_sql=source_sql,
                expected_freq=normalized_frequency,
                partition_key=normalized_partition,
                require_null_vwap=False,
            )
            if source_validation.row_count <= 0:
                raise IndexMinsSilverValidationError(
                    "index_mins native reconcile source is empty: "
                    f"freq={normalized_frequency}, partition={normalized_partition}."
                )
            if (
                source_validation.duplicate_key_count
                or source_validation.invalid_row_count
            ):
                raise IndexMinsSilverValidationError(
                    "index_mins native reconcile source failed contract: "
                    f"duplicate_key_count={source_validation.duplicate_key_count}, "
                    f"invalid_row_count={source_validation.invalid_row_count}."
                )
            computed_revision = _source_revision(
                connection=connection,
                source_sql=source_sql,
                partition_key=normalized_partition,
            )
            if (
                expected_source_revision is not None
                and computed_revision != expected_source_revision
            ):
                raise IndexMinsSilverValidationError(
                    "index_mins native reconcile source revision mismatch: "
                    f"expected={expected_source_revision}, actual={computed_revision}."
                )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            staging_path = target_path.with_name(
                f"{target_path.name}.native-reconcile-{uuid4().hex}.tmp"
            )
            connection.execute(
                copy_query_to_parquet(_native_output_sql(source_sql), staging_path)
            )
            staging_validation = _validate_existing_target(
                connection,
                target_path=staging_path,
                relation_sql=read_parquet(staging_path, hive_partitioning=False),
                expected_freq=normalized_frequency,
                partition_key=normalized_partition,
                expected_row_count=source_validation.row_count,
                require_null_vwap=False,
            )
            _promote_staged_files(
                staged_paths=[staging_path],
                target_paths=[target_path],
                backup_paths=backup_paths,
                promoted_targets=promoted_targets,
            )
            return IndexMinsSilverWriteResult(
                silver_file_path=target_path,
                source_file_path=source_path,
                partition_key=normalized_partition,
                silver_freq=normalized_frequency,
                source_freq=normalized_frequency,
                source_row_count=source_validation.row_count,
                written_row_count=staging_validation.row_count,
                expected_window_count=0,
                generated_window_count=0,
                incomplete_window_count=0,
                exchange_mismatch_window_count=0,
                duplicate_key_count=staging_validation.duplicate_key_count,
                invalid_row_count=staging_validation.invalid_row_count,
                elapsed_ms=(perf_counter() - started_at) * 1000,
                write_mode="bounded_repair_atomic_replace",
                source_mode="native_reconcile",
                source_empty_reason="native_source_reappeared",
                lower_source_row_count=None,
                derived_row_count=None,
                source_revision=computed_revision,
            )
    finally:
        if staging_path is not None and staging_path.exists():
            staging_path.unlink()
        for backup_path in backup_paths.values():
            if backup_path.exists():
                backup_path.unlink()


def _promote_staged_files(
    *,
    staged_paths: Sequence[Path],
    target_paths: Sequence[Path],
    backup_paths: dict[Path, Path],
    promoted_targets: list[Path],
) -> None:
    """Promote a prepared file set and restore old targets if rename fails."""

    try:
        for staging_path, target_path in zip(staged_paths, target_paths, strict=True):
            if target_path.exists():
                backup_path = target_path.with_name(
                    f"{target_path.name}.repair-backup-{uuid4().hex}.tmp"
                )
                os.replace(target_path, backup_path)
                backup_paths[target_path] = backup_path
            os.replace(staging_path, target_path)
            promoted_targets.append(target_path)
    except Exception:
        for target_path in reversed(promoted_targets):
            if target_path.exists():
                target_path.unlink()
            backup_path = backup_paths.pop(target_path, None)
            if backup_path is not None and backup_path.exists():
                os.replace(backup_path, target_path)
        for target_path, backup_path in backup_paths.items():
            if backup_path.exists():
                os.replace(backup_path, target_path)
        raise
    for backup_path in backup_paths.values():
        if backup_path.exists():
            backup_path.unlink()


def _normalize_request(
    request: IndexMinsSilverFallbackRequest,
) -> IndexMinsSilverFallbackRequest:
    partition_key = normalize_iso_trade_date(
        request.partition_key, field_name="partition_key"
    )
    target_frequencies = _normalize_frequencies(request.target_frequencies)
    source_empty_frequencies = _normalize_frequencies(request.source_empty_frequencies)
    if not set(target_frequencies).issubset(source_empty_frequencies):
        raise ValueError(
            "index_mins fallback target frequencies must be explicitly source-empty."
        )
    effective_codes = tuple(
        sorted(
            normalize_index_mins_codes(
                request.effective_codes,
                reject_duplicates=True,
            )
        )
    )
    if not effective_codes:
        raise ValueError("index_mins fallback effective code set must not be empty.")
    if len(effective_codes) > 2_000:
        raise ValueError("index_mins fallback effective code set exceeds 2000 codes.")
    if not request.source_revision.strip():
        raise ValueError("index_mins fallback source_revision must not be empty.")
    if not request.source_empty_reason or not request.source_empty_reason.isascii():
        raise ValueError(
            "index_mins fallback source_empty_reason must be non-empty ASCII."
        )
    return IndexMinsSilverFallbackRequest(
        partition_key=partition_key,
        target_frequencies=target_frequencies,
        source_empty_frequencies=source_empty_frequencies,
        effective_codes=effective_codes,
        source_revision=request.source_revision.strip(),
        source_empty_reason=request.source_empty_reason,
    )


def _normalize_frequencies(values: Sequence[object]) -> tuple[int, ...]:
    normalized: list[int] = []
    for value in values:
        frequency = int(normalize_index_mins_silver_freq(value)[:-3])
        if frequency not in INDEX_MINS_FALLBACK_FREQS:
            raise ValueError(
                "index_mins fallback only supports frequencies 15, 30 and 60."
            )
        if frequency in normalized:
            raise ValueError(
                f"index_mins fallback frequency is duplicated: {frequency}."
            )
        normalized.append(frequency)
    if not normalized:
        raise ValueError("index_mins fallback frequency set must not be empty.")
    return tuple(sorted(normalized))


def _require_source_contract(
    *, connection, source_sql: str, source_validation, request
) -> None:
    if source_validation.row_count <= 0:
        raise IndexMinsSilverValidationError(
            "index_mins 5min Raw fallback source is empty."
        )
    if source_validation.duplicate_key_count or source_validation.invalid_row_count:
        raise IndexMinsSilverValidationError(
            "index_mins 5min Raw fallback source failed core contract: "
            f"duplicate_key_count={source_validation.duplicate_key_count}, "
            f"invalid_row_count={source_validation.invalid_row_count}."
        )
    expected_codes_sql = _values_sql(request.effective_codes, column_name="ts_code")
    row = connection.execute(
        f"""
        WITH expected_codes AS ({expected_codes_sql}), actual_codes AS (
          SELECT DISTINCT ts_code
          FROM ({source_sql}) source_rows
          WHERE CAST(trade_time AS DATE) = CAST(? AS DATE)
        )
        SELECT
          (SELECT count(*) FROM expected_codes),
          (SELECT count(*) FROM actual_codes),
          (SELECT count(*) FROM expected_codes e LEFT JOIN actual_codes a USING (ts_code)
           WHERE a.ts_code IS NULL),
          (SELECT count(*) FROM actual_codes a LEFT JOIN expected_codes e USING (ts_code)
           WHERE e.ts_code IS NULL)
        """,
        [request.partition_key],
    ).fetchone()
    if tuple(int(value or 0) for value in row) != (
        len(request.effective_codes),
        len(request.effective_codes),
        0,
        0,
    ):
        raise IndexMinsSilverValidationError(
            "index_mins fallback effective code set mismatch: "
            f"expected={len(request.effective_codes)}, actual={row[1]}, "
            f"missing={row[2]}, extra={row[3]}."
        )

    expected_times_sql = _values_sql(
        fallback_source_times_for_index_mins(),
        column_name="trade_time",
    )
    row = connection.execute(
        f"""
        WITH expected_codes AS ({expected_codes_sql}), expected_times AS ({expected_times_sql}),
        expected_grid AS (
          SELECT expected_codes.ts_code, expected_times.trade_time
          FROM expected_codes CROSS JOIN expected_times
        ), actual_grid AS (
          SELECT ts_code, strftime(trade_time, '%H:%M:%S') AS trade_time
          FROM ({source_sql}) source_rows
          WHERE CAST(trade_time AS DATE) = CAST(? AS DATE)
          GROUP BY ts_code, strftime(trade_time, '%H:%M:%S')
        )
        SELECT
          (SELECT count(*) FROM expected_grid),
          (SELECT count(*) FROM actual_grid),
          (SELECT count(*) FROM expected_grid e LEFT JOIN actual_grid a
             ON e.ts_code = a.ts_code AND e.trade_time = a.trade_time
           WHERE a.ts_code IS NULL),
          (SELECT count(*) FROM actual_grid a LEFT JOIN expected_grid e
             ON e.ts_code = a.ts_code AND e.trade_time = a.trade_time
           WHERE e.ts_code IS NULL)
        """,
        [request.partition_key],
    ).fetchone()
    expected_cell_count = len(request.effective_codes) * len(
        fallback_source_times_for_index_mins()
    )
    if tuple(int(value or 0) for value in row) != (
        expected_cell_count,
        expected_cell_count,
        0,
        0,
    ):
        raise IndexMinsSilverValidationError(
            "index_mins fallback 5min time grid is incomplete: "
            f"expected_cells={expected_cell_count}, actual_cells={row[1]}, "
            f"missing={row[2]}, unexpected={row[3]}."
        )


def _validate_declared_source_empty(
    *,
    connection,
    lake_root: Path,
    request: IndexMinsSilverFallbackRequest,
) -> None:
    """Reject a fallback claim when a target Raw frequency has actual rows."""

    for frequency in request.source_empty_frequencies:
        target_raw_path = raw_index_mins_path(
            lake_root,
            f"{frequency}min",
            request.partition_key,
        )
        if not target_raw_path.exists():
            continue
        _assert_schema(
            connection,
            target_raw_path,
            RAW_INDEX_MINS_SCHEMA,
            label=f"index_mins {frequency}min Raw source-empty audit",
        )
        row_count = int(
            connection.execute(
                f"SELECT count(*) FROM {read_parquet(target_raw_path, hive_partitioning=False)}"
            ).fetchone()[0]
        )
        if row_count:
            raise IndexMinsSilverValidationError(
                "index_mins fallback source-empty claim is false: "
                f"freq={frequency}min, partition={request.partition_key}, "
                f"raw_row_count={row_count}."
            )


def _source_revision(*, connection, source_sql: str, partition_key: str) -> str:
    row = connection.execute(
        f"""
        SELECT md5(coalesce(string_agg(
          concat_ws('|',
            coalesce(ts_code, '<NULL>'),
            coalesce(freq, '<NULL>'),
            coalesce(strftime(trade_time, '%Y-%m-%d %H:%M:%S'), '<NULL>'),
            coalesce(CAST(open AS VARCHAR), '<NULL>'),
            coalesce(CAST(close AS VARCHAR), '<NULL>'),
            coalesce(CAST(high AS VARCHAR), '<NULL>'),
            coalesce(CAST(low AS VARCHAR), '<NULL>'),
            coalesce(CAST(vol AS VARCHAR), '<NULL>'),
            coalesce(CAST(amount AS VARCHAR), '<NULL>'),
            coalesce(exchange, '<NULL>'),
            coalesce(CAST(vwap AS VARCHAR), '<NULL>')
          ), '||' ORDER BY ts_code, trade_time), ''))
        FROM ({source_sql}) source_rows
        WHERE CAST(trade_time AS DATE) = CAST(? AS DATE)
        """,
        [partition_key],
    ).fetchone()
    return str(row[0] or "")


def _fallback_diagnostics(
    *, connection, source_sql: str, partition_key: str, frequency: int, code_count: int
) -> dict[str, int]:
    target_times = fallback_target_times_for_index_mins_freq(frequency)
    values_sql = ", ".join(
        f"('{target_time}', {1 if target_time == '09:30:00' else frequency // 5})"
        for target_time in target_times
    )
    row = connection.execute(
        f"""
        WITH target_windows(target_time, expected_source_row_count) AS (
          VALUES {values_sql}
        ), source_rows AS (
          {source_sql}
        ), actual_windows AS (
          SELECT source_rows.ts_code, windows.target_time,
                 count(*) AS source_row_count,
                 count(DISTINCT source_rows.exchange) AS exchange_count,
                 count(*) FILTER (WHERE source_rows.exchange IS NULL) AS null_exchange_count
          FROM source_rows
          CROSS JOIN target_windows windows
          WHERE CAST(source_rows.trade_time AS DATE) = CAST(? AS DATE)
            AND CAST(source_rows.trade_time AS TIME) >
                CAST(windows.target_time AS TIME) - INTERVAL '{frequency} minutes'
            AND CAST(source_rows.trade_time AS TIME) <= CAST(windows.target_time AS TIME)
          GROUP BY source_rows.ts_code, windows.target_time
        ), expected_windows AS (
          SELECT codes.ts_code, windows.target_time, windows.expected_source_row_count
          FROM (SELECT DISTINCT ts_code FROM source_rows) codes
          CROSS JOIN target_windows windows
        ), status AS (
          SELECT expected_windows.ts_code, expected_windows.target_time,
                 expected_windows.expected_source_row_count,
                 coalesce(actual_windows.source_row_count, 0) AS source_row_count,
                 coalesce(actual_windows.exchange_count, 0) AS exchange_count,
                 coalesce(actual_windows.null_exchange_count, 0) AS null_exchange_count
          FROM expected_windows
          LEFT JOIN actual_windows USING (ts_code, target_time)
        )
        SELECT
          count(*) AS expected_window_count,
          count(*) FILTER (
            WHERE source_row_count = expected_source_row_count
              AND exchange_count = 1
              AND null_exchange_count = 0
          ) AS generated_window_count,
          count(*) FILTER (
            WHERE source_row_count <> expected_source_row_count
          ) AS incomplete_window_count,
          count(*) FILTER (
            WHERE source_row_count = expected_source_row_count
              AND exchange_count > 1
          ) AS exchange_mismatch_window_count,
          count(*) FILTER (
            WHERE source_row_count = expected_source_row_count
              AND null_exchange_count > 0
          ) AS null_exchange_window_count
        FROM status
        """,
        [partition_key],
    ).fetchone()
    expected_window_count = int(row[0] or 0)
    expected_output_row_count = code_count * len(target_times)
    return {
        "expected_window_count": expected_window_count,
        "generated_window_count": int(row[1] or 0),
        "incomplete_window_count": int(row[2] or 0),
        "exchange_mismatch_window_count": int(row[3] or 0),
        "null_exchange_window_count": int(row[4] or 0),
        "expected_output_row_count": expected_output_row_count,
    }


def _require_fallback_diagnostics(
    *, diagnostics: dict[str, int], frequency: int, partition_key: str
) -> None:
    if diagnostics["incomplete_window_count"]:
        raise IndexMinsSilverValidationError(
            "index_mins fallback window is incomplete: "
            f"freq={frequency}min, partition={partition_key}, "
            f"count={diagnostics['incomplete_window_count']}."
        )
    if (
        diagnostics["exchange_mismatch_window_count"]
        or diagnostics["null_exchange_window_count"]
    ):
        raise IndexMinsSilverValidationError(
            "index_mins fallback window has invalid exchange values: "
            f"freq={frequency}min, partition={partition_key}, "
            f"mixed={diagnostics['exchange_mismatch_window_count']}, "
            f"null={diagnostics['null_exchange_window_count']}."
        )
    if diagnostics["generated_window_count"] != diagnostics["expected_window_count"]:
        raise IndexMinsSilverValidationError(
            "index_mins fallback generated window count mismatch: "
            f"freq={frequency}min, partition={partition_key}."
        )


def _fallback_output_sql(*, source_sql: str, partition_key: str, frequency: int) -> str:
    target_times = fallback_target_times_for_index_mins_freq(frequency)
    values_sql = ", ".join(
        f"('{target_time}', {1 if target_time == '09:30:00' else frequency // 5})"
        for target_time in target_times
    )
    return f"""
    WITH target_windows(target_time, expected_source_row_count) AS (
      VALUES {values_sql}
    ), source_rows AS (
      {source_sql}
    ), windowed_rows AS (
      SELECT source_rows.*, windows.target_time, windows.expected_source_row_count,
             row_number() OVER (
               PARTITION BY source_rows.ts_code, windows.target_time
               ORDER BY source_rows.trade_time
             ) AS ascending_row_number,
             row_number() OVER (
               PARTITION BY source_rows.ts_code, windows.target_time
               ORDER BY source_rows.trade_time DESC
             ) AS descending_row_number
      FROM source_rows
      CROSS JOIN target_windows windows
      WHERE CAST(source_rows.trade_time AS DATE) = CAST('{partition_key}' AS DATE)
        AND CAST(source_rows.trade_time AS TIME) >
            CAST(windows.target_time AS TIME) - INTERVAL '{frequency} minutes'
        AND CAST(source_rows.trade_time AS TIME) <= CAST(windows.target_time AS TIME)
    ), aggregated AS (
      SELECT ts_code, target_time, expected_source_row_count,
             max(trade_time) AS trade_time,
             max(open) FILTER (WHERE ascending_row_number = 1) AS open,
             max(close) FILTER (WHERE descending_row_number = 1) AS close,
             max(high) AS high,
             min(low) AS low,
             sum(vol) AS vol,
             sum(amount) AS amount,
             max(exchange) AS exchange,
             count(*) AS source_row_count,
             count(DISTINCT exchange) AS exchange_count,
             count(*) FILTER (WHERE exchange IS NULL) AS null_exchange_count
      FROM windowed_rows
      GROUP BY ts_code, target_time, expected_source_row_count
    )
    SELECT ts_code, '{frequency}min'::VARCHAR AS freq, trade_time,
           open, close, high, low, vol, amount, exchange,
           CAST(NULL AS DOUBLE) AS vwap
    FROM aggregated
    WHERE source_row_count = expected_source_row_count
      AND exchange_count = 1
      AND null_exchange_count = 0
    ORDER BY ts_code, trade_time
    """


def _values_sql(values: Sequence[object], *, column_name: str) -> str:
    escaped = ", ".join("('" + str(value).replace("'", "''") + "')" for value in values)
    return f"SELECT * FROM (VALUES {escaped}) AS values_table({column_name})"


def _with_elapsed(
    result: IndexMinsSilverWriteResult, *, elapsed_ms: float
) -> IndexMinsSilverWriteResult:
    return IndexMinsSilverWriteResult(
        silver_file_path=result.silver_file_path,
        source_file_path=result.source_file_path,
        partition_key=result.partition_key,
        silver_freq=result.silver_freq,
        source_freq=result.source_freq,
        source_row_count=result.source_row_count,
        written_row_count=result.written_row_count,
        expected_window_count=result.expected_window_count,
        generated_window_count=result.generated_window_count,
        incomplete_window_count=result.incomplete_window_count,
        exchange_mismatch_window_count=result.exchange_mismatch_window_count,
        duplicate_key_count=result.duplicate_key_count,
        invalid_row_count=result.invalid_row_count,
        elapsed_ms=elapsed_ms,
        write_mode=result.write_mode,
        source_mode=result.source_mode,
        source_empty_reason=result.source_empty_reason,
        lower_source_row_count=result.lower_source_row_count,
        derived_row_count=result.derived_row_count,
        source_revision=result.source_revision,
    )


__all__ = [
    "IndexMinsSilverFallbackRequest",
    "IndexMinsSilverFallbackReadiness",
    "compute_index_mins_fallback_source_revision",
    "reconcile_silver_index_mins_native_partition",
    "repair_silver_index_mins_source_empty",
    "validate_silver_index_mins_source_empty_fallback",
]
