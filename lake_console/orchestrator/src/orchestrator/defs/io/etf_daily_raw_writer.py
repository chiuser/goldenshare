"""Bounded Raw writers and relation audits for ETF daily source datasets."""

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    raw_fund_adj_path,
    raw_fund_adj_staging_path,
    raw_fund_daily_path,
    raw_fund_daily_staging_path,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource, TushareResult
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT,
    FUND_ADJ_API_NAME,
    FUND_ADJ_PAGE_LIMIT,
    FUND_ADJ_RAW_COLUMN_TYPES,
    FUND_ADJ_REQUEST_POLICY,
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_API_NAME,
    FUND_DAILY_PAGE_LIMIT,
    FUND_DAILY_RAW_COLUMN_TYPES,
    FUND_DAILY_REQUEST_POLICY,
    FUND_DAILY_SOURCE_COLUMNS,
    RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
    RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
    EtfDailySourceRequest,
    build_fund_adj_request,
    build_fund_daily_request,
    normalize_etf_daily_trade_date,
)
from orchestrator.defs.tushare_request_policy import (
    BoundedPageRequestResult,
    TushareRequestPolicy,
    execute_bounded_pages,
)


class EtfDailyRawValidationError(ValueError):
    """Raised when source, candidate, or existing Raw facts are unsafe."""


@dataclass(frozen=True, slots=True)
class EtfDailyRawAudit:
    columns: tuple[str, ...]
    column_types: tuple[str, ...]
    row_count: int
    invalid_key_count: int
    duplicate_key_count: int
    invalid_date_count: int
    min_trade_date: str | None
    max_trade_date: str | None
    content_hash: str | None
    expected_source_row_count: int | None
    failure_samples: tuple[dict[str, object], ...]
    error_codes: tuple[str, ...]

    @property
    def source_contract_errors(self) -> tuple[str, ...]:
        return tuple(
            code
            for code in self.error_codes
            if code in {"schema_columns", "schema_types", "row_count_mismatch"}
        )

    @property
    def partition_scope_errors(self) -> tuple[str, ...]:
        return tuple(
            code
            for code in self.error_codes
            if code in {"empty_partition", "partition_date"}
        )

    @property
    def key_integrity_errors(self) -> tuple[str, ...]:
        return tuple(
            code
            for code in self.error_codes
            if code in {"invalid_key", "duplicate_key"}
        )


@dataclass(frozen=True, slots=True)
class EtfDailyRawWriteResult:
    asset_key: str
    api_name: str
    partition_key: str
    target_path: Path
    staging_path: Path
    write_mode: str
    source_row_count: int
    normalized_row_count: int
    candidate_row_count: int
    written_row_count: int
    page_count: int
    page_offsets: tuple[int, ...]
    request_count: int
    retry_count: int
    elapsed_ms: float
    content_hash: str
    output_bytes: int
    request_params: Mapping[str, object]
    source_fields: tuple[str, ...]

    def to_details(self) -> dict[str, object]:
        return {
            "asset_key": self.asset_key,
            "source_api": self.api_name,
            "partition_key": self.partition_key,
            "target_path": str(self.target_path),
            "staging_path": str(self.staging_path),
            "write_mode": self.write_mode,
            "source_row_count": self.source_row_count,
            "normalized_row_count": self.normalized_row_count,
            "candidate_row_count": self.candidate_row_count,
            "written_row_count": self.written_row_count,
            "page_count": self.page_count,
            "page_offsets": list(self.page_offsets),
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "content_hash": self.content_hash,
            "output_bytes": self.output_bytes,
            "request_params": dict(self.request_params),
            "source_fields": list(self.source_fields),
        }


@dataclass(frozen=True, slots=True)
class EtfDailyRawSpec:
    asset_key: str
    api_name: str
    source_columns: tuple[str, ...]
    raw_column_types: Mapping[str, str]
    page_limit: int
    request_policy: TushareRequestPolicy
    request_builder: Callable[[str, int], EtfDailySourceRequest]
    target_path_builder: Callable[[Path, str], Path]
    staging_path_builder: Callable[[Path, str, str], Path]


FUND_DAILY_RAW_SPEC = EtfDailyRawSpec(
    asset_key=RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
    api_name=FUND_DAILY_API_NAME,
    source_columns=FUND_DAILY_SOURCE_COLUMNS,
    raw_column_types=FUND_DAILY_RAW_COLUMN_TYPES,
    page_limit=FUND_DAILY_PAGE_LIMIT,
    request_policy=FUND_DAILY_REQUEST_POLICY,
    request_builder=build_fund_daily_request,
    target_path_builder=raw_fund_daily_path,
    staging_path_builder=raw_fund_daily_staging_path,
)
FUND_ADJ_RAW_SPEC = EtfDailyRawSpec(
    asset_key=RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
    api_name=FUND_ADJ_API_NAME,
    source_columns=FUND_ADJ_SOURCE_COLUMNS,
    raw_column_types=FUND_ADJ_RAW_COLUMN_TYPES,
    page_limit=FUND_ADJ_PAGE_LIMIT,
    request_policy=FUND_ADJ_REQUEST_POLICY,
    request_builder=build_fund_adj_request,
    target_path_builder=raw_fund_adj_path,
    staging_path_builder=raw_fund_adj_staging_path,
)
_APPROVED_RAW_SPECS = (FUND_DAILY_RAW_SPEC, FUND_ADJ_RAW_SPEC)


def _relation_select(relation_sql: str) -> str:
    stripped = relation_sql.lstrip().lower()
    return (
        relation_sql
        if stripped.startswith(("select", "with"))
        else f"SELECT * FROM {relation_sql}"
    )


def _quoted_columns(spec: EtfDailyRawSpec) -> str:
    return ", ".join(f'"{column}"' for column in spec.source_columns)


def _expected_types(spec: EtfDailyRawSpec) -> tuple[str, ...]:
    return tuple(spec.raw_column_types[column] for column in spec.source_columns)


def etf_daily_raw_content_hash_sql(spec: EtfDailyRawSpec) -> str:
    """One canonical aggregate for single-file and grouped historical audits."""
    struct_fields = ", ".join(
        f'{column} := "{column}"' for column in spec.source_columns
    )
    return f"""sha256(coalesce(string_agg(
        to_json(struct_pack({struct_fields})), '\n' ORDER BY ts_code, trade_date
    ), ''))"""


def _canonical_content_hash(
    connection,
    *,
    select_sql: str,
    spec: EtfDailyRawSpec,
) -> str:
    value = connection.execute(
        f"""
        SELECT {etf_daily_raw_content_hash_sql(spec)}
        FROM ({select_sql}) relation_rows
        """
    ).fetchone()[0]
    return str(value)


def _failure_samples(
    connection,
    *,
    select_sql: str,
    expected_trade_date: str,
) -> tuple[dict[str, object], ...]:
    samples: list[dict[str, object]] = []
    queries = (
        (
            "invalid_key",
            f"""
            SELECT ts_code, trade_date, NULL::BIGINT AS occurrence_count
            FROM ({select_sql}) relation_rows
            WHERE ts_code IS NULL OR trim(ts_code) = ''
               OR trade_date IS NULL OR trim(trade_date) = ''
            ORDER BY ts_code NULLS FIRST, trade_date NULLS FIRST
            """,
            (),
        ),
        (
            "partition_date",
            f"""
            SELECT ts_code, trade_date, NULL::BIGINT AS occurrence_count
            FROM ({select_sql}) relation_rows
            WHERE trade_date IS NOT NULL AND trim(trade_date) != ''
              AND trade_date != ?
            ORDER BY ts_code, trade_date
            """,
            (expected_trade_date,),
        ),
        (
            "duplicate_key",
            f"""
            SELECT ts_code, trade_date, count(*) AS occurrence_count
            FROM ({select_sql}) relation_rows
            GROUP BY ts_code, trade_date
            HAVING count(*) > 1
            ORDER BY ts_code NULLS FIRST, trade_date NULLS FIRST
            """,
            (),
        ),
    )
    for reason_code, query, params in queries:
        remaining = ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT - len(samples)
        if remaining <= 0:
            break
        rows = connection.execute(
            f"SELECT * FROM ({query}) samples LIMIT ?",
            [*params, remaining],
        ).fetchall()
        samples.extend(
            {
                "reason_code": reason_code,
                "ts_code": row[0],
                "trade_date": row[1],
                "occurrence_count": row[2],
            }
            for row in rows
        )
    return tuple(samples)


def audit_etf_daily_raw_relation(
    connection,
    *,
    relation_sql: str,
    spec: EtfDailyRawSpec,
    partition_key: str,
    expected_source_row_count: int | None = None,
) -> EtfDailyRawAudit:
    """Audit one relation without filtering or repairing any source row."""

    if not any(spec is approved for approved in _APPROVED_RAW_SPECS):
        raise ValueError("ETF daily Raw audit requires one frozen dataset spec")
    normalized_partition = normalize_etf_daily_trade_date(partition_key)
    expected_trade_date = normalized_partition.replace("-", "")
    select_sql = _relation_select(relation_sql)
    description = connection.execute(f"DESCRIBE {select_sql}").fetchall()
    columns = tuple(str(row[0]) for row in description)
    column_types = tuple(str(row[1]).upper() for row in description)
    row_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({select_sql}) relation_rows"
        ).fetchone()[0]
        or 0
    )
    errors: list[str] = []
    if columns != spec.source_columns:
        errors.append("schema_columns")
    if column_types != _expected_types(spec):
        errors.append("schema_types")
    if expected_source_row_count is not None and row_count != expected_source_row_count:
        errors.append("row_count_mismatch")
    if row_count == 0:
        errors.append("empty_partition")
    if errors and any(code.startswith("schema_") for code in errors):
        return EtfDailyRawAudit(
            columns=columns,
            column_types=column_types,
            row_count=row_count,
            invalid_key_count=0,
            duplicate_key_count=0,
            invalid_date_count=0,
            min_trade_date=None,
            max_trade_date=None,
            content_hash=None,
            expected_source_row_count=expected_source_row_count,
            failure_samples=(),
            error_codes=tuple(errors),
        )

    counts = connection.execute(
        f"""
        SELECT
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = ''
               OR trade_date IS NULL OR trim(trade_date) = ''
          ),
          count(*) FILTER (
            WHERE trade_date IS NULL OR trim(trade_date) = '' OR trade_date != ?
          ),
          min(trade_date),
          max(trade_date)
        FROM ({select_sql}) relation_rows
        """,
        [expected_trade_date],
    ).fetchone()
    duplicate_key_count = int(
        connection.execute(
            f"""
            SELECT coalesce(sum(key_count - 1), 0)
            FROM (
              SELECT count(*) AS key_count
              FROM ({select_sql}) relation_rows
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
        or 0
    )
    invalid_key_count = int(counts[0] or 0)
    invalid_date_count = int(counts[1] or 0)
    if invalid_key_count:
        errors.append("invalid_key")
    if duplicate_key_count:
        errors.append("duplicate_key")
    if invalid_date_count:
        errors.append("partition_date")
    return EtfDailyRawAudit(
        columns=columns,
        column_types=column_types,
        row_count=row_count,
        invalid_key_count=invalid_key_count,
        duplicate_key_count=duplicate_key_count,
        invalid_date_count=invalid_date_count,
        min_trade_date=str(counts[2]) if counts[2] is not None else None,
        max_trade_date=str(counts[3]) if counts[3] is not None else None,
        content_hash=_canonical_content_hash(
            connection,
            select_sql=select_sql,
            spec=spec,
        ),
        expected_source_row_count=expected_source_row_count,
        failure_samples=_failure_samples(
            connection,
            select_sql=select_sql,
            expected_trade_date=expected_trade_date,
        ),
        error_codes=tuple(dict.fromkeys(errors)),
    )


def _typed_page_select(spec: EtfDailyRawSpec, relation_name: str) -> str:
    return ", ".join(
        f'CAST({relation_name}."{column}" AS {spec.raw_column_types[column]}) '
        f'AS "{column}"'
        for column in spec.source_columns
    )


def _create_accumulator(connection, spec: EtfDailyRawSpec) -> None:
    columns_sql = ", ".join(
        f'"{column}" {spec.raw_column_types[column]}' for column in spec.source_columns
    )
    connection.execute(f"CREATE TEMP TABLE etf_daily_raw_rows ({columns_sql})")


def _extract_rows(
    result: TushareResult,
    *,
    spec: EtfDailyRawSpec,
) -> Sequence[Mapping[str, object]]:
    if not result.rows:
        return ()
    if tuple(result.columns) != spec.source_columns:
        raise EtfDailyRawValidationError(
            f"schema_drift: {spec.api_name} columns differ from the explicit contract"
        )
    rows = tuple(dict(row) for row in result.rows)
    if any(tuple(row) != spec.source_columns for row in rows):
        raise EtfDailyRawValidationError(
            f"schema_drift: {spec.api_name} row fields differ from the contract"
        )
    return rows


def _raise_for_request_failure(
    page_result: BoundedPageRequestResult[TushareResult],
    *,
    spec: EtfDailyRawSpec,
) -> None:
    if page_result.ready:
        return
    samples = tuple(
        {
            "category": failure.category,
            "message": failure.message,
            "retryable": failure.retryable,
        }
        for failure in page_result.failed_pages[:3]
    )
    raise EtfDailyRawValidationError(
        f"bounded {spec.api_name} request failed: "
        f"reason={page_result.blocked_reason!r}, failures={samples!r}"
    )


def _difference_count(
    connection,
    *,
    left_sql: str,
    right_sql: str,
    spec: EtfDailyRawSpec,
) -> int:
    columns_sql = _quoted_columns(spec)
    left_select = _relation_select(left_sql)
    right_select = _relation_select(right_sql)
    return int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT {columns_sql} FROM ({left_select}) left_rows
              EXCEPT ALL
              SELECT {columns_sql} FROM ({right_select}) right_rows
            ) differences
            """
        ).fetchone()[0]
        or 0
    )


def _relations_are_equivalent(
    connection,
    *,
    candidate_sql: str,
    existing_sql: str,
    candidate_audit: EtfDailyRawAudit,
    existing_audit: EtfDailyRawAudit,
    spec: EtfDailyRawSpec,
) -> bool:
    if existing_audit.error_codes:
        return False
    if candidate_audit.row_count != existing_audit.row_count:
        return False
    if candidate_audit.content_hash != existing_audit.content_hash:
        return False
    return not _difference_count(
        connection,
        left_sql=candidate_sql,
        right_sql=existing_sql,
        spec=spec,
    ) and not _difference_count(
        connection,
        left_sql=existing_sql,
        right_sql=candidate_sql,
        spec=spec,
    )


def _require_preflight_roots(lake_root_path: Path, staging_root_path: Path) -> None:
    for label, path in (
        ("Lake", lake_root_path),
        ("staging", staging_root_path),
    ):
        if not path.is_dir():
            raise EtfDailyRawValidationError(
                f"{label} root must already exist as a directory: {path}"
            )
    if lake_root_path.stat().st_dev != staging_root_path.stat().st_dev:
        raise EtfDailyRawValidationError(
            "Raw staging and target must share one filesystem for atomic os.replace"
        )


def _write_etf_daily_raw_partition(
    *,
    spec: EtfDailyRawSpec,
    lake_root_path: Path,
    staging_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    partition_key: str,
    operation_id: str,
) -> EtfDailyRawWriteResult:
    if not any(spec is approved for approved in _APPROVED_RAW_SPECS):
        raise ValueError("ETF daily Raw writer requires one frozen dataset spec")
    started_at = perf_counter()
    normalized_partition = normalize_etf_daily_trade_date(partition_key)
    expected_trade_date = normalized_partition.replace("-", "")
    _require_preflight_roots(lake_root_path, staging_root_path)
    target_path = spec.target_path_builder(lake_root_path, normalized_partition)
    staging_path = spec.staging_path_builder(
        staging_root_path,
        operation_id,
        normalized_partition,
    )
    if staging_path.exists():
        raise EtfDailyRawValidationError(
            f"operation-scoped Raw staging file already exists: {staging_path}"
        )
    target_existed_at_start = target_path.exists()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.parent.mkdir(parents=True, exist_ok=True)

    source_row_count = 0
    page_result: BoundedPageRequestResult[TushareResult] | None = None
    candidate_audit: EtfDailyRawAudit | None = None
    write_mode = ""
    request_zero = spec.request_builder(normalized_partition, 0)
    try:
        with duckdb_resource.connect() as connection:
            _create_accumulator(connection, spec)

            def consume_page(
                offset: int,
                rows: Sequence[Mapping[str, object]],
            ) -> None:
                nonlocal source_row_count
                if not rows:
                    return
                try:
                    import pandas as pd
                except ModuleNotFoundError as error:
                    raise EtfDailyRawValidationError(
                        "pandas is required for page-bounded ETF daily ingestion"
                    ) from error
                frame = pd.DataFrame.from_records(rows, columns=spec.source_columns)
                relation_name = "etf_daily_raw_page_frame"
                typed_table = "etf_daily_raw_page_typed"
                connection.register(relation_name, frame)
                try:
                    connection.execute(f"DROP TABLE IF EXISTS {typed_table}")
                    connection.execute(
                        f"CREATE TEMP TABLE {typed_table} AS SELECT "
                        f"{_typed_page_select(spec, relation_name)} "
                        f"FROM {relation_name}"
                    )
                    invalid_count = int(
                        connection.execute(
                            f"""
                            SELECT count(*) FROM {typed_table}
                            WHERE ts_code IS NULL OR trim(ts_code) = ''
                               OR trade_date IS NULL OR trim(trade_date) = ''
                               OR trade_date != ?
                            """,
                            [expected_trade_date],
                        ).fetchone()[0]
                        or 0
                    )
                    if invalid_count:
                        raise EtfDailyRawValidationError(
                            "source page contains an invalid key or partition date: "
                            f"api={spec.api_name}, offset={offset}, "
                            f"invalid_count={invalid_count}"
                        )
                    connection.execute(
                        f"INSERT INTO etf_daily_raw_rows "
                        f"SELECT {_quoted_columns(spec)} FROM {typed_table}"
                    )
                    source_row_count += len(rows)
                finally:
                    connection.execute(f"DROP TABLE IF EXISTS {typed_table}")
                    connection.unregister(relation_name)

            def request_page(offset: int) -> TushareResult:
                request = spec.request_builder(normalized_partition, offset)
                return tushare.call(request.api_name, request.params, request.fields)

            page_result = execute_bounded_pages(
                request_page=request_page,
                extract_rows=lambda result: _extract_rows(result, spec=spec),
                page_size=spec.page_limit,
                policy=spec.request_policy,
                scope=f"{spec.api_name}:{normalized_partition}",
                row_key=lambda row: (row.get("ts_code"), row.get("trade_date")),
                consume_page=consume_page,
                retain_rows=False,
            )
            _raise_for_request_failure(page_result, spec=spec)
            if source_row_count <= 0:
                raise EtfDailyRawValidationError(
                    f"{spec.api_name} source returned no rows for {normalized_partition}"
                )
            accumulator_audit = audit_etf_daily_raw_relation(
                connection,
                relation_sql="etf_daily_raw_rows",
                spec=spec,
                partition_key=normalized_partition,
                expected_source_row_count=source_row_count,
            )
            if accumulator_audit.error_codes:
                raise EtfDailyRawValidationError(
                    "normalized Raw rows failed contract validation: "
                    f"api={spec.api_name}, errors={accumulator_audit.error_codes!r}"
                )
            output_select = (
                f"SELECT {_quoted_columns(spec)} FROM etf_daily_raw_rows "
                "ORDER BY ts_code, trade_date"
            )
            connection.execute(
                f"COPY ({output_select}) TO {duckdb_string(staging_path)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            candidate_sql = read_parquet(staging_path, hive_partitioning=False)
            candidate_audit = audit_etf_daily_raw_relation(
                connection,
                relation_sql=candidate_sql,
                spec=spec,
                partition_key=normalized_partition,
                expected_source_row_count=source_row_count,
            )
            if candidate_audit.error_codes:
                raise EtfDailyRawValidationError(
                    "Raw candidate read-back failed contract validation: "
                    f"api={spec.api_name}, errors={candidate_audit.error_codes!r}"
                )
            if target_existed_at_start:
                try:
                    existing_sql = read_parquet(target_path, hive_partitioning=False)
                    existing_audit = audit_etf_daily_raw_relation(
                        connection,
                        relation_sql=existing_sql,
                        spec=spec,
                        partition_key=normalized_partition,
                    )
                except Exception as error:
                    raise EtfDailyRawValidationError(
                        "existing Raw target is unreadable and cannot be overwritten: "
                        f"path={target_path}, error_type={type(error).__name__}"
                    ) from error
                if not _relations_are_equivalent(
                    connection,
                    candidate_sql=candidate_sql,
                    existing_sql=existing_sql,
                    candidate_audit=candidate_audit,
                    existing_audit=existing_audit,
                    spec=spec,
                ):
                    raise EtfDailyRawValidationError(
                        "existing Raw target conflicts with the current source; "
                        f"refusing overwrite: {target_path}"
                    )
                staging_path.unlink()
                write_mode = "reuse_existing"
            else:
                if target_path.exists():
                    raise EtfDailyRawValidationError(
                        "Raw target appeared during candidate creation; refusing overwrite: "
                        f"{target_path}"
                    )
                os.replace(staging_path, target_path)
                write_mode = "write_new"
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    if (
        page_result is None
        or candidate_audit is None
        or candidate_audit.content_hash is None
    ):
        raise AssertionError(
            "ETF daily Raw writer completed without frozen audit evidence"
        )
    return EtfDailyRawWriteResult(
        asset_key=spec.asset_key,
        api_name=spec.api_name,
        partition_key=normalized_partition,
        target_path=target_path,
        staging_path=staging_path,
        write_mode=write_mode,
        source_row_count=source_row_count,
        normalized_row_count=source_row_count,
        candidate_row_count=candidate_audit.row_count,
        written_row_count=candidate_audit.row_count,
        page_count=page_result.page_count,
        page_offsets=page_result.page_offsets,
        request_count=page_result.request_count,
        retry_count=page_result.retry_count,
        elapsed_ms=(perf_counter() - started_at) * 1000,
        content_hash=candidate_audit.content_hash,
        output_bytes=target_path.stat().st_size,
        request_params=request_zero.params,
        source_fields=spec.source_columns,
    )


def write_fund_daily_raw_partition(
    *,
    lake_root_path: Path,
    staging_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    partition_key: str,
    operation_id: str,
) -> EtfDailyRawWriteResult:
    return _write_etf_daily_raw_partition(
        spec=FUND_DAILY_RAW_SPEC,
        lake_root_path=lake_root_path,
        staging_root_path=staging_root_path,
        duckdb_resource=duckdb_resource,
        tushare=tushare,
        partition_key=partition_key,
        operation_id=operation_id,
    )


def write_fund_adj_raw_partition(
    *,
    lake_root_path: Path,
    staging_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    partition_key: str,
    operation_id: str,
) -> EtfDailyRawWriteResult:
    return _write_etf_daily_raw_partition(
        spec=FUND_ADJ_RAW_SPEC,
        lake_root_path=lake_root_path,
        staging_root_path=staging_root_path,
        duckdb_resource=duckdb_resource,
        tushare=tushare,
        partition_key=partition_key,
        operation_id=operation_id,
    )


__all__ = [
    "FUND_ADJ_RAW_SPEC",
    "FUND_DAILY_RAW_SPEC",
    "EtfDailyRawAudit",
    "EtfDailyRawSpec",
    "EtfDailyRawValidationError",
    "EtfDailyRawWriteResult",
    "audit_etf_daily_raw_relation",
    "etf_daily_raw_content_hash_sql",
    "write_fund_adj_raw_partition",
    "write_fund_daily_raw_partition",
]
