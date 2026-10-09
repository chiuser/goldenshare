"""Temporary Raw writers for the Eastmoney board datasets.

M3 deliberately exposes writer functions only.  Dagster assets, checks, jobs,
and sensors are introduced by later milestones after these source and staging
contracts have been proven.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import date, datetime
from numbers import Real
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.dc_board_quote_coverage import (
    batch_board_quote_coverage,
)
from orchestrator.defs.asset_guards.dc_board_source_freeze import (
    revalidate_dc_board_source,
)
from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardSourceValidationError,
    build_dc_board_request_policy,
    load_prod_dc_member_pairs,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    read_parquet,
)
from orchestrator.defs.io.dc_board_candidate import (
    assert_dc_board_candidate_can_promote,
    dc_board_candidate_path,
)
from orchestrator.defs.paths import (
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
)
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
from orchestrator.defs.run_contracts.configs import (
    DcBoardSourceFreezeConfig,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_SOURCE_OBSERVATION_MAX_REQUESTS,
    DC_DAILY_FIELDS,
    DC_INDEX_FIELDS,
    DC_INDEX_PLACEHOLDER_SQL,
    DC_INDEX_TYPES,
    DC_MEMBER_FIELDS,
    DC_MEMBER_PAGE_LIMIT,
)
from orchestrator.defs.tushare_request_policy import (
    BoundedCodePageRequestSession,
    BoundedCodeRequestResult,
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
    prod_completion_fingerprint: str | None = None
    prod_completion_observed_at: str | None = None
    tushare_source_fingerprint: str | None = None
    tushare_source_observed_at: str | None = None
    source_closure_diagnostics: Mapping[str, object] = dataclass_field(
        default_factory=dict
    )

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
            "prod_completion_fingerprint": self.prod_completion_fingerprint,
            "prod_completion_observed_at": self.prod_completion_observed_at,
            "tushare_source_fingerprint": self.tushare_source_fingerprint,
            "tushare_source_observed_at": self.tushare_source_observed_at,
        }
        metadata.update(self.source_closure_diagnostics)
        return metadata


@dataclass(frozen=True, slots=True)
class _DcMemberPairDiff:
    missing_pair_count: int
    extra_pair_count: int
    affected_codes: tuple[str, ...]
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


def _normalize_row(
    row: Mapping[str, object], fields: Sequence[str]
) -> dict[str, object]:
    normalized = {}
    for field in fields:
        value = row.get(field)
        if (
            isinstance(value, Real)
            and not isinstance(value, bool)
            and math.isnan(value)
        ):
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


def _validation_counts(
    connection, dataset: str, raw_trade_date: str
) -> tuple[int, int, int, int]:
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
        name_sql = (
            "SELECT count(*) FROM dc_board_rows WHERE name IS NULL OR trim(name) = ''"
        )
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
        name_sql = (
            "SELECT count(*) FROM dc_board_rows WHERE name IS NULL OR trim(name) = ''"
        )
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
    lake_root_path: Path,
    source_method: str,
    request_count: int,
    page_count: int,
    retry_count: int,
    started_at: float,
    promotion_guard: Callable[[], Mapping[str, int] | None] | None = None,
    failed_codes: Sequence[str] = (),
    empty_codes: Sequence[str] = (),
    chunk_count: int = 0,
    prod_completion_fingerprint: str | None = None,
    prod_completion_observed_at: str | None = None,
    tushare_source_fingerprint: str | None = None,
    tushare_source_observed_at: str | None = None,
    source_closure_diagnostics: Mapping[str, object] | None = None,
) -> DcBoardRawWriteResult:
    fields = tuple(_RAW_TYPES[dataset])
    raw_trade_date = _iso_to_raw_trade_date(partition_key)
    source_row_count = int(
        connection.execute("SELECT count(*) FROM dc_board_rows").fetchone()[0]
    )
    if source_row_count == 0:
        raise DcBoardRawValidationError(
            f"{dataset} returned no rows for open trade date {partition_key}."
        )

    duplicate_count, invalid_count, out_of_partition_count, blank_name_count = (
        _validation_counts(connection, dataset, raw_trade_date)
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
    staging_path = dc_board_candidate_path(lake_root=lake_root_path, target=target_path)
    try:
        select_sql = (
            "SELECT "
            + ", ".join(
                f"CAST({_quoted_identifier(field)} AS {_RAW_TYPES[dataset][field]}) "
                f"AS {_quoted_identifier(field)}"
                for field in fields
            )
            + " FROM dc_board_rows"
        )
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
            connection.execute(
                count_parquet_query(staging_path, hive_partitioning=False)
            ).fetchone()[0]
        )
        if observed_count != source_row_count:
            raise DcBoardRawValidationError(
                f"staging row reconciliation failed: source={source_row_count}, "
                f"written={observed_count}."
            )
        if promotion_guard is not None:
            counts = promotion_guard() or {}
            request_count += int(counts.get("request_count", 0))
            page_count += int(counts.get("page_count", 0))
            retry_count += int(counts.get("retry_count", 0))
        assert_dc_board_candidate_can_promote(staging_path, target_path)
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
        prod_completion_fingerprint=prod_completion_fingerprint,
        prod_completion_observed_at=prod_completion_observed_at,
        tushare_source_fingerprint=tushare_source_fingerprint,
        tushare_source_observed_at=tushare_source_observed_at,
        source_closure_diagnostics=source_closure_diagnostics or {},
    )


def _tushare_extract_rows(
    result: TushareResult, fields: Sequence[str]
) -> Sequence[Mapping[str, object]]:
    _validate_response_columns(result, fields)
    return _normalize_rows(result.rows, fields)


def _validate_dc_daily_covers_same_day_index(
    connection, *, index_path: Path, lake_root: Path,
    partition_key: str, duckdb_resource: DuckDBResource, expected_coverage_digest: str,
) -> None:
    if not index_path.is_file():
        raise DcBoardRawValidationError(f"same-day raw index missing: {index_path}")
    gaps = tuple(row[0] for row in connection.execute(
        f"SELECT DISTINCT ts_code FROM {read_parquet(index_path, hive_partitioning=False)} "
        f"WHERE NOT ({DC_INDEX_PLACEHOLDER_SQL}) EXCEPT SELECT DISTINCT ts_code FROM dc_board_rows"
    ).fetchall())
    coverage = batch_board_quote_coverage(lake_root=lake_root, duckdb_resource=duckdb_resource,
                                         gaps_by_date={partition_key: gaps})[partition_key]
    if not coverage.ready or coverage.evidence_digest != expected_coverage_digest:
        raise DcBoardRawValidationError(f"same-day quote coverage blocked or changed after freeze: {coverage.metadata()}")


def _load_prod_dc_member_pairs_for_diagnostics(
    connection,
    *,
    prod_pairs: Sequence[tuple[str, str]],
) -> None:
    """Load prod member pairs for scoped difference diagnostics only."""

    connection.execute("DROP TABLE IF EXISTS prod_dc_member_pairs")
    connection.execute(
        "CREATE TEMP TABLE prod_dc_member_pairs (ts_code VARCHAR, con_code VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO prod_dc_member_pairs (ts_code, con_code) VALUES (?, ?)",
        prod_pairs,
    )


def _inspect_dc_member_prod_diff(connection) -> _DcMemberPairDiff:
    """Return source/prod differences without treating prod as write authority."""

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
    affected_codes = tuple(
        str(row[0])
        for row in connection.execute(
            """
            SELECT DISTINCT ts_code
            FROM (
                SELECT ts_code FROM dc_member_missing_pairs
                UNION
                SELECT ts_code FROM dc_member_extra_pairs
            )
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
        affected_codes=affected_codes,
        missing_pair_samples=missing_pair_samples,
        extra_pair_samples=extra_pair_samples,
    )


def _assert_dc_member_rows_valid_for_diagnostics(
    connection,
    *,
    partition_key: str,
) -> None:
    """Reject structural member defects before deciding whether a retry is safe."""

    duplicate_count, invalid_count, out_of_partition_count, blank_name_count = (
        _validation_counts(
            connection,
            "dc_member",
            _iso_to_raw_trade_date(partition_key),
        )
    )
    if duplicate_count or invalid_count or blank_name_count or out_of_partition_count:
        raise DcBoardRawValidationError(
            f"dc_member validation failed for {partition_key}: "
            f"duplicate_key_count={duplicate_count}, "
            f"invalid_code_count={invalid_count}, "
            f"blank_name_count={blank_name_count}, "
            f"out_of_partition_count={out_of_partition_count}."
        )


def _replace_dc_member_rows_for_affected_codes(
    connection,
    *,
    affected_codes: Sequence[str],
    replacement_rows: Sequence[Mapping[str, object]],
) -> None:
    """Replace full member rows for source-stability codes in the temporary table."""

    connection.execute("DROP TABLE IF EXISTS dc_member_source_stability_codes")
    connection.execute(
        "CREATE TEMP TABLE dc_member_source_stability_codes (ts_code VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO dc_member_source_stability_codes (ts_code) VALUES (?)",
        [(code,) for code in affected_codes],
    )
    connection.execute(
        """
        DELETE FROM dc_board_rows
        WHERE ts_code IN (SELECT ts_code FROM dc_member_source_stability_codes)
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
        raise DcBoardRawValidationError(f"dc_member {phase} request failed: {details}")
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
        row for code in result.successful_codes for row in result.rows_by_code[code]
    ]


def _dc_member_rows_fingerprint(
    rows: Sequence[Mapping[str, object]],
) -> str:
    normalized_rows = [
        tuple(str(row.get(field) or "").strip() for field in DC_MEMBER_FIELDS)
        for row in rows
    ]
    normalized_rows.sort()
    return hashlib.sha256(
        json.dumps(
            normalized_rows,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _assert_dc_member_source_rows_stable(
    *,
    affected_codes: Sequence[str],
    initial_result: BoundedCodeRequestResult[TushareResult],
    confirmation_result: BoundedCodeRequestResult[TushareResult],
) -> None:
    """Require complete per-board Tushare rows to be identical across two reads."""

    unstable_codes = tuple(
        code
        for code in affected_codes
        if _dc_member_rows_fingerprint(initial_result.rows_by_code.get(code, ()))
        != _dc_member_rows_fingerprint(confirmation_result.rows_by_code.get(code, ()))
    )
    if unstable_codes:
        raise DcBoardRawValidationError(
            "dc_member Tushare rows changed during source stability confirmation: "
            f"unstable_code_count={len(unstable_codes)}, "
            f"unstable_code_samples={list(unstable_codes[:20])}."
        )


def write_dc_index_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    partition_key: str,
    source_snapshot_config: DcBoardSourceFreezeConfig,
    policy=DC_REQUEST_POLICY,
) -> DcBoardRawWriteResult:
    """Fetch and atomically write one ``dc_index`` trade-date partition."""

    started_at = perf_counter()
    observation = revalidate_dc_board_source(
        proof=source_snapshot_config, asset_name="raw_tushare_dc_index", partition_key=partition_key,
        lake_root=lake_root_path, duckdb_resource=duckdb_resource,
        tushare=tushare, prod_postgres=prod_postgres, policy=policy,
    )
    validated_config = source_snapshot_config
    fresh_completion = observation.prod.snapshot
    source_result = observation.source
    with duckdb_resource.connect() as connection:
        _create_table(connection, "dc_index")
        for idx_type in DC_INDEX_TYPES:
            page_rows = source_result.index_rows_by_type.get(idx_type, ())
            _insert_rows(connection, fields=DC_INDEX_FIELDS, rows=page_rows)

        if not any(source_result.index_rows_by_type.values()):
            raise DcBoardRawValidationError(
                f"dc_index returned no rows across all idx_type values for {partition_key}."
            )
        return _promote_table(
            connection,
            lake_root_path=lake_root_path,
            dataset="dc_index",
            partition_key=partition_key,
            target_path=raw_dc_index_path(lake_root_path, partition_key),
            source_method="tushare_api",
            request_count=source_result.request_count,
            page_count=source_result.page_count,
            retry_count=source_result.retry_count,
            started_at=started_at,
            prod_completion_fingerprint=fresh_completion.completion_fingerprint,
            prod_completion_observed_at=validated_config.prod_observed_at_second,
            tushare_source_fingerprint=source_result.snapshot.source_fingerprint,
            tushare_source_observed_at=validated_config.source_observed_at_second,
            source_closure_diagnostics={
                "prod_index_missing_identity_count": source_result.index_missing_count,
                "prod_index_extra_identity_count": source_result.index_extra_count,
                "prod_daily_missing_identity_count": source_result.daily_missing_count,
                "prod_daily_extra_identity_count": source_result.daily_extra_count,
                "dc_index_placeholder_row_count": source_result.placeholder_row_count,
            },
        )


def write_dc_daily_partition(
    *, lake_root_path: Path, duckdb_resource: DuckDBResource,
    tushare: TushareResource, prod_postgres: ProdPostgresResource,
    partition_key: str, source_snapshot_config: DcBoardSourceFreezeConfig,
    policy=DC_REQUEST_POLICY,
) -> DcBoardRawWriteResult:
    """Write the freshly validated complete source snapshot without refetching daily."""
    started_at = perf_counter()
    observation = revalidate_dc_board_source(
        proof=source_snapshot_config, asset_name="raw_tushare_dc_daily", partition_key=partition_key,
        lake_root=lake_root_path, duckdb_resource=duckdb_resource,
        tushare=tushare, prod_postgres=prod_postgres, policy=policy,
    )
    source = observation.source
    with duckdb_resource.connect() as connection:
        _create_table(connection, "dc_daily")
        _insert_rows(connection, fields=DC_DAILY_FIELDS, rows=source.daily_rows)
        _validate_dc_daily_covers_same_day_index(
            connection, index_path=raw_dc_index_path(lake_root_path, partition_key),
            lake_root=lake_root_path, partition_key=partition_key, duckdb_resource=duckdb_resource,
            expected_coverage_digest=source_snapshot_config.history_evidence_digest,
        )
        return _promote_table(
            connection, lake_root_path=lake_root_path, dataset="dc_daily", partition_key=partition_key,
            target_path=raw_dc_daily_path(lake_root_path, partition_key),
            source_method="tushare_api", request_count=source.request_count,
            page_count=source.page_count, retry_count=source.retry_count, started_at=started_at,
            prod_completion_fingerprint=observation.prod.snapshot.completion_fingerprint,
            prod_completion_observed_at=source_snapshot_config.prod_observed_at_second,
            tushare_source_fingerprint=source.snapshot.source_fingerprint,
            tushare_source_observed_at=source_snapshot_config.source_observed_at_second,
            source_closure_diagnostics={
                "prod_daily_missing_identity_count": source.daily_missing_count,
                "prod_daily_extra_identity_count": source.daily_extra_count,
            },
        )


def write_dc_member_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    partition_key: str,
    candidate_codes: Sequence[str],
    source_snapshot_config: DcBoardSourceFreezeConfig,
    policy=DC_REQUEST_POLICY,
) -> DcBoardRawWriteResult:
    """Fetch one member request per candidate board code and atomically write it."""

    normalized_codes = tuple(str(code).strip().upper() for code in candidate_codes)
    if not normalized_codes:
        raise DcBoardRawValidationError("dc_member candidate_codes must not be empty.")
    invalid_candidates = tuple(
        code for code in normalized_codes if not _BOARD_CODE_RE.fullmatch(code)
    )
    if invalid_candidates:
        raise DcBoardRawValidationError(
            "dc_member candidate_codes contain invalid board codes: "
            f"{invalid_candidates[:20]}"
        )
    started_at = perf_counter()
    observation = revalidate_dc_board_source(
        proof=source_snapshot_config, asset_name="raw_tushare_dc_member", partition_key=partition_key,
        lake_root=lake_root_path, duckdb_resource=duckdb_resource,
        tushare=tushare, prod_postgres=prod_postgres, policy=policy,
    )
    fresh_completion = observation.prod.snapshot
    remaining_requests = policy.max_requests - observation.source.request_count - DC_BOARD_SOURCE_OBSERVATION_MAX_REQUESTS
    remaining_seconds = policy.max_elapsed_seconds - (perf_counter() - started_at)
    if remaining_requests < len(normalized_codes) or remaining_seconds <= 0:
        raise DcBoardRawValidationError("member request budget cannot cover candidates and final source validation")
    member_policy = replace(policy, max_requests=remaining_requests, max_elapsed_seconds=remaining_seconds)
    with duckdb_resource.connect() as connection:
        _create_table(connection, "dc_member")
        request_session = BoundedCodePageRequestSession(policy=member_policy)
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
            extract_rows=lambda response: _tushare_extract_rows(
                response, DC_MEMBER_FIELDS
            ),
            page_size=DC_MEMBER_PAGE_LIMIT,
            row_key=lambda row: (
                row.get("trade_date"),
                row.get("ts_code"),
                row.get("con_code"),
            ),
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
        _assert_dc_member_rows_valid_for_diagnostics(
            connection,
            partition_key=partition_key,
        )
        try:
            candidate_code_set = set(normalized_codes)
            prod_pairs = tuple(
                pair
                for pair in load_prod_dc_member_pairs(
                    prod_postgres=prod_postgres,
                    trade_date=partition_key,
                )
                if pair[0] in candidate_code_set
            )
        except DcBoardSourceValidationError as exc:
            raise DcBoardRawValidationError(str(exc)) from exc
        _load_prod_dc_member_pairs_for_diagnostics(connection, prod_pairs=prod_pairs)
        initial_pair_diff = _inspect_dc_member_prod_diff(connection)
        confirmation_result: BoundedCodeRequestResult[TushareResult] | None = None
        final_pair_diff = initial_pair_diff
        stable_source_fingerprint = _dc_member_rows_fingerprint(initial_rows)
        if initial_pair_diff.affected_codes:
            confirmation_result = request_session.execute(
                codes=initial_pair_diff.affected_codes,
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
            confirmation_rows = _dc_member_rows_from_request_result(
                confirmation_result,
                phase="source_stability_confirmation",
            )
            _assert_dc_member_source_rows_stable(
                affected_codes=initial_pair_diff.affected_codes,
                initial_result=initial_result,
                confirmation_result=confirmation_result,
            )
            _replace_dc_member_rows_for_affected_codes(
                connection,
                affected_codes=initial_pair_diff.affected_codes,
                replacement_rows=confirmation_rows,
            )
            _assert_dc_member_rows_valid_for_diagnostics(
                connection,
                partition_key=partition_key,
            )
            final_pair_diff = _inspect_dc_member_prod_diff(connection)

        confirmation_page_count = (
            sum(confirmation_result.page_counts.values())
            if confirmation_result is not None
            else 0
        )
        confirmation_request_count = (
            confirmation_result.request_count if confirmation_result is not None else 0
        )
        confirmation_retry_count = (
            confirmation_result.retry_count if confirmation_result is not None else 0
        )
        def final_source_guard():
            remaining_seconds = policy.max_elapsed_seconds - (perf_counter() - started_at)
            if remaining_seconds <= 0:
                raise DcBoardRawValidationError("member elapsed budget exceeded before final source validation")
            terminal = revalidate_dc_board_source(
                proof=source_snapshot_config, asset_name="raw_tushare_dc_member", partition_key=partition_key,
                lake_root=lake_root_path, duckdb_resource=duckdb_resource,
                tushare=tushare, prod_postgres=prod_postgres,
                policy=replace(policy, max_requests=DC_BOARD_SOURCE_OBSERVATION_MAX_REQUESTS,
                               max_elapsed_seconds=remaining_seconds),
            )
            if perf_counter() - started_at >= policy.max_elapsed_seconds:
                raise DcBoardRawValidationError("member elapsed budget exceeded; promotion blocked")
            return {"request_count": terminal.source.request_count,
                    "page_count": terminal.source.page_count, "retry_count": terminal.source.retry_count}
        return _promote_table(
            connection,
            lake_root_path=lake_root_path,
            dataset="dc_member",
            partition_key=partition_key,
            target_path=raw_dc_member_path(lake_root_path, partition_key),
            source_method="tushare_api_by_ts_code",
            request_count=request_session.request_count + observation.source.request_count,
            page_count=observation.source.page_count + sum(initial_result.page_counts.values())
            + confirmation_page_count,
            retry_count=request_session.retry_count + observation.source.retry_count,
            started_at=started_at,
            promotion_guard=final_source_guard,
            empty_codes=initial_result.empty_codes,
            prod_completion_fingerprint=fresh_completion.completion_fingerprint,
            tushare_source_fingerprint=stable_source_fingerprint,
            source_closure_diagnostics={
                "member_prod_missing_pair_count": initial_pair_diff.missing_pair_count,
                "member_prod_extra_pair_count": initial_pair_diff.extra_pair_count,
                "member_source_stability_code_count": len(
                    initial_pair_diff.affected_codes
                ),
                "member_source_stability_request_count": confirmation_request_count,
                "member_source_stability_page_count": confirmation_page_count,
                "member_source_stability_retry_count": confirmation_retry_count,
                "member_final_prod_missing_pair_count": final_pair_diff.missing_pair_count,
                "member_final_prod_extra_pair_count": final_pair_diff.extra_pair_count,
            },
        )


def write_dc_member_rows_streaming(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    chunks: Iterable[Sequence[Mapping[str, object]]],
    source_method: str = "prod_db_readonly_export",
    pre_promote: Callable[[], object],
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
            lake_root_path=lake_root_path,
            dataset="dc_member",
            partition_key=partition_key,
            target_path=raw_dc_member_path(lake_root_path, partition_key),
            source_method=source_method,
            request_count=0,
            page_count=observed_chunks,
            retry_count=0,
            started_at=started_at,
            promotion_guard=pre_promote,
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
