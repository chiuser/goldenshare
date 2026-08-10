"""Streaming Raw writer and relation audit for Tushare ``idx_factor_pro``."""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    raw_idx_factor_pro_staging_path,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource, TushareResult
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_PAGE_LIMIT,
    IDX_FACTOR_PRO_RAW_COLUMN_TYPES,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
    build_idx_factor_pro_daily_request,
    normalize_idx_factor_pro_trade_date,
)
from orchestrator.defs.tushare_request_policy import (
    TushareRequestPolicy,
    execute_bounded_pages,
)


class IdxFactorProRawValidationError(ValueError):
    """Raised when source, staging, or an existing Raw target is invalid."""


@dataclass(frozen=True, slots=True)
class IdxFactorProRawAudit:
    columns: tuple[str, ...]
    column_types: tuple[str, ...]
    row_count: int
    distinct_code_count: int
    missing_codes: tuple[str, ...]
    extra_codes: tuple[str, ...]
    duplicate_key_count: int
    invalid_key_count: int
    invalid_date_count: int
    min_trade_date: str | None
    max_trade_date: str | None
    null_ratios: tuple[tuple[str, float], ...]

    @property
    def expected_column_types(self) -> tuple[str, ...]:
        return tuple(
            IDX_FACTOR_PRO_RAW_COLUMN_TYPES[column]
            for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
        )

    @property
    def schema_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.columns != IDX_FACTOR_PRO_SOURCE_COLUMNS:
            errors.append("schema_columns")
        if self.column_types != self.expected_column_types:
            errors.append("schema_types")
        return tuple(errors)

    @property
    def scope_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.invalid_date_count:
            errors.append("partition_date")
        if self.missing_codes:
            errors.append("missing_codes")
        if self.extra_codes:
            errors.append("extra_codes")
        return tuple(errors)

    @property
    def key_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.invalid_key_count:
            errors.append("invalid_keys")
        if self.duplicate_key_count:
            errors.append("duplicate_key")
        return tuple(errors)

    @property
    def parity_errors(self) -> tuple[str, ...]:
        expected_count = len(self.missing_codes) + self.distinct_code_count
        return (
            ("row_count",)
            if self.row_count != expected_count or self.distinct_code_count != expected_count
            else ()
        )

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                self.schema_errors
                + self.scope_errors
                + self.key_errors
                + self.parity_errors
            )
        )


@dataclass(frozen=True, slots=True)
class IdxFactorProRawWriteResult:
    partition_key: str
    target_path: Path
    staging_path: Path
    write_mode: str
    expected_code_count: int
    source_row_count: int
    selected_row_count: int
    written_row_count: int
    request_count: int
    page_count: int
    retry_count: int
    min_trade_date: str | None
    max_trade_date: str | None
    code_count: int
    output_bytes: int
    elapsed_ms: float

    def to_details(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "target_path": str(self.target_path),
            "write_mode": self.write_mode,
            "expected_code_count": self.expected_code_count,
            "source_row_count": self.source_row_count,
            "selected_row_count": self.selected_row_count,
            "written_row_count": self.written_row_count,
            "request_count": self.request_count,
            "page_count": self.page_count,
            "retry_count": self.retry_count,
            "min_trade_date": self.min_trade_date,
            "max_trade_date": self.max_trade_date,
            "code_count": self.code_count,
            "output_bytes": self.output_bytes,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


def _relation_select(relation_sql: str) -> str:
    stripped = relation_sql.lstrip().lower()
    return (
        relation_sql
        if stripped.startswith(("select", "with"))
        else f"SELECT * FROM {relation_sql}"
    )


def _prepare_expected_codes(connection, expected_codes: Sequence[str]) -> None:
    connection.execute("DROP TABLE IF EXISTS idx_factor_pro_expected_codes")
    connection.execute(
        "CREATE TEMP TABLE idx_factor_pro_expected_codes("
        "ts_code VARCHAR PRIMARY KEY)"
    )
    connection.executemany(
        "INSERT INTO idx_factor_pro_expected_codes VALUES (?)",
        [(code,) for code in expected_codes],
    )


def validate_idx_factor_pro_raw_relation(
    connection,
    *,
    relation_sql: str,
    expected_codes: Sequence[str],
    partition_key: str,
) -> IdxFactorProRawAudit:
    """Audit one Raw relation against the exact daily contract."""

    normalized_partition = normalize_idx_factor_pro_trade_date(partition_key)
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
    expected_types = tuple(
        IDX_FACTOR_PRO_RAW_COLUMN_TYPES[column]
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
    )
    if columns != IDX_FACTOR_PRO_SOURCE_COLUMNS or column_types != expected_types:
        return IdxFactorProRawAudit(
            columns=columns,
            column_types=column_types,
            row_count=row_count,
            distinct_code_count=0,
            missing_codes=tuple(expected_codes),
            extra_codes=(),
            duplicate_key_count=0,
            invalid_key_count=row_count,
            invalid_date_count=row_count,
            min_trade_date=None,
            max_trade_date=None,
            null_ratios=(),
        )

    _prepare_expected_codes(connection, expected_codes)
    missing_codes = tuple(
        str(row[0])
        for row in connection.execute(
            f"""
            SELECT ts_code
            FROM idx_factor_pro_expected_codes
            EXCEPT
            SELECT DISTINCT ts_code FROM ({select_sql}) relation_rows
            ORDER BY ts_code
            """
        ).fetchall()
    )
    extra_codes = tuple(
        str(row[0])
        for row in connection.execute(
            f"""
            SELECT DISTINCT ts_code FROM ({select_sql}) relation_rows
            EXCEPT
            SELECT ts_code FROM idx_factor_pro_expected_codes
            ORDER BY ts_code
            """
        ).fetchall()
    )
    counts = connection.execute(
        f"""
        SELECT
          count(DISTINCT ts_code),
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = ''
               OR trade_date IS NULL OR trim(trade_date) = ''
          ),
          count(*) FILTER (WHERE trade_date != ?),
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
    numeric_columns = IDX_FACTOR_PRO_SOURCE_COLUMNS[2:]
    null_counts = connection.execute(
        "SELECT "
        + ", ".join(
            f'count(*) FILTER (WHERE "{column}" IS NULL)'
            for column in numeric_columns
        )
        + f" FROM ({select_sql}) relation_rows"
    ).fetchone()
    null_ratios = tuple(
        sorted(
            (
                (column, (int(count or 0) / row_count) if row_count else 0.0)
                for column, count in zip(numeric_columns, null_counts, strict=True)
            ),
            key=lambda item: (-item[1], item[0]),
        )
    )
    return IdxFactorProRawAudit(
        columns=columns,
        column_types=column_types,
        row_count=row_count,
        distinct_code_count=int(counts[0] or 0),
        missing_codes=missing_codes,
        extra_codes=extra_codes,
        duplicate_key_count=duplicate_key_count,
        invalid_key_count=int(counts[1] or 0),
        invalid_date_count=int(counts[2] or 0),
        min_trade_date=str(counts[3]) if counts[3] is not None else None,
        max_trade_date=str(counts[4]) if counts[4] is not None else None,
        null_ratios=null_ratios,
    )


def _extract_rows(result: TushareResult) -> Sequence[Mapping[str, object]]:
    if not result.rows and not result.columns:
        return ()
    if tuple(result.columns) != IDX_FACTOR_PRO_SOURCE_COLUMNS:
        raise IdxFactorProRawValidationError(
            "schema_drift: idx_factor_pro response columns differ from the "
            "explicit 89-column contract"
        )
    rows = tuple(dict(row) for row in result.rows)
    if any(tuple(row) != IDX_FACTOR_PRO_SOURCE_COLUMNS for row in rows):
        raise IdxFactorProRawValidationError(
            "schema_drift: idx_factor_pro row keys or order differ from the contract"
        )
    return rows


def _create_accumulator_tables(connection, expected_codes: Sequence[str]) -> None:
    _prepare_expected_codes(connection, expected_codes)
    connection.execute(
        "CREATE TEMP TABLE idx_factor_pro_source_keys("
        "ts_code VARCHAR NOT NULL, trade_date VARCHAR NOT NULL, "
        "PRIMARY KEY(ts_code, trade_date))"
    )
    columns_sql = ", ".join(
        f'"{column}" {IDX_FACTOR_PRO_RAW_COLUMN_TYPES[column]}'
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
    )
    connection.execute(
        f"CREATE TEMP TABLE idx_factor_pro_selected_rows ({columns_sql})"
    )


def _typed_page_select() -> str:
    return ", ".join(
        f'CAST("{column}" AS {IDX_FACTOR_PRO_RAW_COLUMN_TYPES[column]}) '
        f'AS "{column}"'
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
    )


def _output_select() -> str:
    columns_sql = ", ".join(f'"{column}"' for column in IDX_FACTOR_PRO_SOURCE_COLUMNS)
    return (
        f"SELECT {columns_sql} FROM idx_factor_pro_selected_rows "
        "ORDER BY ts_code, trade_date"
    )


def _raise_for_request_failure(page_result) -> None:
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
    raise IdxFactorProRawValidationError(
        "bounded idx_factor_pro request failed: "
        f"reason={page_result.blocked_reason!r}, failures={samples!r}"
    )


def write_idx_factor_pro_raw_partition(
    *,
    lake_root_path: Path,
    staging_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    partition_key: str,
    run_id: str,
    request_policy: TushareRequestPolicy,
) -> IdxFactorProRawWriteResult:
    """Write one full-market daily page set through external staging."""

    started_at = perf_counter()
    normalized_partition = normalize_idx_factor_pro_trade_date(partition_key)
    expected_trade_date = normalized_partition.replace("-", "")
    expected_codes = active_idx_factor_pro_daily_codes(normalized_partition)
    if not expected_codes:
        raise IdxFactorProRawValidationError(
            f"active idx_factor_pro code scope is empty for {normalized_partition}"
        )
    target_path = raw_idx_factor_pro_path(lake_root_path, normalized_partition)
    staging_path = raw_idx_factor_pro_staging_path(
        staging_root_path,
        run_id,
        normalized_partition,
    )

    if target_path.exists():
        try:
            with duckdb_resource.connect() as connection:
                existing_audit = validate_idx_factor_pro_raw_relation(
                    connection,
                    relation_sql=read_parquet(target_path, hive_partitioning=False),
                    expected_codes=expected_codes,
                    partition_key=normalized_partition,
                )
        except Exception as error:
            raise IdxFactorProRawValidationError(
                "existing Raw target is unreadable and cannot be overwritten: "
                f"path={target_path}, error_type={type(error).__name__}"
            ) from error
        if existing_audit.errors:
            raise IdxFactorProRawValidationError(
                "existing Raw target is invalid and cannot be overwritten: "
                f"errors={existing_audit.errors!r}, path={target_path}"
            )
        raise IdxFactorProRawValidationError(
            f"healthy Raw target already exists; daily writer refuses overwrite: {target_path}"
        )
    if staging_path.exists():
        raise IdxFactorProRawValidationError(
            f"run-scoped Raw staging file already exists: {staging_path}"
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.parent.stat().st_dev != staging_path.parent.stat().st_dev:
        raise IdxFactorProRawValidationError(
            "Raw staging and target must share one filesystem for atomic os.replace"
        )

    source_row_count = 0
    try:
        with duckdb_resource.connect() as connection:
            _create_accumulator_tables(connection, expected_codes)

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
                    raise IdxFactorProRawValidationError(
                        "pandas is required for page-bounded idx_factor_pro ingestion"
                    ) from error
                frame = pd.DataFrame.from_records(
                    rows,
                    columns=IDX_FACTOR_PRO_SOURCE_COLUMNS,
                )
                relation_name = "idx_factor_pro_page_frame"
                typed_table = "idx_factor_pro_page_typed"
                connection.register(relation_name, frame)
                try:
                    connection.execute(f"DROP TABLE IF EXISTS {typed_table}")
                    connection.execute(
                        f"CREATE TEMP TABLE {typed_table} AS "
                        f"SELECT {_typed_page_select()} FROM {relation_name}"
                    )
                    invalid_key_or_date_count = int(
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
                    if invalid_key_or_date_count:
                        raise IdxFactorProRawValidationError(
                            "source page contains invalid keys or an out-of-partition date: "
                            f"offset={offset}, invalid_count={invalid_key_or_date_count}"
                        )
                    connection.execute(
                        f"INSERT INTO idx_factor_pro_source_keys "
                        f"SELECT ts_code, trade_date FROM {typed_table}"
                    )
                    columns_sql = ", ".join(
                        f'page."{column}"' for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
                    )
                    connection.execute(
                        "INSERT INTO idx_factor_pro_selected_rows "
                        f"SELECT {columns_sql} FROM {typed_table} page "
                        "JOIN idx_factor_pro_expected_codes expected USING (ts_code)"
                    )
                    source_row_count += len(rows)
                finally:
                    connection.execute(f"DROP TABLE IF EXISTS {typed_table}")
                    connection.unregister(relation_name)

            def request_page(offset: int) -> TushareResult:
                request = build_idx_factor_pro_daily_request(
                    normalized_partition,
                    offset,
                )
                return tushare.call(request.api_name, request.params, request.fields)

            page_result = execute_bounded_pages(
                request_page=request_page,
                extract_rows=_extract_rows,
                page_size=IDX_FACTOR_PRO_PAGE_LIMIT,
                policy=request_policy,
                scope=f"idx_factor_pro:{normalized_partition}",
                row_key=lambda row: (row.get("ts_code"), row.get("trade_date")),
                consume_page=consume_page,
                retain_rows=False,
            )
            _raise_for_request_failure(page_result)
            if source_row_count <= 0:
                raise IdxFactorProRawValidationError(
                    "idx_factor_pro source returned no rows for the daily partition"
                )

            selected_audit = validate_idx_factor_pro_raw_relation(
                connection,
                relation_sql="idx_factor_pro_selected_rows",
                expected_codes=expected_codes,
                partition_key=normalized_partition,
            )
            if selected_audit.errors:
                raise IdxFactorProRawValidationError(
                    "selected Raw rows failed contract validation: "
                    f"errors={selected_audit.errors!r}, "
                    f"missing_count={len(selected_audit.missing_codes)}, "
                    f"extra_count={len(selected_audit.extra_codes)}"
                )

            connection.execute(copy_query_to_parquet(_output_select(), staging_path))
            staging_audit = validate_idx_factor_pro_raw_relation(
                connection,
                relation_sql=read_parquet(staging_path, hive_partitioning=False),
                expected_codes=expected_codes,
                partition_key=normalized_partition,
            )
            if staging_audit.errors:
                raise IdxFactorProRawValidationError(
                    "Raw staging readback failed contract validation: "
                    f"errors={staging_audit.errors!r}"
                )
            if selected_audit.row_count != staging_audit.row_count:
                raise IdxFactorProRawValidationError(
                    "Raw selected/written row reconciliation failed: "
                    f"selected={selected_audit.row_count}, "
                    f"written={staging_audit.row_count}"
                )
        if target_path.exists():
            raise IdxFactorProRawValidationError(
                f"Raw target appeared during staging; refusing overwrite: {target_path}"
            )
        os.replace(staging_path, target_path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    return IdxFactorProRawWriteResult(
        partition_key=normalized_partition,
        target_path=target_path,
        staging_path=staging_path,
        write_mode="staged_atomic_replace",
        expected_code_count=len(expected_codes),
        source_row_count=source_row_count,
        selected_row_count=selected_audit.row_count,
        written_row_count=staging_audit.row_count,
        request_count=page_result.request_count,
        page_count=page_result.page_count,
        retry_count=page_result.retry_count,
        min_trade_date=staging_audit.min_trade_date,
        max_trade_date=staging_audit.max_trade_date,
        code_count=staging_audit.distinct_code_count,
        output_bytes=target_path.stat().st_size,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


__all__ = [
    "IdxFactorProRawAudit",
    "IdxFactorProRawValidationError",
    "IdxFactorProRawWriteResult",
    "validate_idx_factor_pro_raw_relation",
    "write_idx_factor_pro_raw_partition",
]
