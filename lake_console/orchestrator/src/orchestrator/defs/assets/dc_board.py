"""Temporary Raw writers for the Eastmoney board datasets.

M3 deliberately exposes writer functions only.  Dagster assets, checks, jobs,
and sensors are introduced by later milestones after these source and staging
contracts have been proven.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import math
from numbers import Real
import os
from pathlib import Path
import re
from time import perf_counter
from uuid import uuid4

from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    copy_query_to_parquet,
    read_parquet,
)
from orchestrator.defs.paths import raw_dc_daily_path, raw_dc_index_path, raw_dc_member_path
from orchestrator.defs.resources import DuckDBResource, TushareResource, TushareResult
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_DC_DAILY_SCHEMA,
    RAW_TUSHARE_DC_INDEX_SCHEMA,
    RAW_TUSHARE_DC_MEMBER_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_CATEGORIES,
    DC_DAILY_FIELDS,
    DC_DAILY_PAGE_LIMIT,
    DC_INDEX_FIELDS,
    DC_INDEX_PAGE_LIMIT,
    DC_INDEX_TYPES,
    DC_MEMBER_FIELDS,
    DC_MEMBER_PAGE_LIMIT,
    DC_MEMBER_BACKOFF_BASE_SECONDS,
    DC_MEMBER_BACKOFF_MAX_SECONDS,
    DC_MEMBER_MAX_RETRIES,
    DC_MEMBER_MIN_REQUEST_INTERVAL_SECONDS,
    DC_BOARD_MAX_ELAPSED_MS,
    DC_BOARD_MAX_REQUESTS_PER_PARTITION,
)
from orchestrator.defs.tushare_request_policy import (
    BoundedCodeRequestResult,
    TushareRequestPolicy,
    execute_bounded_code_pages,
    execute_bounded_pages,
)


DC_REQUEST_POLICY = TushareRequestPolicy(
    minimum_interval_seconds=DC_MEMBER_MIN_REQUEST_INTERVAL_SECONDS,
    max_retries=DC_MEMBER_MAX_RETRIES,
    backoff_base_seconds=DC_MEMBER_BACKOFF_BASE_SECONDS,
    max_backoff_seconds=DC_MEMBER_BACKOFF_MAX_SECONDS,
    max_requests=DC_BOARD_MAX_REQUESTS_PER_PARTITION,
    max_elapsed_seconds=DC_BOARD_MAX_ELAPSED_MS / 1000,
)


_TRADE_DATE_RE = re.compile(r"^\d{8}$")
_BOARD_CODE_RE = re.compile(r"^BK\d{4}\.DC$")
_RAW_TYPES = {
    "dc_index": {column.name: column.type for column in RAW_TUSHARE_DC_INDEX_SCHEMA},
    "dc_member": {column.name: column.type for column in RAW_TUSHARE_DC_MEMBER_SCHEMA},
    "dc_daily": {column.name: column.type for column in RAW_TUSHARE_DC_DAILY_SCHEMA},
}


class DcBoardRawValidationError(ValueError):
    """Raised before promotion when a Raw partition is not internally valid."""


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


@dataclass(frozen=True, slots=True)
class DcBoardRawWriteResult:
    partition_key: str
    source_method: str
    target_path: Path
    source_row_count: int
    written_row_count: int
    duplicate_key_count: int
    invalid_code_count: int
    out_of_partition_count: int
    request_count: int
    page_count: int
    retry_count: int
    elapsed_ms: float
    failed_code_count: int = 0
    empty_code_count: int = 0
    failed_codes: tuple[str, ...] = ()
    empty_codes: tuple[str, ...] = ()
    chunk_count: int = 0

    def to_metadata(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "source_method": self.source_method,
            "source_closure_status": "validated_before_promote",
            "target_path": str(self.target_path),
            "source_row_count": self.source_row_count,
            "written_row_count": self.written_row_count,
            "duplicate_key_count": self.duplicate_key_count,
            "invalid_code_count": self.invalid_code_count,
            "out_of_partition_count": self.out_of_partition_count,
            "request_count": self.request_count,
            "page_count": self.page_count,
            "retry_count": self.retry_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "failed_code_count": self.failed_code_count,
            "empty_code_count": self.empty_code_count,
            "failed_codes": list(self.failed_codes[:20]),
            "empty_codes": list(self.empty_codes[:20]),
            "chunk_count": self.chunk_count,
        }


def _canonical_trade_date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace("-", "")
    return compact if _TRADE_DATE_RE.fullmatch(compact) else text


def _iso_to_raw_trade_date(partition_key: str) -> str:
    try:
        return date.fromisoformat(partition_key).strftime("%Y%m%d")
    except ValueError as exc:
        raise DcBoardRawValidationError(
            f"partition_key must be ISO date YYYY-MM-DD: {partition_key!r}"
        ) from exc


def _normalize_row(row: Mapping[str, object], fields: Sequence[str]) -> dict[str, object]:
    normalized = {}
    for field in fields:
        value = row.get(field)
        if isinstance(value, Real) and not isinstance(value, bool) and math.isnan(value):
            value = None
        normalized[field] = value
    if "trade_date" in normalized:
        normalized["trade_date"] = _canonical_trade_date(normalized["trade_date"])
    return normalized


def _normalize_rows(
    rows: Iterable[Mapping[str, object]], fields: Sequence[str]
) -> list[dict[str, object]]:
    return [_normalize_row(row, fields) for row in rows]


def _validate_response_columns(result: TushareResult, fields: Sequence[str]) -> None:
    expected = tuple(fields)
    if result.columns and tuple(result.columns) != expected:
        raise DcBoardRawValidationError(
            f"Tushare response columns drifted: expected {expected}, got {result.columns}."
        )


def _create_table(connection, dataset: str) -> None:
    column_types = _RAW_TYPES[dataset]
    fields = tuple(column_types)
    definitions = ", ".join(
        f"{_quoted_identifier(field)} {column_types[field]}" for field in fields
    )
    connection.execute(f"CREATE TEMP TABLE dc_board_rows ({definitions})")


def _insert_rows(
    connection,
    *,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    if not rows:
        return
    placeholders = ", ".join("?" for _ in fields)
    values = [tuple(row.get(field) for field in fields) for row in rows]
    connection.executemany(
        f"INSERT INTO dc_board_rows ({', '.join(_quoted_identifier(field) for field in fields)}) "
        f"VALUES ({placeholders})",
        values,
    )


def _validation_counts(connection, dataset: str, raw_trade_date: str) -> tuple[int, int, int, int]:
    if dataset == "dc_index":
        duplicate_sql = """
            SELECT count(*) FROM (
                SELECT ts_code, trade_date
                FROM dc_board_rows
                GROUP BY ts_code, trade_date
                HAVING count(*) > 1
            )
        """
        invalid_sql = """
            SELECT count(*) FROM dc_board_rows
            WHERE ts_code IS NULL OR NOT regexp_full_match(trim(ts_code), '^BK[0-9]{4}\\.DC$')
               OR idx_type IS NULL OR idx_type NOT IN ('行业板块', '概念板块', '地域板块')
        """
        name_sql = "SELECT count(*) FROM dc_board_rows WHERE name IS NULL OR trim(name) = ''"
    elif dataset == "dc_member":
        duplicate_sql = """
            SELECT count(*) FROM (
                SELECT trade_date, ts_code, con_code
                FROM dc_board_rows
                GROUP BY trade_date, ts_code, con_code
                HAVING count(*) > 1
            )
        """
        invalid_sql = """
            SELECT count(*) FROM dc_board_rows
            WHERE ts_code IS NULL OR NOT regexp_full_match(trim(ts_code), '^BK[0-9]{4}\\.DC$')
               OR con_code IS NULL OR NOT regexp_full_match(trim(con_code), '^[0-9]{6}\\.(SZ|SH|BJ)$')
        """
        name_sql = "SELECT count(*) FROM dc_board_rows WHERE name IS NULL OR trim(name) = ''"
    elif dataset == "dc_daily":
        duplicate_sql = """
            SELECT count(*) FROM (
                SELECT ts_code, trade_date, category
                FROM dc_board_rows
                GROUP BY ts_code, trade_date, category
                HAVING count(*) > 1
            )
        """
        invalid_sql = """
            SELECT count(*) FROM dc_board_rows
            WHERE ts_code IS NULL OR NOT regexp_full_match(trim(ts_code), '^BK[0-9]{4}\\.DC$')
               OR category IS NULL OR category NOT IN ('行业板块', '概念板块', '地域板块')
        """
        name_sql = "SELECT 0"
    else:
        raise ValueError(f"unsupported board dataset: {dataset}")

    duplicate_count = int(connection.execute(duplicate_sql).fetchone()[0])
    invalid_code_count = int(connection.execute(invalid_sql).fetchone()[0])
    blank_name_count = int(connection.execute(name_sql).fetchone()[0])
    out_of_partition_count = int(
        connection.execute(
            """
            SELECT count(*) FROM dc_board_rows
            WHERE trade_date IS NULL OR trade_date <> ?
            """,
            [raw_trade_date],
        ).fetchone()[0]
    )
    return duplicate_count, invalid_code_count, out_of_partition_count, blank_name_count


def _promote_table(
    connection,
    *,
    dataset: str,
    partition_key: str,
    target_path: Path,
    source_method: str,
    request_count: int,
    page_count: int,
    retry_count: int,
    started_at: float,
    failed_codes: Sequence[str] = (),
    empty_codes: Sequence[str] = (),
    chunk_count: int = 0,
) -> DcBoardRawWriteResult:
    fields = tuple(_RAW_TYPES[dataset])
    raw_trade_date = _iso_to_raw_trade_date(partition_key)
    source_row_count = int(connection.execute("SELECT count(*) FROM dc_board_rows").fetchone()[0])
    if source_row_count == 0:
        raise DcBoardRawValidationError(
            f"{dataset} returned no rows for open trade date {partition_key}."
        )

    duplicate_count, invalid_count, out_of_partition_count, blank_name_count = _validation_counts(
        connection, dataset, raw_trade_date
    )
    if duplicate_count or invalid_count or blank_name_count or out_of_partition_count:
        raise DcBoardRawValidationError(
            f"{dataset} validation failed for {partition_key}: "
            f"duplicate_key_count={duplicate_count}, "
            f"invalid_code_count={invalid_count}, "
            f"blank_name_count={blank_name_count}, "
            f"out_of_partition_count={out_of_partition_count}."
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = target_path.with_name(f"{target_path.name}.m3-{uuid4().hex}.tmp")
    try:
        select_sql = "SELECT " + ", ".join(
            f"CAST({_quoted_identifier(field)} AS {_RAW_TYPES[dataset][field]}) "
            f"AS {_quoted_identifier(field)}"
            for field in fields
        ) + " FROM dc_board_rows"
        connection.execute(copy_query_to_parquet(select_sql, staging_path))
        observed_columns = tuple(
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT "
                + ", ".join(_quoted_identifier(field) for field in fields)
                + f" FROM {read_parquet(staging_path, hive_partitioning=False)}"
            ).fetchall()
        )
        if observed_columns != fields:
            raise DcBoardRawValidationError(
                f"staging schema reconciliation failed: expected {fields}, "
                f"got {observed_columns}."
            )
        observed_count = int(
            connection.execute(count_parquet_query(staging_path, hive_partitioning=False))
            .fetchone()[0]
        )
        if observed_count != source_row_count:
            raise DcBoardRawValidationError(
                f"staging row reconciliation failed: source={source_row_count}, "
                f"written={observed_count}."
            )
        os.replace(staging_path, target_path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    return DcBoardRawWriteResult(
        partition_key=partition_key,
        source_method=source_method,
        target_path=target_path,
        source_row_count=source_row_count,
        written_row_count=observed_count,
        duplicate_key_count=duplicate_count,
        invalid_code_count=invalid_count,
        out_of_partition_count=out_of_partition_count,
        request_count=request_count,
        page_count=page_count,
        retry_count=retry_count,
        elapsed_ms=(perf_counter() - started_at) * 1000,
        failed_code_count=len(tuple(failed_codes)),
        empty_code_count=len(tuple(empty_codes)),
        failed_codes=tuple(failed_codes),
        empty_codes=tuple(empty_codes),
        chunk_count=chunk_count,
    )


def _tushare_extract_rows(result: TushareResult, fields: Sequence[str]) -> Sequence[Mapping[str, object]]:
    _validate_response_columns(result, fields)
    return _normalize_rows(result.rows, fields)


def _validate_dc_daily_same_day_index_coverage(
    connection,
    *,
    index_path: Path,
) -> None:
    """Reject a partial ``dc_daily`` response before it can replace the target file."""

    if not index_path.exists():
        raise DcBoardRawValidationError(
            f"dc_daily source closure requires same-day raw dc_index: {index_path}"
        )

    row = connection.execute(
        f"""
        WITH daily_codes AS (
            SELECT DISTINCT trim(CAST(ts_code AS VARCHAR)) AS ts_code
            FROM dc_board_rows
            WHERE ts_code IS NOT NULL AND trim(CAST(ts_code AS VARCHAR)) <> ''
        ), index_codes AS (
            SELECT DISTINCT trim(CAST(ts_code AS VARCHAR)) AS ts_code
            FROM {read_parquet(index_path)}
            WHERE ts_code IS NOT NULL AND trim(CAST(ts_code AS VARCHAR)) <> ''
        ), missing_codes AS (
            SELECT ts_code FROM index_codes
            EXCEPT
            SELECT ts_code FROM daily_codes
        ), extra_codes AS (
            SELECT ts_code FROM daily_codes
            EXCEPT
            SELECT ts_code FROM index_codes
        )
        SELECT
            (SELECT count(*) FROM daily_codes),
            (SELECT count(*) FROM index_codes),
            (SELECT count(*) FROM missing_codes),
            (SELECT count(*) FROM extra_codes),
            (SELECT list(ts_code ORDER BY ts_code) FROM (SELECT ts_code FROM missing_codes LIMIT 5)),
            (SELECT list(ts_code ORDER BY ts_code) FROM (SELECT ts_code FROM extra_codes LIMIT 5))
        """
    ).fetchone()
    daily_count, index_count, missing_count, extra_count, missing_sample, extra_sample = row
    if int(index_count or 0) <= 0:
        raise DcBoardRawValidationError(
            f"dc_daily source closure found no board codes in same-day raw dc_index: {index_path}"
        )
    if int(missing_count or 0) or int(extra_count or 0):
        raise DcBoardRawValidationError(
            "dc_daily same-day board code coverage is incomplete before target promotion: "
            f"daily_code_count={int(daily_count or 0)}, "
            f"index_code_count={int(index_count or 0)}, "
            f"missing_index_code_count={int(missing_count or 0)}, "
            f"extra_daily_code_count={int(extra_count or 0)}, "
            f"missing_index_code_sample={list(missing_sample or ())}, "
            f"extra_daily_code_sample={list(extra_sample or ())}."
        )


def write_dc_index_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    partition_key: str,
    policy=DC_REQUEST_POLICY,
) -> DcBoardRawWriteResult:
    """Fetch and atomically write one ``dc_index`` trade-date partition."""

    started_at = perf_counter()
    with duckdb_resource.connect() as connection:
        _create_table(connection, "dc_index")
        result: BoundedCodeRequestResult[TushareResult] = execute_bounded_code_pages(
            codes=DC_INDEX_TYPES,
            request_page=lambda idx_type, offset: tushare.call(
                    "dc_index",
                    {
                        "trade_date": partition_key.replace("-", ""),
                        "idx_type": idx_type,
                        "limit": 5_000,
                        "offset": offset,
                    },
                    DC_INDEX_FIELDS,
                ),
            extract_rows=lambda result: _tushare_extract_rows(result, DC_INDEX_FIELDS),
            page_size=DC_INDEX_PAGE_LIMIT,
            policy=policy,
            row_key=lambda row: (row.get("ts_code"), row.get("trade_date")),
        )
        if not result.ready:
            raise DcBoardRawValidationError(
                f"dc_index request failed: {result.to_details()}"
            )
        for idx_type in DC_INDEX_TYPES:
            page_rows = result.rows_by_code.get(idx_type, [])
            mismatched_idx_type = [
                row
                for row in page_rows
                if row.get("idx_type") != idx_type
            ]
            if mismatched_idx_type:
                raise DcBoardRawValidationError(
                    f"dc_index response contains rows for a different idx_type: "
                    f"requested={idx_type}, sample={mismatched_idx_type[:3]}"
                )
            _insert_rows(connection, fields=DC_INDEX_FIELDS, rows=page_rows)

        if not any(result.rows_by_code.values()):
            raise DcBoardRawValidationError(
                f"dc_index returned no rows across all idx_type values for {partition_key}."
            )
        return _promote_table(
            connection,
            dataset="dc_index",
            partition_key=partition_key,
            target_path=raw_dc_index_path(lake_root_path, partition_key),
            source_method="tushare_api",
            request_count=result.request_count,
            page_count=sum(result.page_counts.values()),
            retry_count=result.retry_count,
            started_at=started_at,
        )


def write_dc_daily_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    partition_key: str,
    policy=DC_REQUEST_POLICY,
) -> DcBoardRawWriteResult:
    """Fetch and atomically write one ``dc_daily`` trade-date partition."""

    started_at = perf_counter()
    with duckdb_resource.connect() as connection:
        _create_table(connection, "dc_daily")
        page_result = execute_bounded_pages(
            request_page=lambda offset: tushare.call(
                "dc_daily",
                {
                    "trade_date": partition_key.replace("-", ""),
                    "limit": 2_000,
                    "offset": offset,
                },
                DC_DAILY_FIELDS,
            ),
            extract_rows=lambda result: _tushare_extract_rows(result, DC_DAILY_FIELDS),
            page_size=DC_DAILY_PAGE_LIMIT,
            policy=policy,
            scope=f"dc_daily:{partition_key}",
            row_key=lambda row: (row.get("ts_code"), row.get("trade_date"), row.get("category")),
        )
        if not page_result.ready:
            raise DcBoardRawValidationError(
                f"dc_daily request failed: {page_result.to_details()}"
            )
        _insert_rows(connection, fields=DC_DAILY_FIELDS, rows=page_result.rows)
        category_count = int(
            connection.execute(
                "SELECT count(DISTINCT category) FROM dc_board_rows"
            ).fetchone()[0]
        )
        if category_count < len(DC_DAILY_CATEGORIES):
            raise DcBoardRawValidationError(
                "dc_daily category coverage is incomplete: "
                f"observed={category_count}, expected={len(DC_DAILY_CATEGORIES)}."
            )
        _validate_dc_daily_same_day_index_coverage(
            connection,
            index_path=raw_dc_index_path(lake_root_path, partition_key),
        )
        return _promote_table(
            connection,
            dataset="dc_daily",
            partition_key=partition_key,
            target_path=raw_dc_daily_path(lake_root_path, partition_key),
            source_method="tushare_api",
            request_count=page_result.request_count,
            page_count=page_result.page_count,
            retry_count=page_result.retry_count,
            started_at=started_at,
        )


def write_dc_member_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    partition_key: str,
    candidate_codes: Sequence[str],
    policy=DC_REQUEST_POLICY,
) -> DcBoardRawWriteResult:
    """Fetch one member request per candidate board code and atomically write it."""

    normalized_codes = tuple(str(code).strip().upper() for code in candidate_codes)
    if not normalized_codes:
        raise DcBoardRawValidationError("dc_member candidate_codes must not be empty.")
    invalid_candidates = tuple(code for code in normalized_codes if not _BOARD_CODE_RE.fullmatch(code))
    if invalid_candidates:
        raise DcBoardRawValidationError(
            "dc_member candidate_codes contain invalid board codes: "
            f"{invalid_candidates[:20]}"
        )
    started_at = perf_counter()
    with duckdb_resource.connect() as connection:
        _create_table(connection, "dc_member")
        result: BoundedCodeRequestResult[TushareResult] = execute_bounded_code_pages(
            codes=normalized_codes,
            request_page=lambda code, offset: tushare.call(
                "dc_member",
                {
                    "trade_date": partition_key.replace("-", ""),
                    "ts_code": code,
                    "limit": DC_MEMBER_PAGE_LIMIT,
                    "offset": offset,
                },
                DC_MEMBER_FIELDS,
            ),
            extract_rows=lambda response: _tushare_extract_rows(response, DC_MEMBER_FIELDS),
            page_size=DC_MEMBER_PAGE_LIMIT,
            policy=policy,
            row_key=lambda row: (row.get("trade_date"), row.get("ts_code"), row.get("con_code")),
        )
        if not result.ready:
            raise DcBoardRawValidationError(
                f"dc_member request failed: {result.to_details()}"
            )
        mismatched_codes = [
            row
            for code in result.successful_codes
            for row in result.rows_by_code[code]
            if row.get("ts_code") != code
        ]
        if mismatched_codes:
            raise DcBoardRawValidationError(
                "dc_member response contains rows for a different requested board code: "
                f"sample={mismatched_codes[:3]}"
            )
        all_rows = [row for code in result.successful_codes for row in result.rows_by_code[code]]
        if not all_rows:
            raise DcBoardRawValidationError(
                f"dc_member returned no rows for any candidate code on {partition_key}."
            )
        _insert_rows(connection, fields=DC_MEMBER_FIELDS, rows=all_rows)
        return _promote_table(
            connection,
            dataset="dc_member",
            partition_key=partition_key,
            target_path=raw_dc_member_path(lake_root_path, partition_key),
            source_method="tushare_api_by_ts_code",
            request_count=result.request_count,
            page_count=sum(result.page_counts.values()),
            retry_count=result.retry_count,
            started_at=started_at,
            empty_codes=result.empty_codes,
        )


def write_dc_member_rows_streaming(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    chunks: Iterable[Sequence[Mapping[str, object]]],
    source_method: str = "prod_db_readonly_export",
    chunk_count: int = 0,
) -> DcBoardRawWriteResult:
    """Write member rows from a bounded stream without collecting a full day."""

    started_at = perf_counter()
    observed_chunks = 0
    with duckdb_resource.connect() as connection:
        _create_table(connection, "dc_member")
        for chunk in chunks:
            normalized_rows = _normalize_rows(chunk, DC_MEMBER_FIELDS)
            if normalized_rows:
                _insert_rows(connection, fields=DC_MEMBER_FIELDS, rows=normalized_rows)
            observed_chunks += 1
        return _promote_table(
            connection,
            dataset="dc_member",
            partition_key=partition_key,
            target_path=raw_dc_member_path(lake_root_path, partition_key),
            source_method=source_method,
            request_count=0,
            page_count=observed_chunks,
            retry_count=0,
            started_at=started_at,
            chunk_count=chunk_count or observed_chunks,
        )


__all__ = [
    "DcBoardRawValidationError",
    "DcBoardRawWriteResult",
    "write_dc_daily_partition",
    "write_dc_index_partition",
    "write_dc_member_partition",
    "write_dc_member_rows_streaming",
]
