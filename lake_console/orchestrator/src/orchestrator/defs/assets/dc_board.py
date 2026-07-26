"""Temporary Raw writers for the Eastmoney board datasets.

M3 deliberately exposes writer functions only.  Dagster assets, checks, jobs,
and sensors are introduced by later milestones after these source and staging
contracts have been proven.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime
import math
from numbers import Real
import os
from pathlib import Path
import re
from time import perf_counter
from uuid import uuid4

from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardReferenceValidationError,
    assert_dc_daily_rows_match_reference,
    build_dc_board_request_policy,
    load_prod_dc_member_pairs,
    require_closed_prod_dc_board_reference,
    require_tushare_index_and_daily_reference_match,
)
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    copy_query_to_parquet,
    read_parquet,
)
from orchestrator.defs.paths import raw_dc_daily_path, raw_dc_index_path, raw_dc_member_path
from orchestrator.defs.resources import (
    DuckDBResource,
    ProdPostgresResource,
    TushareResource,
    TushareResult,
)
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
    DC_INDEX_TYPES,
    DC_MEMBER_FIELDS,
    DC_MEMBER_PAGE_LIMIT,
)
from orchestrator.defs.run_contracts.configs import (
    DcBoardIndexReferenceConfig,
    validate_dc_board_index_reference_config,
)
from orchestrator.defs.tushare_request_policy import (
    BoundedCodePageRequestSession,
    BoundedCodeRequestResult,
    execute_bounded_pages,
)


DC_REQUEST_POLICY = build_dc_board_request_policy()


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
    reference_fingerprint: str | None = None
    reference_observed_at: str | None = None
    source_closure_diagnostics: Mapping[str, int] = dataclass_field(default_factory=dict)

    def to_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
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
            "reference_fingerprint": self.reference_fingerprint,
            "reference_observed_at": self.reference_observed_at,
        }
        metadata.update(self.source_closure_diagnostics)
        return metadata


@dataclass(frozen=True, slots=True)
class _DcMemberPairDiff:
    missing_pair_count: int
    extra_pair_count: int
    repair_codes: tuple[str, ...]
    missing_pair_samples: tuple[tuple[str, str], ...]
    extra_pair_samples: tuple[tuple[str, str], ...]


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
    reference_fingerprint: str | None = None,
    reference_observed_at: str | None = None,
    source_closure_diagnostics: Mapping[str, int] | None = None,
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
        reference_fingerprint=reference_fingerprint,
        reference_observed_at=reference_observed_at,
        source_closure_diagnostics=source_closure_diagnostics or {},
    )


def _tushare_extract_rows(result: TushareResult, fields: Sequence[str]) -> Sequence[Mapping[str, object]]:
    _validate_response_columns(result, fields)
    return _normalize_rows(result.rows, fields)


def _validate_dc_daily_same_day_index_coverage(
    connection,
    *,
    index_path: Path,
    expected_index_identity: Sequence[tuple[str, str]],
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
    raw_index_identity = tuple(
        (str(idx_type).strip(), str(ts_code).strip().upper())
        for idx_type, ts_code in connection.execute(
            f"""
            SELECT DISTINCT
                trim(CAST(idx_type AS VARCHAR)),
                upper(trim(CAST(ts_code AS VARCHAR)))
            FROM {read_parquet(index_path)}
            WHERE idx_type IS NOT NULL AND trim(CAST(idx_type AS VARCHAR)) <> ''
              AND ts_code IS NOT NULL AND trim(CAST(ts_code AS VARCHAR)) <> ''
            ORDER BY 1, 2
            """
        ).fetchall()
    )
    expected_identity = tuple(sorted(expected_index_identity))
    missing_identity_count = len(set(expected_identity) - set(raw_index_identity))
    extra_identity_count = len(set(raw_index_identity) - set(expected_identity))
    if missing_identity_count or extra_identity_count:
        raise DcBoardRawValidationError(
            "dc_daily source closure found a same-day raw dc_index identity mismatch: "
            f"missing_index_identity_count={missing_identity_count}, "
            f"extra_index_identity_count={extra_identity_count}."
        )


def _load_prod_dc_member_pairs_for_comparison(
    connection,
    *,
    prod_pairs: Sequence[tuple[str, str]],
) -> None:
    """Load the fixed prod member-pair baseline for one writer invocation."""

    connection.execute("DROP TABLE IF EXISTS prod_dc_member_pairs")
    connection.execute(
        "CREATE TEMP TABLE prod_dc_member_pairs (ts_code VARCHAR, con_code VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO prod_dc_member_pairs (ts_code, con_code) VALUES (?, ?)",
        prod_pairs,
    )


def _inspect_dc_member_pair_diff(connection) -> _DcMemberPairDiff:
    """Return the current DuckDB source/prod member-pair difference."""

    connection.execute("DROP TABLE IF EXISTS dc_member_missing_pairs")
    connection.execute("DROP TABLE IF EXISTS dc_member_extra_pairs")
    connection.execute(
        """
        CREATE TEMP TABLE dc_member_missing_pairs AS
        WITH source_pairs AS (
            SELECT DISTINCT
                upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
                upper(trim(CAST(con_code AS VARCHAR))) AS con_code
            FROM dc_board_rows
        ), prod_pairs AS (
            SELECT DISTINCT
                upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
                upper(trim(CAST(con_code AS VARCHAR))) AS con_code
            FROM prod_dc_member_pairs
        )
        SELECT ts_code, con_code FROM prod_pairs
        EXCEPT
        SELECT ts_code, con_code FROM source_pairs
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE dc_member_extra_pairs AS
        WITH source_pairs AS (
            SELECT DISTINCT
                upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
                upper(trim(CAST(con_code AS VARCHAR))) AS con_code
            FROM dc_board_rows
        ), prod_pairs AS (
            SELECT DISTINCT
                upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
                upper(trim(CAST(con_code AS VARCHAR))) AS con_code
            FROM prod_dc_member_pairs
        )
        SELECT ts_code, con_code FROM source_pairs
        EXCEPT
        SELECT ts_code, con_code FROM prod_pairs
        """
    )
    missing_count = int(
        connection.execute("SELECT count(*) FROM dc_member_missing_pairs").fetchone()[0]
    )
    extra_count = int(
        connection.execute("SELECT count(*) FROM dc_member_extra_pairs").fetchone()[0]
    )
    repair_codes = tuple(
        str(row[0])
        for row in connection.execute(
            """
            SELECT DISTINCT ts_code
            FROM dc_member_missing_pairs
            ORDER BY ts_code
            """
        ).fetchall()
    )
    missing_pair_samples = tuple(
        (str(ts_code), str(con_code))
        for ts_code, con_code in connection.execute(
            """
            SELECT ts_code, con_code
            FROM dc_member_missing_pairs
            ORDER BY ts_code, con_code
            LIMIT 20
            """
        ).fetchall()
    )
    extra_pair_samples = tuple(
        (str(ts_code), str(con_code))
        for ts_code, con_code in connection.execute(
            """
            SELECT ts_code, con_code
            FROM dc_member_extra_pairs
            ORDER BY ts_code, con_code
            LIMIT 20
            """
        ).fetchall()
    )
    return _DcMemberPairDiff(
        missing_pair_count=missing_count,
        extra_pair_count=extra_count,
        repair_codes=repair_codes,
        missing_pair_samples=missing_pair_samples,
        extra_pair_samples=extra_pair_samples,
    )


def _raise_dc_member_pair_diff_error(
    pair_diff: _DcMemberPairDiff,
    *,
    phase: str,
) -> None:
    raise DcBoardRawValidationError(
        "dc_member Tushare/prod pair identity differs before target promotion: "
        f"phase={phase}, "
        f"missing_pair_count={pair_diff.missing_pair_count}, "
        f"extra_pair_count={pair_diff.extra_pair_count}, "
        f"missing_pair_samples={list(pair_diff.missing_pair_samples)}, "
        f"extra_pair_samples={list(pair_diff.extra_pair_samples)}."
    )


def _assert_dc_member_rows_valid_for_pair_comparison(
    connection,
    *,
    partition_key: str,
) -> None:
    """Reject structural member defects before deciding whether a retry is safe."""

    duplicate_count, invalid_count, out_of_partition_count, blank_name_count = _validation_counts(
        connection,
        "dc_member",
        _iso_to_raw_trade_date(partition_key),
    )
    if duplicate_count or invalid_count or blank_name_count or out_of_partition_count:
        raise DcBoardRawValidationError(
            f"dc_member validation failed for {partition_key}: "
            f"duplicate_key_count={duplicate_count}, "
            f"invalid_code_count={invalid_count}, "
            f"blank_name_count={blank_name_count}, "
            f"out_of_partition_count={out_of_partition_count}."
        )


def _replace_dc_member_rows_for_repair_codes(
    connection,
    *,
    repair_codes: Sequence[str],
    replacement_rows: Sequence[Mapping[str, object]],
) -> None:
    """Replace full member rows for retried board codes inside the temporary table."""

    connection.execute("DROP TABLE IF EXISTS dc_member_repair_codes")
    connection.execute("CREATE TEMP TABLE dc_member_repair_codes (ts_code VARCHAR)")
    connection.executemany(
        "INSERT INTO dc_member_repair_codes (ts_code) VALUES (?)",
        [(code,) for code in repair_codes],
    )
    connection.execute(
        """
        DELETE FROM dc_board_rows
        WHERE ts_code IN (SELECT ts_code FROM dc_member_repair_codes)
        """
    )
    _insert_rows(connection, fields=DC_MEMBER_FIELDS, rows=replacement_rows)


def _dc_member_rows_from_request_result(
    result: BoundedCodeRequestResult[TushareResult],
    *,
    phase: str,
) -> list[dict[str, object]]:
    """Return validated member rows from one bounded request batch."""

    if not result.ready:
        details = result.to_details()
        details["empty_codes"] = list(result.empty_codes[:20])
        details["empty_code_list_truncated"] = len(result.empty_codes) > 20
        raise DcBoardRawValidationError(
            f"dc_member {phase} request failed: {details}"
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
            f"phase={phase}, sample={mismatched_codes[:3]}"
        )
    return [
        row
        for code in result.successful_codes
        for row in result.rows_by_code[code]
    ]


def write_dc_index_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    partition_key: str,
    reference_config: DcBoardIndexReferenceConfig,
    policy=DC_REQUEST_POLICY,
) -> DcBoardRawWriteResult:
    """Fetch and atomically write one ``dc_index`` trade-date partition."""

    started_at = perf_counter()
    validated_config = validate_dc_board_index_reference_config(
        reference_config,
        partition_key=partition_key,
    )
    try:
        fresh_reference = require_closed_prod_dc_board_reference(
            prod_postgres=prod_postgres,
            trade_date=partition_key,
        )
    except DcBoardReferenceValidationError as exc:
        raise DcBoardRawValidationError(str(exc)) from exc
    if fresh_reference.fingerprint != validated_config.reference_fingerprint:
        raise DcBoardRawValidationError(
            "dc_index prod reference changed after sensor freeze; target promotion is blocked: "
            f"sensor_fingerprint={validated_config.reference_fingerprint}, "
            f"writer_fingerprint={fresh_reference.fingerprint}."
        )
    try:
        comparison = require_tushare_index_and_daily_reference_match(
            tushare=tushare,
            trade_date=partition_key,
            reference=fresh_reference,
            policy=policy,
        )
    except DcBoardReferenceValidationError as exc:
        raise DcBoardRawValidationError(str(exc)) from exc
    with duckdb_resource.connect() as connection:
        _create_table(connection, "dc_index")
        for idx_type in DC_INDEX_TYPES:
            page_rows = comparison.index_rows_by_type.get(idx_type, ())
            _insert_rows(connection, fields=DC_INDEX_FIELDS, rows=page_rows)

        if not any(comparison.index_rows_by_type.values()):
            raise DcBoardRawValidationError(
                f"dc_index returned no rows across all idx_type values for {partition_key}."
            )
        return _promote_table(
            connection,
            dataset="dc_index",
            partition_key=partition_key,
            target_path=raw_dc_index_path(lake_root_path, partition_key),
            source_method="tushare_api",
            request_count=comparison.request_count,
            page_count=comparison.page_count,
            retry_count=comparison.retry_count,
            started_at=started_at,
            reference_fingerprint=fresh_reference.fingerprint,
            reference_observed_at=validated_config.reference_observed_at,
        )


def write_dc_daily_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    partition_key: str,
    policy=DC_REQUEST_POLICY,
) -> DcBoardRawWriteResult:
    """Fetch and atomically write one ``dc_daily`` trade-date partition."""

    started_at = perf_counter()
    try:
        fresh_reference = require_closed_prod_dc_board_reference(
            prod_postgres=prod_postgres,
            trade_date=partition_key,
        )
    except DcBoardReferenceValidationError as exc:
        raise DcBoardRawValidationError(str(exc)) from exc
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
        try:
            assert_dc_daily_rows_match_reference(
                rows=page_result.rows,
                trade_date=partition_key,
                reference=fresh_reference,
            )
        except DcBoardReferenceValidationError as exc:
            raise DcBoardRawValidationError(str(exc)) from exc
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
            expected_index_identity=fresh_reference.index_identity,
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
            reference_fingerprint=fresh_reference.fingerprint,
        )


def write_dc_member_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
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
    try:
        fresh_reference = require_closed_prod_dc_board_reference(
            prod_postgres=prod_postgres,
            trade_date=partition_key,
        )
    except DcBoardReferenceValidationError as exc:
        raise DcBoardRawValidationError(str(exc)) from exc
    if tuple(sorted(set(normalized_codes))) != fresh_reference.member_codes:
        raise DcBoardRawValidationError(
            "dc_member candidate codes must exactly match the same-day prod reference: "
            f"candidate_code_count={len(set(normalized_codes))}, "
            f"reference_code_count={fresh_reference.member_code_count}."
        )
    with duckdb_resource.connect() as connection:
        _create_table(connection, "dc_member")
        request_session = BoundedCodePageRequestSession(policy=policy)
        initial_result = request_session.execute(
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
            row_key=lambda row: (row.get("trade_date"), row.get("ts_code"), row.get("con_code")),
        )
        initial_rows = _dc_member_rows_from_request_result(
            initial_result,
            phase="initial",
        )
        if not initial_rows:
            raise DcBoardRawValidationError(
                f"dc_member returned no rows for any candidate code on {partition_key}."
            )
        _insert_rows(connection, fields=DC_MEMBER_FIELDS, rows=initial_rows)
        _assert_dc_member_rows_valid_for_pair_comparison(
            connection,
            partition_key=partition_key,
        )
        try:
            prod_pairs = load_prod_dc_member_pairs(
                prod_postgres=prod_postgres,
                trade_date=partition_key,
            )
        except DcBoardReferenceValidationError as exc:
            raise DcBoardRawValidationError(str(exc)) from exc
        _load_prod_dc_member_pairs_for_comparison(connection, prod_pairs=prod_pairs)
        initial_pair_diff = _inspect_dc_member_pair_diff(connection)
        repair_result: BoundedCodeRequestResult[TushareResult] | None = None
        final_pair_diff = initial_pair_diff
        if initial_pair_diff.extra_pair_count:
            _raise_dc_member_pair_diff_error(initial_pair_diff, phase="initial")
        if initial_pair_diff.missing_pair_count:
            repair_result = request_session.execute(
                codes=initial_pair_diff.repair_codes,
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
                extract_rows=lambda response: _tushare_extract_rows(
                    response,
                    DC_MEMBER_FIELDS,
                ),
                page_size=DC_MEMBER_PAGE_LIMIT,
                row_key=lambda row: (
                    row.get("trade_date"),
                    row.get("ts_code"),
                    row.get("con_code"),
                ),
            )
            repair_rows = _dc_member_rows_from_request_result(
                repair_result,
                phase="missing_pair_repair",
            )
            _replace_dc_member_rows_for_repair_codes(
                connection,
                repair_codes=initial_pair_diff.repair_codes,
                replacement_rows=repair_rows,
            )
            _assert_dc_member_rows_valid_for_pair_comparison(
                connection,
                partition_key=partition_key,
            )
            final_pair_diff = _inspect_dc_member_pair_diff(connection)
        if final_pair_diff.missing_pair_count or final_pair_diff.extra_pair_count:
            _raise_dc_member_pair_diff_error(final_pair_diff, phase="final")

        repair_page_count = (
            sum(repair_result.page_counts.values()) if repair_result is not None else 0
        )
        repair_request_count = repair_result.request_count if repair_result is not None else 0
        repair_retry_count = repair_result.retry_count if repair_result is not None else 0
        return _promote_table(
            connection,
            dataset="dc_member",
            partition_key=partition_key,
            target_path=raw_dc_member_path(lake_root_path, partition_key),
            source_method="tushare_api_by_ts_code",
            request_count=request_session.request_count,
            page_count=sum(initial_result.page_counts.values()) + repair_page_count,
            retry_count=request_session.retry_count,
            started_at=started_at,
            empty_codes=initial_result.empty_codes,
            reference_fingerprint=fresh_reference.fingerprint,
            source_closure_diagnostics={
                "member_initial_missing_pair_count": initial_pair_diff.missing_pair_count,
                "member_repair_code_count": len(initial_pair_diff.repair_codes)
                if repair_result is not None
                else 0,
                "member_repair_request_count": repair_request_count,
                "member_repair_page_count": repair_page_count,
                "member_repair_retry_count": repair_retry_count,
                "member_recovered_pair_count": (
                    initial_pair_diff.missing_pair_count - final_pair_diff.missing_pair_count
                ),
                "member_final_missing_pair_count": final_pair_diff.missing_pair_count,
                "member_final_extra_pair_count": final_pair_diff.extra_pair_count,
            },
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
