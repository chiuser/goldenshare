"""Set-based Silver writer for the index minute data set.

P3 deliberately keeps this module outside Dagster definitions.  It proves the
native normalization and the two fixed derived-window contracts before the
Silver assets, checks, jobs, and sensors are introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4
import os

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_MINS_SCHEMA,
    SILVER_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_DERIVED_FREQS,
    index_mins_derived_windows,
    normalize_index_mins_silver_freq,
    source_freq_for_index_mins_derived_freq,
)


INDEX_MINS_SILVER_COLUMNS = tuple(column.name for column in SILVER_INDEX_MINS_SCHEMA)
INDEX_MINS_SILVER_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_INDEX_MINS_SCHEMA
}


class IndexMinsSilverValidationError(RuntimeError):
    """Raised when an index_mins source or staging relation is invalid."""


@dataclass(frozen=True, slots=True)
class IndexMinsSilverWriteResult:
    silver_file_path: Path
    source_file_path: Path
    partition_key: str
    silver_freq: str
    source_freq: str
    source_row_count: int
    written_row_count: int
    expected_window_count: int
    generated_window_count: int
    incomplete_window_count: int
    exchange_mismatch_window_count: int
    duplicate_key_count: int
    invalid_row_count: int
    elapsed_ms: float
    write_mode: str
    source_mode: str = "native"
    source_empty_reason: str | None = None
    lower_source_row_count: int | None = None
    derived_row_count: int | None = None
    source_revision: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "silver_freq": self.silver_freq,
            "source_freq": self.source_freq,
            "source_file_path": str(self.source_file_path),
            "silver_file_path": str(self.silver_file_path),
            "source_row_count": self.source_row_count,
            "written_row_count": self.written_row_count,
            "expected_window_count": self.expected_window_count,
            "generated_window_count": self.generated_window_count,
            "incomplete_window_count": self.incomplete_window_count,
            "exchange_mismatch_window_count": self.exchange_mismatch_window_count,
            "duplicate_key_count": self.duplicate_key_count,
            "invalid_row_count": self.invalid_row_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "write_mode": self.write_mode,
            "source_mode": self.source_mode,
            "source_empty_reason": self.source_empty_reason,
            "lower_source_row_count": self.lower_source_row_count,
            "derived_row_count": self.derived_row_count,
            "source_revision": self.source_revision,
            "validation": "set_based_staging_readback_passed",
        }


@dataclass(frozen=True, slots=True)
class _RelationValidation:
    row_count: int
    duplicate_key_count: int
    invalid_row_count: int
    non_null_vwap_count: int


def write_silver_index_mins_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    freq: int | str,
    partition_key: str,
) -> IndexMinsSilverWriteResult:
    """Write one native or derived Silver frequency atomically."""

    normalized_freq = normalize_index_mins_silver_freq(freq)
    if int(normalized_freq[:-3]) in INDEX_MINS_DERIVED_FREQS:
        return _write_derived_partition(
            lake_root=lake_root,
            duckdb=duckdb,
            silver_freq=normalized_freq,
            partition_key=partition_key,
        )
    return _write_native_partition(
        lake_root=lake_root,
        duckdb=duckdb,
        silver_freq=normalized_freq,
        partition_key=partition_key,
    )


def _write_native_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    silver_freq: str,
    partition_key: str,
) -> IndexMinsSilverWriteResult:
    source_freq = silver_freq
    del duckdb  # Use the repository-wide configured connection helper.
    source_path = raw_index_mins_path(lake_root, source_freq, partition_key)
    target_path = silver_index_mins_path(lake_root, silver_freq, partition_key)
    if not source_path.exists():
        raise FileNotFoundError(f"Missing index_mins Raw file: {source_path}")

    started_at = perf_counter()
    with connect_configured_duckdb() as connection:
        _assert_schema(
            connection,
            source_path,
            RAW_INDEX_MINS_SCHEMA,
            label="index_mins Raw",
        )
        normalized_sql = _native_normalized_sql(source_path)
        source_validation = _validate_relation(
            connection,
            relation_sql=normalized_sql,
            expected_freq=silver_freq,
            partition_key=partition_key,
            require_null_vwap=False,
        )
        _require_source_validation(
            source_validation,
            label="index_mins Raw",
            partition_key=partition_key,
            expected_freq=silver_freq,
        )
        output_sql = _native_output_sql(normalized_sql)
        if target_path.exists():
            target_validation = _validate_existing_target(
                connection,
                target_path=target_path,
                relation_sql=read_parquet(target_path, hive_partitioning=False),
                expected_freq=silver_freq,
                partition_key=partition_key,
                expected_row_count=source_validation.row_count,
                require_null_vwap=False,
            )
            return _result(
                target_path=target_path,
                source_path=source_path,
                partition_key=partition_key,
                silver_freq=silver_freq,
                source_freq=source_freq,
                source_validation=source_validation,
                written_row_count=target_validation.row_count,
                expected_window_count=0,
                generated_window_count=0,
                incomplete_window_count=0,
                exchange_mismatch_window_count=0,
                elapsed_ms=_elapsed_ms(started_at),
                write_mode="reuse_existing",
            )
        return _stage_and_promote(
            connection=connection,
            output_sql=output_sql,
            target_path=target_path,
            source_path=source_path,
            partition_key=partition_key,
            silver_freq=silver_freq,
            source_freq=source_freq,
            source_validation=source_validation,
            expected_row_count=source_validation.row_count,
            expected_window_count=0,
            generated_window_count=0,
            incomplete_window_count=0,
            exchange_mismatch_window_count=0,
            started_at=started_at,
        )


def _write_derived_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    silver_freq: str,
    partition_key: str,
) -> IndexMinsSilverWriteResult:
    source_freq = source_freq_for_index_mins_derived_freq(silver_freq)
    del duckdb  # Use the repository-wide configured connection helper.
    source_path = silver_index_mins_path(lake_root, source_freq, partition_key)
    target_path = silver_index_mins_path(lake_root, silver_freq, partition_key)
    if not source_path.exists():
        raise FileNotFoundError(
            "Missing native Silver source for derived index_mins: "
            f"freq={source_freq}, partition={partition_key}, path={source_path}"
        )

    started_at = perf_counter()
    with connect_configured_duckdb() as connection:
        _assert_schema(
            connection,
            source_path,
            SILVER_INDEX_MINS_SCHEMA,
            label="index_mins native Silver",
        )
        source_relation = read_parquet(source_path, hive_partitioning=False)
        source_sql = _native_source_sql(source_relation)
        source_validation = _validate_relation(
            connection,
            relation_sql=source_sql,
            expected_freq=source_freq,
            partition_key=partition_key,
            require_null_vwap=False,
        )
        _require_source_validation(
            source_validation,
            label="index_mins native Silver",
            partition_key=partition_key,
            expected_freq=source_freq,
        )
        diagnostics = _derived_diagnostics(
            connection,
            source_sql=source_sql,
            silver_freq=silver_freq,
            partition_key=partition_key,
        )
        if diagnostics["source_row_count"] <= 0:
            raise IndexMinsSilverValidationError(
                "index_mins derived source is empty: "
                f"freq={source_freq}, partition={partition_key}."
            )
        if diagnostics["exchange_mismatch_window_count"]:
            raise IndexMinsSilverValidationError(
                "index_mins derived window has mixed exchange values: "
                f"freq={silver_freq}, partition={partition_key}, "
                f"count={diagnostics['exchange_mismatch_window_count']}."
            )
        if diagnostics["incomplete_window_count"]:
            raise IndexMinsSilverValidationError(
                "index_mins derived window is incomplete: "
                f"freq={silver_freq}, partition={partition_key}, "
                f"count={diagnostics['incomplete_window_count']}."
            )
        if diagnostics["generated_window_count"] <= 0:
            raise IndexMinsSilverValidationError(
                "index_mins derived generation produced no complete windows: "
                f"freq={silver_freq}, partition={partition_key}."
            )

        output_sql = _derived_output_sql(
            source_sql=source_sql,
            silver_freq=silver_freq,
            partition_key=partition_key,
        )
        if target_path.exists():
            target_validation = _validate_existing_target(
                connection,
                target_path=target_path,
                relation_sql=read_parquet(target_path, hive_partitioning=False),
                expected_freq=silver_freq,
                partition_key=partition_key,
                expected_row_count=diagnostics["generated_window_count"],
                require_null_vwap=True,
            )
            return _result(
                target_path=target_path,
                source_path=source_path,
                partition_key=partition_key,
                silver_freq=silver_freq,
                source_freq=source_freq,
                source_validation=source_validation,
                written_row_count=target_validation.row_count,
                expected_window_count=diagnostics["expected_window_count"],
                generated_window_count=diagnostics["generated_window_count"],
                incomplete_window_count=diagnostics["incomplete_window_count"],
                exchange_mismatch_window_count=diagnostics[
                    "exchange_mismatch_window_count"
                ],
                elapsed_ms=_elapsed_ms(started_at),
                write_mode="reuse_existing",
            )
        return _stage_and_promote(
            connection=connection,
            output_sql=output_sql,
            target_path=target_path,
            source_path=source_path,
            partition_key=partition_key,
            silver_freq=silver_freq,
            source_freq=source_freq,
            source_validation=source_validation,
            expected_row_count=diagnostics["generated_window_count"],
            expected_window_count=diagnostics["expected_window_count"],
            generated_window_count=diagnostics["generated_window_count"],
            incomplete_window_count=diagnostics["incomplete_window_count"],
            exchange_mismatch_window_count=diagnostics[
                "exchange_mismatch_window_count"
            ],
            started_at=started_at,
        )


def _stage_and_promote(
    *,
    connection,
    output_sql: str,
    target_path: Path,
    source_path: Path,
    partition_key: str,
    silver_freq: str,
    source_freq: str,
    source_validation: _RelationValidation,
    expected_row_count: int,
    expected_window_count: int,
    generated_window_count: int,
    incomplete_window_count: int,
    exchange_mismatch_window_count: int,
    started_at: float,
) -> IndexMinsSilverWriteResult:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = target_path.with_name(f"{target_path.name}.p3-{uuid4().hex}.tmp")
    promoted = False
    try:
        connection.execute(copy_query_to_parquet(output_sql, staging_path))
        staging_validation = _validate_existing_target(
            connection,
            target_path=staging_path,
            relation_sql=read_parquet(staging_path, hive_partitioning=False),
            expected_freq=silver_freq,
            partition_key=partition_key,
            expected_row_count=expected_row_count,
            require_null_vwap=int(silver_freq[:-3]) in INDEX_MINS_DERIVED_FREQS,
        )
        if staging_validation.row_count != expected_row_count:
            raise IndexMinsSilverValidationError(
                "index_mins Silver staging row reconciliation failed: "
                f"expected={expected_row_count}, actual={staging_validation.row_count}."
            )
        if target_path.exists():
            raise IndexMinsSilverValidationError(
                "index_mins Silver target appeared during write; refusing overwrite: "
                f"{target_path}"
            )
        os.replace(staging_path, target_path)
        promoted = True
    finally:
        if not promoted and staging_path.exists():
            staging_path.unlink()

    return _result(
        target_path=target_path,
        source_path=source_path,
        partition_key=partition_key,
        silver_freq=silver_freq,
        source_freq=source_freq,
        source_validation=source_validation,
        written_row_count=expected_row_count,
        expected_window_count=expected_window_count,
        generated_window_count=generated_window_count,
        incomplete_window_count=incomplete_window_count,
        exchange_mismatch_window_count=exchange_mismatch_window_count,
        elapsed_ms=_elapsed_ms(started_at),
        write_mode="staged_atomic_replace",
    )


def _result(
    *,
    target_path: Path,
    source_path: Path,
    partition_key: str,
    silver_freq: str,
    source_freq: str,
    source_validation: _RelationValidation,
    written_row_count: int,
    expected_window_count: int,
    generated_window_count: int,
    incomplete_window_count: int,
    exchange_mismatch_window_count: int,
    elapsed_ms: float,
    write_mode: str,
) -> IndexMinsSilverWriteResult:
    return IndexMinsSilverWriteResult(
        silver_file_path=target_path,
        source_file_path=source_path,
        partition_key=partition_key,
        silver_freq=silver_freq,
        source_freq=source_freq,
        source_row_count=source_validation.row_count,
        written_row_count=written_row_count,
        expected_window_count=expected_window_count,
        generated_window_count=generated_window_count,
        incomplete_window_count=incomplete_window_count,
        exchange_mismatch_window_count=exchange_mismatch_window_count,
        duplicate_key_count=source_validation.duplicate_key_count,
        invalid_row_count=source_validation.invalid_row_count,
        elapsed_ms=elapsed_ms,
        write_mode=write_mode,
    )


def _validate_existing_target(
    connection,
    *,
    target_path: Path,
    relation_sql: str,
    expected_freq: str,
    partition_key: str,
    expected_row_count: int,
    require_null_vwap: bool,
) -> _RelationValidation:
    _assert_schema(
        connection,
        target_path,
        SILVER_INDEX_MINS_SCHEMA,
        label="index_mins Silver target",
    )
    validation = _validate_relation(
        connection,
        relation_sql=relation_sql,
        expected_freq=expected_freq,
        partition_key=partition_key,
        require_null_vwap=require_null_vwap,
    )
    if validation.row_count != expected_row_count:
        raise IndexMinsSilverValidationError(
            "Existing index_mins Silver partition has an unexpected row count and "
            f"will not be overwritten: path={target_path}, "
            f"expected={expected_row_count}, actual={validation.row_count}."
        )
    _require_relation_clean(
        validation,
        label="Existing index_mins Silver partition",
        target_path=target_path,
    )
    return validation


def _require_source_validation(
    validation: _RelationValidation,
    *,
    label: str,
    partition_key: str,
    expected_freq: str,
) -> None:
    if validation.row_count <= 0:
        raise IndexMinsSilverValidationError(
            f"{label} is empty: freq={expected_freq}, partition={partition_key}."
        )
    _require_relation_clean(
        validation,
        label=label,
        target_path=None,
    )


def _require_relation_clean(
    validation: _RelationValidation,
    *,
    label: str,
    target_path: Path | None,
) -> None:
    if validation.duplicate_key_count or validation.invalid_row_count:
        suffix = f", path={target_path}" if target_path else ""
        raise IndexMinsSilverValidationError(
            f"{label} failed Silver contract: "
            f"duplicate_key_count={validation.duplicate_key_count}, "
            f"invalid_row_count={validation.invalid_row_count}{suffix}."
        )
    if target_path is not None and validation.non_null_vwap_count:
        raise IndexMinsSilverValidationError(
            f"Derived index_mins Silver vwap must be NULL: path={target_path}, "
            f"non_null_vwap_count={validation.non_null_vwap_count}."
        )


def _validate_relation(
    connection,
    *,
    relation_sql: str,
    expected_freq: str,
    partition_key: str,
    require_null_vwap: bool,
) -> _RelationValidation:
    relation_select = (
        relation_sql
        if relation_sql.lstrip().lower().startswith("select")
        else f"SELECT * FROM {relation_sql}"
    )
    row_count, invalid_row_count, duplicate_key_count, non_null_vwap_count = connection.execute(
        f"""
        SELECT
          count(*),
          count(*) FILTER (
            WHERE ts_code IS NULL
               OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR NOT regexp_matches(upper(trim(CAST(ts_code AS VARCHAR))), '^[0-9A-Z]{{1,12}}\\.[A-Z0-9]{{2,8}}$')
               OR freq IS NULL
               OR CAST(freq AS VARCHAR) <> ?
               OR trade_time IS NULL
               OR CAST(trade_time AS DATE) <> CAST(? AS DATE)
               OR open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
               OR NOT isfinite(CAST(open AS DOUBLE))
               OR NOT isfinite(CAST(close AS DOUBLE))
               OR NOT isfinite(CAST(high AS DOUBLE))
               OR NOT isfinite(CAST(low AS DOUBLE))
               OR open <= 0 OR close <= 0 OR high <= 0 OR low <= 0
               OR high < low OR open < low OR open > high
               OR close < low OR close > high
               OR vol IS NULL OR amount IS NULL
               OR NOT isfinite(CAST(vol AS DOUBLE))
               OR NOT isfinite(CAST(amount AS DOUBLE))
               OR vol < 0 OR amount < 0
               OR (vwap IS NOT NULL AND (
                    NOT isfinite(CAST(vwap AS DOUBLE)) OR CAST(vwap AS DOUBLE) < 0
               ))
          ),
          count(*) - count(DISTINCT (ts_code, freq, trade_time)),
          count(*) FILTER (WHERE vwap IS NOT NULL)
        FROM ({relation_select}) relation_rows
        """,
        [expected_freq, partition_key],
    ).fetchone()
    return _RelationValidation(
        row_count=int(row_count or 0),
        duplicate_key_count=int(duplicate_key_count or 0),
        invalid_row_count=int(invalid_row_count or 0),
        non_null_vwap_count=(int(non_null_vwap_count or 0) if require_null_vwap else 0),
    )


def _assert_schema(connection, path: Path, schema, *, label: str) -> None:
    expected = tuple((column.name, column.type.upper()) for column in schema)
    try:
        observed = tuple(
            (str(row[0]), str(row[1]).upper().split("(", 1)[0])
            for row in connection.execute(
                describe_parquet_query(path, hive_partitioning=False)
            ).fetchall()
        )
    except Exception as error:  # noqa: BLE001 - normalize corrupt Parquet failures.
        raise IndexMinsSilverValidationError(
            f"{label} cannot be read as Parquet: path={path}."
        ) from error
    if observed != expected:
        raise IndexMinsSilverValidationError(
            f"{label} schema does not match contract: expected={expected}, observed={observed}."
        )


def _native_normalized_sql(source_path: Path) -> str:
    return _native_source_sql(read_parquet(source_path, hive_partitioning=False))


def _native_source_sql(relation_sql: str) -> str:
    return f"""
    SELECT
      upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
      trim(CAST(freq AS VARCHAR)) AS freq,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      CAST(open AS DOUBLE) AS open,
      CAST(close AS DOUBLE) AS close,
      CAST(high AS DOUBLE) AS high,
      CAST(low AS DOUBLE) AS low,
      CAST(vol AS DOUBLE) AS vol,
      CAST(amount AS DOUBLE) AS amount,
      NULLIF(trim(CAST(exchange AS VARCHAR)), '') AS exchange,
      CAST(vwap AS DOUBLE) AS vwap
    FROM {relation_sql}
    """


def _native_output_sql(normalized_sql: str) -> str:
    return f"""
    SELECT ts_code, freq, trade_time, open, close, high, low, vol, amount, exchange, vwap
    FROM ({normalized_sql}) normalized
    ORDER BY ts_code, trade_time
    """


def _derived_diagnostics(
    connection,
    *,
    source_sql: str,
    silver_freq: str,
    partition_key: str,
) -> dict[str, int]:
    window_map = _window_map_sql(silver_freq)
    completion = _completion_predicate(
        silver_freq,
        "source_row_count",
        "window_id",
    )
    row = connection.execute(
        f"""
        WITH source_rows AS (
          {source_sql}
        ), source_stock_days AS (
          SELECT DISTINCT ts_code, CAST(trade_time AS DATE) AS trade_date
          FROM source_rows
          WHERE CAST(trade_time AS DATE) = CAST(? AS DATE)
        ), window_map AS (
          {window_map}
        ), expected_windows AS (
          SELECT days.ts_code, days.trade_date, map.window_id,
                 count(*) AS expected_source_row_count
          FROM source_stock_days days CROSS JOIN window_map map
          GROUP BY days.ts_code, days.trade_date, map.window_id
        ), actual_windows AS (
          SELECT source_rows.ts_code,
                 CAST(source_rows.trade_time AS DATE) AS trade_date,
                 map.window_id,
                 max(source_rows.trade_time) AS trade_time,
                 count(*) AS source_row_count,
                 count(DISTINCT coalesce(source_rows.exchange, '<NULL>')) AS exchange_count
          FROM source_rows
          INNER JOIN window_map map
            ON strftime(source_rows.trade_time, '%H:%M:%S') = map.source_time
          WHERE CAST(source_rows.trade_time AS DATE) = CAST(? AS DATE)
          GROUP BY source_rows.ts_code, CAST(source_rows.trade_time AS DATE), map.window_id
        ), status AS (
          SELECT expected.ts_code, expected.trade_date, expected.window_id,
                 coalesce(actual.source_row_count, 0) AS source_row_count,
                 coalesce(actual.exchange_count, 0) AS exchange_count,
                 actual.trade_time
          FROM expected_windows expected
          LEFT JOIN actual_windows actual
            ON expected.ts_code = actual.ts_code
           AND expected.trade_date = actual.trade_date
           AND expected.window_id = actual.window_id
        )
        SELECT
          (SELECT count(*) FROM source_rows
           WHERE CAST(trade_time AS DATE) = CAST(? AS DATE)),
          count(*),
          count(*) FILTER (
            WHERE source_row_count > 0
              AND NOT ({completion})
          ) + count(*) FILTER (WHERE source_row_count = 0),
          count(*) FILTER (WHERE source_row_count > 0 AND exchange_count > 1),
          count(*) FILTER (
            WHERE source_row_count > 0
              AND ({completion})
              AND exchange_count = 1
          )
        FROM status
        """,
        [partition_key, partition_key, partition_key],
    ).fetchone()
    return {
        "source_row_count": int(row[0] or 0),
        "expected_window_count": int(row[1] or 0),
        "incomplete_window_count": int(row[2] or 0),
        "exchange_mismatch_window_count": int(row[3] or 0),
        "generated_window_count": int(row[4] or 0),
    }


def _derived_output_sql(*, source_sql: str, silver_freq: str, partition_key: str) -> str:
    window_map = _window_map_sql(silver_freq)
    completion = _completion_predicate(
        silver_freq,
        "source_row_count",
        "window_id",
    )
    return f"""
    WITH source_rows AS (
      {source_sql}
    ), window_map AS (
      {window_map}
    ), windowed_rows AS (
      SELECT source_rows.*, map.window_id, map.target_time,
             row_number() OVER (
               PARTITION BY source_rows.ts_code, CAST(source_rows.trade_time AS DATE), map.window_id
               ORDER BY source_rows.trade_time
             ) AS ascending_row_number,
             row_number() OVER (
               PARTITION BY source_rows.ts_code, CAST(source_rows.trade_time AS DATE), map.window_id
               ORDER BY source_rows.trade_time DESC
             ) AS descending_row_number
      FROM source_rows
      INNER JOIN window_map map
        ON strftime(source_rows.trade_time, '%H:%M:%S') = map.source_time
      WHERE CAST(source_rows.trade_time AS DATE) = CAST('{partition_key}' AS DATE)
    ), aggregated AS (
      SELECT ts_code,
             '{silver_freq}'::VARCHAR AS freq,
             max(trade_time) AS trade_time,
             max(open) FILTER (WHERE ascending_row_number = 1) AS open,
             max(close) FILTER (WHERE descending_row_number = 1) AS close,
             max(high) AS high,
             min(low) AS low,
             sum(vol) AS vol,
             sum(amount) AS amount,
             max(exchange) AS exchange,
             count(*) AS source_row_count,
             count(DISTINCT coalesce(exchange, '<NULL>')) AS exchange_count,
             window_id,
             max(target_time) AS target_time
      FROM windowed_rows
      GROUP BY ts_code, CAST(trade_time AS DATE), window_id
    )
    SELECT ts_code, freq, trade_time, open, close, high, low, vol, amount, exchange,
           CAST(NULL AS DOUBLE) AS vwap
    FROM aggregated
    WHERE exchange_count = 1
      AND strftime(trade_time, '%H:%M:%S') = target_time
      AND ({completion.replace('count(*)', 'source_row_count')})
    ORDER BY ts_code, trade_time
    """


def _window_map_sql(silver_freq: str) -> str:
    values = ",\n          ".join(
        f"('{source_time}', {window_id}, '{target_time}')"
        for source_time, window_id, target_time in index_mins_derived_windows(silver_freq)
    )
    return (
        "SELECT * FROM (VALUES\n          "
        f"{values}"
        ") AS windows(source_time, window_id, target_time)"
    )


def _completion_predicate(
    silver_freq: str,
    source_row_count: str,
    window_id: str,
) -> str:
    if int(normalize_index_mins_silver_freq(silver_freq)[:-3]) == 90:
        return (
            f"({source_row_count} = 3 OR "
            f"({window_id} = 3 AND {source_row_count} = 2))"
        )
    return f"{source_row_count} = 2"


def _elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000
