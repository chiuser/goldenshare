"""Set-based Raw writer for the index minute data set.

This module intentionally contains no Dagster asset decorator.  P2 proves the
source, staging, validation, and promotion contract before P4 adds active
definitions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    read_parquet,
)
from orchestrator.defs.paths import raw_index_mins_path
from orchestrator.defs.prod_db.index_mins import (
    PROD_INDEX_MINS_DUCKDB_ATTACHED_DATABASE,
    PROD_INDEX_MINS_DUCKDB_ATTACH_OPTIONS,
    IndexMinsActivePool,
    build_prod_index_mins_duckdb_source_sql,
    validate_prod_index_mins_query_contract,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_INDEX_MINS_SCHEMA
from orchestrator.defs.run_contracts.index_mins import (
    index_mins_code_set_hash,
    index_mins_trade_date_window,
    normalize_index_mins_codes,
    normalize_index_mins_source_freq,
)


INDEX_MINS_RAW_COLUMNS = tuple(column.name for column in RAW_INDEX_MINS_SCHEMA)
INDEX_MINS_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_INDEX_MINS_SCHEMA
}


class IndexMinsRawValidationError(RuntimeError):
    """Raised when source or target facts cannot pass the Raw contract."""


@dataclass(frozen=True, slots=True)
class IndexMinsRawWriteResult:
    raw_file_path: Path
    partition_key: str
    source_freq: str
    source_row_count: int
    written_row_count: int
    expected_code_count: int
    returned_code_count: int
    missing_code_count: int
    extra_code_count: int
    duplicate_key_count: int
    out_of_scope_row_count: int
    query_count: int
    elapsed_ms: float
    active_pool_hash: str
    write_mode: str
    source_method: str = "prod_db_raw_index_mins"

    def to_metadata(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "source_freq": self.source_freq,
            "source_method": self.source_method,
            "write_mode": self.write_mode,
            "raw_file_path": str(self.raw_file_path),
            "source_row_count": self.source_row_count,
            "written_row_count": self.written_row_count,
            "expected_code_count": self.expected_code_count,
            "returned_code_count": self.returned_code_count,
            "missing_code_count": self.missing_code_count,
            "extra_code_count": self.extra_code_count,
            "duplicate_key_count": self.duplicate_key_count,
            "out_of_scope_row_count": self.out_of_scope_row_count,
            "query_count": self.query_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "active_pool_hash": self.active_pool_hash,
            "validation": "source_and_staging_readback_passed",
        }


@dataclass(frozen=True, slots=True)
class _RelationValidation:
    columns: tuple[str, ...]
    row_count: int
    returned_code_count: int
    missing_code_count: int
    extra_code_count: int
    duplicate_key_count: int
    out_of_scope_row_count: int
    schema_errors: tuple[str, ...]
    missing_code_samples: tuple[str, ...]
    extra_code_samples: tuple[str, ...]

    @property
    def errors(self) -> tuple[str, ...]:
        errors = list(self.schema_errors)
        if self.row_count == 0:
            errors.append("empty_source")
        if self.missing_code_count:
            errors.append("missing_active_codes")
        if self.extra_code_count:
            errors.append("extra_codes")
        if self.duplicate_key_count:
            errors.append("duplicate_primary_key")
        if self.out_of_scope_row_count:
            errors.append("out_of_scope_rows")
        return tuple(errors)


def write_raw_index_mins_partition_from_prod_db(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    source_freq: str,
    partition_key: str,
    active_pool: IndexMinsActivePool | Sequence[object],
) -> IndexMinsRawWriteResult:
    """Write one frequency/date Raw partition from the read-only Prod DB.

    The source query and validation execute in DuckDB against an attached
    read-only Postgres database.  The target is never replaced until both the
    source relation and the re-read staging Parquet pass the same contract.
    """

    del duckdb  # The configured connection is created by the shared helper.
    started_at = perf_counter()
    normalized_freq = normalize_index_mins_source_freq(source_freq)
    start_datetime, end_datetime = index_mins_trade_date_window(partition_key)
    expected_codes, active_pool_hash = _active_pool_values(active_pool)
    target_path = raw_index_mins_path(lake_root, normalized_freq, partition_key)

    if target_path.exists():
        with connect_configured_duckdb() as connection:
            _create_expected_code_table(connection, expected_codes)
            validation = _validate_relation(
                connection,
                relation_sql=read_parquet(target_path, hive_partitioning=False),
                expected_codes=expected_codes,
                source_freq=normalized_freq,
                partition_key=partition_key,
            )
        if validation.errors:
            raise IndexMinsRawValidationError(
                "Existing index_mins Raw partition is invalid and will not be overwritten: "
                f"path={target_path}, errors={list(validation.errors)}, "
                f"missing_codes={list(validation.missing_code_samples)}, "
                f"extra_codes={list(validation.extra_code_samples)}."
            )
        return _build_result(
            target_path=target_path,
            partition_key=partition_key,
            source_freq=normalized_freq,
            validation=validation,
            expected_code_count=len(expected_codes),
            active_pool_hash=active_pool_hash,
            elapsed_ms=_elapsed_ms(started_at),
            write_mode="reuse_existing",
            query_count=0,
        )

    validate_prod_index_mins_query_contract()
    source_sql = build_prod_index_mins_duckdb_source_sql(
        source_freq=normalized_freq,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        effective_codes=expected_codes,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = target_path.with_name(f"{target_path.name}.p2-{uuid4().hex}.tmp")

    try:
        with connect_configured_duckdb() as connection:
            _load_duckdb_postgres_extension(connection)
            _attach_prod_postgres_database(
                connection,
                postgres_connection_string=prod_postgres.duckdb_connection_string(),
            )
            connection.execute(
                "CREATE TEMP TABLE index_mins_source AS " + source_sql
            )
            _create_expected_code_table(connection, expected_codes)
            source_validation = _validate_relation(
                connection,
                relation_sql="index_mins_source",
                expected_codes=expected_codes,
                source_freq=normalized_freq,
                partition_key=partition_key,
            )
            if source_validation.errors:
                raise IndexMinsRawValidationError(
                    "Prod index_mins source failed before staging promote: "
                    f"freq={normalized_freq}, partition={partition_key}, "
                    f"errors={list(source_validation.errors)}, "
                    f"missing_codes={list(source_validation.missing_code_samples)}, "
                    f"extra_codes={list(source_validation.extra_code_samples)}."
                )

            output_sql = _raw_output_sql()
            connection.execute(copy_query_to_parquet(output_sql, staging_path))
            staging_validation = _validate_relation(
                connection,
                relation_sql=read_parquet(staging_path, hive_partitioning=False),
                expected_codes=expected_codes,
                source_freq=normalized_freq,
                partition_key=partition_key,
            )
            if staging_validation.errors:
                raise IndexMinsRawValidationError(
                    "index_mins staging Parquet failed readback validation: "
                    f"freq={normalized_freq}, partition={partition_key}, "
                    f"errors={list(staging_validation.errors)}."
                )
            if staging_validation.row_count != source_validation.row_count:
                raise IndexMinsRawValidationError(
                    "index_mins source/staging row reconciliation failed: "
                    f"source={source_validation.row_count}, "
                    f"staging={staging_validation.row_count}."
                )

        if target_path.exists():
            raise IndexMinsRawValidationError(
                f"index_mins target appeared during write; refusing overwrite: {target_path}."
            )
        os.replace(staging_path, target_path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    return _build_result(
        target_path=target_path,
        partition_key=partition_key,
        source_freq=normalized_freq,
        validation=staging_validation,
        expected_code_count=len(expected_codes),
        active_pool_hash=active_pool_hash,
        elapsed_ms=_elapsed_ms(started_at),
        write_mode="staged_atomic_replace",
        query_count=1,
    )


def validate_existing_index_mins_raw_partition(
    *,
    path: Path,
    source_freq: str,
    partition_key: str,
    active_pool: IndexMinsActivePool | Sequence[object],
) -> _RelationValidation:
    """Validate an existing partition without opening a Prod connection."""

    normalized_freq = normalize_index_mins_source_freq(source_freq)
    expected_codes, _active_pool_hash = _active_pool_values(active_pool)
    with connect_configured_duckdb() as connection:
        _create_expected_code_table(connection, expected_codes)
        return _validate_relation(
            connection,
            relation_sql=read_parquet(path, hive_partitioning=False),
            expected_codes=expected_codes,
            source_freq=normalized_freq,
            partition_key=partition_key,
        )


def _build_result(
    *,
    target_path: Path,
    partition_key: str,
    source_freq: str,
    validation: _RelationValidation,
    expected_code_count: int,
    active_pool_hash: str,
    elapsed_ms: float,
    write_mode: str,
    query_count: int,
) -> IndexMinsRawWriteResult:
    return IndexMinsRawWriteResult(
        raw_file_path=target_path,
        partition_key=partition_key,
        source_freq=source_freq,
        source_row_count=validation.row_count,
        written_row_count=validation.row_count,
        expected_code_count=expected_code_count,
        returned_code_count=validation.returned_code_count,
        missing_code_count=validation.missing_code_count,
        extra_code_count=validation.extra_code_count,
        duplicate_key_count=validation.duplicate_key_count,
        out_of_scope_row_count=validation.out_of_scope_row_count,
        query_count=query_count,
        elapsed_ms=elapsed_ms,
        active_pool_hash=active_pool_hash,
        write_mode=write_mode,
    )


def _active_pool_values(
    active_pool: IndexMinsActivePool | Sequence[object],
) -> tuple[tuple[str, ...], str]:
    if isinstance(active_pool, IndexMinsActivePool):
        codes = normalize_index_mins_codes(active_pool.codes, reject_duplicates=True)
        if active_pool.code_set_hash != index_mins_code_set_hash(codes):
            raise ValueError("index_mins active pool hash does not match its codes.")
        return codes, active_pool.code_set_hash
    codes = normalize_index_mins_codes(active_pool, reject_duplicates=True)
    return codes, index_mins_code_set_hash(codes)


def _create_expected_code_table(connection, expected_codes: Sequence[str]) -> None:
    values_sql = ", ".join(f"({_sql_literal(code)})" for code in expected_codes)
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE expected_index_mins_codes AS "
        f"SELECT ts_code FROM (VALUES {values_sql}) AS codes(ts_code)"
    )


def _validate_relation(
    connection,
    *,
    relation_sql: str,
    expected_codes: Sequence[str],
    source_freq: str,
    partition_key: str,
) -> _RelationValidation:
    description = connection.execute(
        f"DESCRIBE SELECT * FROM {relation_sql}"
    ).fetchall()
    columns = tuple(str(row[0]) for row in description)
    schema_errors = _schema_errors(description)
    row_count = int(
        connection.execute(
            f"SELECT count(*) FROM {relation_sql}"
        ).fetchone()[0]
    )
    returned_code_count = int(
        connection.execute(
            f"SELECT count(DISTINCT CAST(ts_code AS VARCHAR)) FROM {relation_sql}"
        ).fetchone()[0]
        or 0
    )
    missing_count, extra_count, missing_samples, extra_samples = _code_set_diff(
        connection,
        relation_sql=relation_sql,
    )
    duplicate_key_count = int(
        connection.execute(
            f"""
            SELECT COALESCE(sum(key_count - 1), 0)
            FROM (
              SELECT ts_code, freq, trade_time, count(*) AS key_count
              FROM {relation_sql}
              GROUP BY ts_code, freq, trade_time
              HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
        or 0
    )
    out_of_scope_row_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {relation_sql}
            WHERE ts_code IS NULL
               OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR freq IS NULL
               OR CAST(freq AS VARCHAR) <> ?
               OR trade_time IS NULL
               OR CAST(trade_time AS DATE) <> CAST(? AS DATE)
            """,
            [source_freq, partition_key],
        ).fetchone()[0]
        or 0
    )
    return _RelationValidation(
        columns=columns,
        row_count=row_count,
        returned_code_count=returned_code_count,
        missing_code_count=missing_count,
        extra_code_count=extra_count,
        duplicate_key_count=duplicate_key_count,
        out_of_scope_row_count=out_of_scope_row_count,
        schema_errors=schema_errors,
        missing_code_samples=missing_samples,
        extra_code_samples=extra_samples,
    )


def _code_set_diff(
    connection,
    *,
    relation_sql: str,
) -> tuple[int, int, tuple[str, ...], tuple[str, ...]]:
    row = connection.execute(
        f"""
        WITH actual_codes AS (
          SELECT DISTINCT trim(CAST(ts_code AS VARCHAR)) AS ts_code
          FROM {relation_sql}
          WHERE ts_code IS NOT NULL AND trim(CAST(ts_code AS VARCHAR)) <> ''
        ), missing_codes AS (
          SELECT ts_code FROM expected_index_mins_codes
          EXCEPT
          SELECT ts_code FROM actual_codes
        ), extra_codes AS (
          SELECT ts_code FROM actual_codes
          EXCEPT
          SELECT ts_code FROM expected_index_mins_codes
        )
        SELECT
          (SELECT count(*) FROM missing_codes),
          (SELECT count(*) FROM extra_codes),
          (SELECT list(ts_code ORDER BY ts_code) FROM (SELECT ts_code FROM missing_codes ORDER BY ts_code LIMIT 5)),
          (SELECT list(ts_code ORDER BY ts_code) FROM (SELECT ts_code FROM extra_codes ORDER BY ts_code LIMIT 5))
        """
    ).fetchone()
    missing_sample = tuple(str(value) for value in (row[2] or []))
    extra_sample = tuple(str(value) for value in (row[3] or []))
    return int(row[0] or 0), int(row[1] or 0), missing_sample, extra_sample


def _schema_errors(description: Sequence[Sequence[object]]) -> tuple[str, ...]:
    observed = tuple(str(row[0]) for row in description)
    expected = INDEX_MINS_RAW_COLUMNS
    errors: list[str] = []
    if observed != expected:
        errors.append(f"schema_columns_expected={expected},observed={observed}")
    if len(description) == len(expected):
        for row, column in zip(description, expected, strict=True):
            observed_type = str(row[1]).upper().split("(", 1)[0]
            expected_type = INDEX_MINS_RAW_COLUMN_TYPES[column].upper()
            if observed_type != expected_type:
                errors.append(
                    f"schema_type_{column}_expected={expected_type},observed={observed_type}"
                )
    return tuple(errors)


def _raw_output_sql() -> str:
    select_sql = ",\n  ".join(
        f"CAST({column} AS {INDEX_MINS_RAW_COLUMN_TYPES[column]}) AS {column}"
        for column in INDEX_MINS_RAW_COLUMNS
    )
    return f"SELECT {select_sql} FROM index_mins_source ORDER BY ts_code, trade_time"


def _sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _load_duckdb_postgres_extension(connection) -> None:
    try:
        connection.execute("LOAD postgres")
        return
    except Exception:  # noqa: BLE001 - retry for local installations.
        try:
            connection.execute("INSTALL postgres")
            connection.execute("LOAD postgres")
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(
                "DuckDB postgres extension is required for index_mins Raw extraction."
            ) from error


def _attach_prod_postgres_database(
    connection,
    *,
    postgres_connection_string: str,
) -> None:
    escaped = postgres_connection_string.replace("'", "''")
    attach_sql = (
        f"ATTACH '{escaped}' AS {PROD_INDEX_MINS_DUCKDB_ATTACHED_DATABASE} "
        f"({PROD_INDEX_MINS_DUCKDB_ATTACH_OPTIONS})"
    )
    try:
        connection.execute(attach_sql)
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(
            "DuckDB failed to attach the read-only Prod Postgres source for index_mins."
        ) from error


def _elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000
