"""Bounded Tushare fetch primitives for major-index minute bars."""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.major_index_mins_quality import (
    prepare_major_index_mins_raw_expected_tables,
    validate_major_index_mins_raw_relation,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    raw_major_index_mins_staging_path,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource, TushareResult
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_CODES,
    MAJOR_INDEX_MINS_PAGE_LIMIT,
    MAJOR_INDEX_MINS_RAW_COLUMN_TYPES,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
    MajorIndexMinsSourceRevision,
    build_major_index_mins_source_revision,
    effective_raw_request_codes_for_date,
    major_index_mins_source_scope,
    normalize_major_index_mins_source_freq,
    normalize_major_index_mins_trade_date,
    raw_scope_hash_for_partition,
)
from orchestrator.defs.tushare_request_policy import (
    TushareRequestPolicy,
    execute_bounded_code_pages,
)


class MajorIndexMinsFetchError(RuntimeError):
    """Raised when a bounded source window cannot be consumed safely."""


class MajorIndexMinsRawValidationError(ValueError):
    """Raised when source, staging, or an existing Raw target is invalid."""


@dataclass(frozen=True, slots=True)
class MajorIndexMinsFetchResult:
    source_freq: str
    start_datetime: str
    end_datetime: str
    expected_codes: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    page_counts: Mapping[str, int]
    request_count: int
    retry_count: int
    elapsed_ms: float
    source_revision: MajorIndexMinsSourceRevision

    @property
    def page_count(self) -> int:
        return sum(self.page_counts.values())

    def to_details(self) -> dict[str, object]:
        return {
            "source_freq": self.source_freq,
            "start_datetime": self.start_datetime,
            "end_datetime": self.end_datetime,
            "expected_code_count": len(self.expected_codes),
            "source_row_count": len(self.rows),
            "page_count": self.page_count,
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "source_revision": self.source_revision.revision,
        }


@dataclass(frozen=True, slots=True)
class MajorIndexMinsRawWriteResult:
    partition_key: str
    source_freq: str
    target_path: Path
    staging_path: Path
    write_mode: str
    expected_code_count: int
    source_row_count: int
    output_row_count: int
    request_count: int
    page_count: int
    retry_count: int
    elapsed_ms: float
    source_revision: str | None
    scope_hash: str

    def to_details(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "source_freq": self.source_freq,
            "target_path": str(self.target_path),
            "write_mode": self.write_mode,
            "expected_code_count": self.expected_code_count,
            "source_row_count": self.source_row_count,
            "output_row_count": self.output_row_count,
            "request_count": self.request_count,
            "page_count": self.page_count,
            "retry_count": self.retry_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "source_revision": self.source_revision,
            "scope_hash": self.scope_hash,
        }


def _normalize_datetime(value: str, *, field_name: str) -> tuple[str, datetime]:
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MajorIndexMinsFetchError(
            f"{field_name} must be an ISO datetime: {value!r}"
        ) from exc
    if parsed.tzinfo is not None:
        raise MajorIndexMinsFetchError(f"{field_name} must be timezone-naive.")
    return parsed.strftime("%Y-%m-%d %H:%M:%S"), parsed


def _extract_rows(result: TushareResult) -> Sequence[Mapping[str, object]]:
    if not result.rows and not result.columns:
        return ()
    if tuple(result.columns) != MAJOR_INDEX_MINS_SOURCE_COLUMNS:
        raise MajorIndexMinsFetchError(
            "schema_drift: idx_mins response columns differ from the explicit contract; "
            f"expected={MAJOR_INDEX_MINS_SOURCE_COLUMNS!r}, actual={result.columns!r}"
        )
    return tuple(dict(row) for row in result.rows)


def _failure_reason(message: str) -> str:
    lowered = message.lower()
    if "duplicate row" in lowered:
        return "duplicate_key"
    if "schema_drift" in lowered:
        return "schema_drift"
    if "budget" in lowered:
        return "budget_exceeded"
    return "unknown_source_error"


def fetch_major_index_mins_window(
    *,
    tushare: TushareResource,
    ts_codes: Sequence[str],
    source_freq: str,
    start_datetime: str,
    end_datetime: str,
    request_policy: TushareRequestPolicy,
) -> MajorIndexMinsFetchResult:
    """Fetch one bounded code/frequency/time window without writing any file."""

    normalized_codes = tuple(str(code).strip().upper() for code in ts_codes)
    if not normalized_codes:
        raise MajorIndexMinsFetchError("expected code scope must not be empty.")
    if len(set(normalized_codes)) != len(normalized_codes):
        raise MajorIndexMinsFetchError("expected code scope contains duplicate codes.")
    unknown_codes = tuple(code for code in normalized_codes if code not in MAJOR_INDEX_MINS_CODES)
    if unknown_codes:
        raise MajorIndexMinsFetchError(f"unsupported code(s): {unknown_codes!r}")
    if source_freq not in MAJOR_INDEX_MINS_SOURCE_FREQS:
        raise MajorIndexMinsFetchError(
            f"unsupported source frequency: {source_freq!r}"
        )

    normalized_start, parsed_start = _normalize_datetime(
        start_datetime,
        field_name="start_datetime",
    )
    normalized_end, parsed_end = _normalize_datetime(
        end_datetime,
        field_name="end_datetime",
    )
    if parsed_start > parsed_end:
        raise MajorIndexMinsFetchError("start_datetime must not exceed end_datetime.")
    for code in normalized_codes:
        scope = major_index_mins_source_scope(code)
        if parsed_start.date().isoformat() < scope.source_start_date:
            raise MajorIndexMinsFetchError(
                f"request starts before source scope for {code}."
            )
        if (
            scope.source_end_date is not None
            and parsed_end.date().isoformat() > scope.source_end_date
        ):
            raise MajorIndexMinsFetchError(
                f"request ends after source scope for {code}."
            )

    request_result = execute_bounded_code_pages(
        codes=normalized_codes,
        request_page=lambda code, offset: tushare.call(
            "idx_mins",
            {
                "ts_code": code,
                "freq": source_freq,
                "start_date": normalized_start,
                "end_date": normalized_end,
                "limit": MAJOR_INDEX_MINS_PAGE_LIMIT,
                "offset": offset,
            },
            MAJOR_INDEX_MINS_SOURCE_COLUMNS,
        ),
        extract_rows=_extract_rows,
        page_size=MAJOR_INDEX_MINS_PAGE_LIMIT,
        policy=request_policy,
        row_key=lambda row: (row.get("ts_code"), row.get("trade_time")),
    )
    if not request_result.ready:
        failure_message = "; ".join(
            failure.message for failure in request_result.failed_codes[:3]
        )
        reason = _failure_reason(
            failure_message or request_result.blocked_reason or "unknown"
        )
        raise MajorIndexMinsFetchError(
            f"{reason}: bounded idx_mins request failed; "
            f"details={request_result.to_details(max_failure_samples=3)!r}"
        )
    if request_result.empty_codes:
        raise MajorIndexMinsFetchError(
            "source_empty: expected idx_mins code(s) returned no rows; "
            f"empty_codes={request_result.empty_codes!r}"
        )

    flattened_rows: list[dict[str, object]] = []
    for code in normalized_codes:
        for row in request_result.rows_by_code.get(code, ()):  # pragma: no branch
            if set(row) != set(MAJOR_INDEX_MINS_SOURCE_COLUMNS):
                raise MajorIndexMinsFetchError(
                    f"schema_drift: row keys differ for {code}."
                )
            if str(row.get("ts_code", "")).strip().upper() != code:
                raise MajorIndexMinsFetchError(
                    f"identity_mismatch: response code differs for {code}."
                )
            if str(row.get("freq", "")).strip() != source_freq:
                raise MajorIndexMinsFetchError(
                    f"frequency_mismatch: response frequency differs for {code}."
                )
            _, trade_time = _normalize_datetime(
                str(row.get("trade_time", "")),
                field_name="trade_time",
            )
            if not parsed_start <= trade_time <= parsed_end:
                raise MajorIndexMinsFetchError(
                    f"time_out_of_window: response row is outside request window for {code}."
                )
            flattened_rows.append(dict(row))

    rows = tuple(
        sorted(
            flattened_rows,
            key=lambda row: (str(row["ts_code"]), str(row["trade_time"])),
        )
    )
    source_revision = build_major_index_mins_source_revision(
        ts_codes=normalized_codes,
        source_freq=source_freq,
        start_datetime=normalized_start,
        end_datetime=normalized_end,
        rows=rows,
    )
    return MajorIndexMinsFetchResult(
        source_freq=source_freq,
        start_datetime=normalized_start,
        end_datetime=normalized_end,
        expected_codes=normalized_codes,
        rows=rows,
        page_counts=dict(request_result.page_counts),
        request_count=request_result.request_count,
        retry_count=request_result.retry_count,
        elapsed_ms=request_result.elapsed_ms,
        source_revision=source_revision,
    )


def _create_source_table(connection) -> None:
    columns_sql = ", ".join(
        f'"{column}" {MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column]}'
        for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
    )
    connection.execute(f"CREATE TEMP TABLE major_index_mins_source ({columns_sql})")


def _insert_source_rows(
    connection,
    rows: Sequence[Mapping[str, object]],
) -> None:
    placeholders = ", ".join("?" for _ in MAJOR_INDEX_MINS_SOURCE_COLUMNS)
    columns_sql = ", ".join(f'"{column}"' for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS)
    connection.executemany(
        f"INSERT INTO major_index_mins_source ({columns_sql}) VALUES ({placeholders})",
        [
            tuple(row[column] for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS)
            for row in rows
        ],
    )


def _raw_output_sql() -> str:
    columns_sql = ", ".join(f'"{column}"' for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS)
    return (
        f"SELECT {columns_sql} FROM major_index_mins_source "
        "ORDER BY ts_code, trade_time"
    )


def _elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000


def write_major_index_mins_raw_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    source_freq: str,
    partition_key: str,
    run_id: str,
    request_policy: TushareRequestPolicy,
) -> MajorIndexMinsRawWriteResult:
    """Write one Raw frequency/date through staging and no-overwrite promote."""

    started_at = perf_counter()
    normalized_freq = normalize_major_index_mins_source_freq(source_freq)
    normalized_partition = normalize_major_index_mins_trade_date(partition_key)
    expected_codes = effective_raw_request_codes_for_date(normalized_partition)
    scope_hash = raw_scope_hash_for_partition(
        normalized_partition,
        normalized_freq,
    )
    if not expected_codes:
        raise MajorIndexMinsRawValidationError(
            f"source scope is empty for {normalized_partition}."
        )
    target_path = raw_major_index_mins_path(
        lake_root_path,
        normalized_freq,
        normalized_partition,
    )
    staging_path = raw_major_index_mins_staging_path(
        lake_root_path,
        run_id,
        normalized_freq,
        normalized_partition,
    )

    if target_path.exists():
        with duckdb_resource.connect() as connection:
            prepare_major_index_mins_raw_expected_tables(
                connection,
                expected_codes=expected_codes,
                frequency=normalized_freq,
                partition_key=normalized_partition,
            )
            existing_validation = validate_major_index_mins_raw_relation(
                connection,
                relation_sql=read_parquet(target_path, hive_partitioning=False),
                expected_codes=expected_codes,
                frequency=normalized_freq,
                partition_key=normalized_partition,
            )
        if existing_validation.errors:
            raise MajorIndexMinsRawValidationError(
                "existing Raw target is invalid and cannot be overwritten: "
                f"errors={existing_validation.errors!r}, path={target_path}"
            )
        return MajorIndexMinsRawWriteResult(
            partition_key=normalized_partition,
            source_freq=normalized_freq,
            target_path=target_path,
            staging_path=staging_path,
            write_mode="reuse_existing",
            expected_code_count=len(expected_codes),
            source_row_count=existing_validation.row_count,
            output_row_count=existing_validation.row_count,
            request_count=0,
            page_count=0,
            retry_count=0,
            elapsed_ms=_elapsed_ms(started_at),
            source_revision=None,
            scope_hash=scope_hash,
        )

    fetch_result = fetch_major_index_mins_window(
        tushare=tushare,
        ts_codes=expected_codes,
        source_freq=normalized_freq,
        start_datetime=f"{normalized_partition} 00:00:00",
        end_datetime=f"{normalized_partition} 23:59:59",
        request_policy=request_policy,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with duckdb_resource.connect() as connection:
            _create_source_table(connection)
            _insert_source_rows(connection, fetch_result.rows)
            prepare_major_index_mins_raw_expected_tables(
                connection,
                expected_codes=expected_codes,
                frequency=normalized_freq,
                partition_key=normalized_partition,
            )
            source_validation = validate_major_index_mins_raw_relation(
                connection,
                relation_sql="major_index_mins_source",
                expected_codes=expected_codes,
                frequency=normalized_freq,
                partition_key=normalized_partition,
            )
            if source_validation.errors:
                raise MajorIndexMinsRawValidationError(
                    "Raw source validation failed before staging: "
                    f"errors={source_validation.errors!r}"
                )
            connection.execute(copy_query_to_parquet(_raw_output_sql(), staging_path))
            staging_validation = validate_major_index_mins_raw_relation(
                connection,
                relation_sql=read_parquet(staging_path, hive_partitioning=False),
                expected_codes=expected_codes,
                frequency=normalized_freq,
                partition_key=normalized_partition,
            )
            if staging_validation.errors:
                raise MajorIndexMinsRawValidationError(
                    "Raw staging validation failed after readback: "
                    f"errors={staging_validation.errors!r}"
                )
            if staging_validation.row_count != source_validation.row_count:
                raise MajorIndexMinsRawValidationError(
                    "Raw source/staging row reconciliation failed: "
                    f"source={source_validation.row_count}, "
                    f"staging={staging_validation.row_count}."
                )
        if target_path.exists():
            raise MajorIndexMinsRawValidationError(
                f"Raw target appeared during staging; refusing overwrite: {target_path}"
            )
        os.replace(staging_path, target_path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    return MajorIndexMinsRawWriteResult(
        partition_key=normalized_partition,
        source_freq=normalized_freq,
        target_path=target_path,
        staging_path=staging_path,
        write_mode="staged_atomic_replace",
        expected_code_count=len(expected_codes),
        source_row_count=source_validation.row_count,
        output_row_count=staging_validation.row_count,
        request_count=fetch_result.request_count,
        page_count=fetch_result.page_count,
        retry_count=fetch_result.retry_count,
        elapsed_ms=_elapsed_ms(started_at),
        source_revision=fetch_result.source_revision.revision,
        scope_hash=scope_hash,
    )
