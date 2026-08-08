import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_RAW_COLUMNS,
    INDEX_DAILY_SILVER_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_index_daily_path,
    raw_index_daily_staging_path,
    silver_index_daily_path,
)
from orchestrator.defs.prod_db.index_daily import (
    PROD_INDEX_DAILY_DUCKDB_ATTACH_OPTIONS,
    PROD_INDEX_DAILY_DUCKDB_ATTACHED_DATABASE,
    build_prod_index_daily_duckdb_source_sql,
    index_code_set_hash,
    normalize_index_codes,
    validate_prod_index_daily_duckdb_attach_options_contract,
    validate_prod_index_daily_duckdb_source_contract,
    validate_prod_index_daily_select_contract,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_DAILY_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.configs import (
    IndexDailyRawConfig,
    normalize_iso_trade_date,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger

INDEX_DAILY_RAW_COLUMN_TYPES = {column.name: column.type for column in RAW_INDEX_DAILY_SCHEMA}

INDEX_DAILY_SILVER_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_INDEX_DAILY_SCHEMA
}


def _selected_partition_keys(context: dg.AssetExecutionContext) -> tuple[str, ...]:
    return tuple(sorted(set(context.partition_keys)))


def _column_names(
    connection, path: Path, *, hive_partitioning: bool = False
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=hive_partitioning)
        ).fetchone()[0]
    )


def _sample_dicts(
    columns: list[str], rows: list[tuple[Any, ...]]
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _human_materialization_metadata(
    *,
    summary: str,
    next_action: str,
    result_status: str,
    input_summary: dict[str, Any],
    diagnostic_ref: str,
    code_set_summary: dict[str, Any] | None = None,
    filter_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "summary": summary,
        "next_action": next_action,
        "result_status": result_status,
        "input_summary": input_summary,
        "diagnostic_ref": diagnostic_ref,
    }
    if code_set_summary is not None:
        metadata["code_set_summary"] = code_set_summary
    if filter_summary is not None:
        metadata["filter_summary"] = filter_summary
    return metadata


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


def _registered_index_ts_codes(context: dg.AssetExecutionContext) -> tuple[str, ...]:
    codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )
    if not codes:
        raise RuntimeError(
            f"{cn_a_index_ts_codes.name} has no registered partition keys."
        )
    return codes


@dataclass(frozen=True)
class IndexDailyRawWriteResult:
    raw_file_path: Path
    row_count: int
    observed_columns: tuple[str, ...]
    expected_code_count: int
    expected_code_set_hash: str
    returned_code_count: int
    source_row_count: int
    duplicate_key_count: int
    missing_code_count: int
    extra_code_count: int
    query_count: int = 1
    source_method: str = "prod_core_db"
    write_mode: str = "replace"

    def materialization_extra_metadata(self, *, partition_key: str) -> dict[str, object]:
        return {
            "partition_key": partition_key,
            "source_method": self.source_method,
            "source_system": SourceSystem.PROD_CORE_DB.value,
            "source_table": "core_serving.index_daily_serving",
            "write_mode": self.write_mode,
            "expected_code_count": self.expected_code_count,
            "expected_code_set_hash": self.expected_code_set_hash,
            "returned_code_count": self.returned_code_count,
            "source_row_count": self.source_row_count,
            "duplicate_key_count": self.duplicate_key_count,
            "missing_code_count": self.missing_code_count,
            "extra_code_count": self.extra_code_count,
            "query_count": self.query_count,
        }


@dataclass(frozen=True)
class SilverIndexDailyWriteResult:
    partition_key: str
    silver_file_path: Path
    source_file_path: Path
    source_row_count: int
    output_row_count: int
    observed_columns: tuple[str, ...]
    duplicate_removed_count: int
    duplicate_sample_rows: list[dict[str, Any]]

    def materialization_metadata(self) -> dict[str, Any]:
        return {
            "partition_key": self.partition_key,
            "file_path": str(self.silver_file_path),
            "source_file_path": str(self.source_file_path),
            "source_asset": "raw_index_daily",
            "source_partition_set": cn_a_index_trade_days.name,
            "source_row_count": self.source_row_count,
            "output_row_count": self.output_row_count,
            "output_columns": list(self.observed_columns),
            "duplicate_removed_count": self.duplicate_removed_count,
            "duplicate_sample_rows": self.duplicate_sample_rows,
        }


def write_raw_index_daily_partition_from_prod_db(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    partition_key: str,
    index_codes: Sequence[str],
    run_id: str,
) -> IndexDailyRawWriteResult:
    normalized_partition_key = normalize_iso_trade_date(partition_key)
    normalized_codes = normalize_index_codes(index_codes)
    validate_prod_index_daily_select_contract()
    validate_prod_index_daily_duckdb_source_contract()
    validate_prod_index_daily_duckdb_attach_options_contract()
    source_sql = build_prod_index_daily_duckdb_source_sql(
        trade_date=normalized_partition_key,
        index_codes=normalized_codes,
    )
    return _write_raw_index_daily_rows_from_prod_db_source(
        duckdb=duckdb,
        postgres_connection_string=prod_postgres.duckdb_connection_string(),
        source_sql=source_sql,
        target_path=raw_index_daily_path(lake_root_path, normalized_partition_key),
        staging_path=raw_index_daily_staging_path(
            lake_root_path,
            run_id,
            normalized_partition_key,
        ),
        index_codes=normalized_codes,
        partition_key=normalized_partition_key,
        load_postgres_extension=True,
    )


def _write_raw_index_daily_rows_from_prod_db_source(
    *,
    duckdb: DuckDBResource,
    source_sql: str,
    target_path: Path,
    staging_path: Path,
    index_codes: Sequence[str],
    partition_key: str,
    load_postgres_extension: bool,
    postgres_connection_string: str | None = None,
) -> IndexDailyRawWriteResult:
    normalized_partition_key = normalize_iso_trade_date(partition_key)
    expected_codes = normalize_index_codes(index_codes)
    expected_codes_sql = ", ".join(duckdb_string(index_code) for index_code in expected_codes)
    expected_code_set_sql = _index_daily_expected_codes_sql(expected_codes)
    source_trade_date = normalized_partition_key.replace("-", "")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    if staging_path.exists():
        staging_path.unlink()

    duckdb_resource = duckdb
    with duckdb_resource.connect() as connection:
        if load_postgres_extension:
            _load_duckdb_postgres_extension(connection)
            if postgres_connection_string is None:
                raise RuntimeError(
                    "Prod DB index_daily extraction requires a Postgres connection string."
                )
            _attach_prod_index_daily_postgres_database(
                connection,
                postgres_connection_string=postgres_connection_string,
            )
        connection.execute(
            "CREATE TEMP TABLE prod_index_daily_source AS "
            f"SELECT {', '.join(INDEX_DAILY_RAW_COLUMNS)} "
            f"FROM ({source_sql}) AS source_rows"
        )
        source_row_count = int(
            connection.execute("SELECT count(*) FROM prod_index_daily_source").fetchone()[0]
        )
        if source_row_count == 0:
            raise RuntimeError(
                f"Prod DB index_daily returned 0 rows for {normalized_partition_key}."
            )

        null_key_count = int(
            connection.execute(
                """
                SELECT count(*)
                FROM prod_index_daily_source
                WHERE ts_code IS NULL
                   OR trim(CAST(ts_code AS VARCHAR)) = ''
                   OR trade_date IS NULL
                   OR trim(CAST(trade_date AS VARCHAR)) = ''
                """
            ).fetchone()[0]
        )
        if null_key_count:
            raise RuntimeError(
                "Prod DB index_daily returned rows with blank keys: "
                f"null_key_count={null_key_count}."
            )

        invalid_scope_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM prod_index_daily_source
                WHERE CAST(trade_date AS VARCHAR) != {duckdb_string(source_trade_date)}
                   OR CAST(ts_code AS VARCHAR) NOT IN ({expected_codes_sql})
                """
            ).fetchone()[0]
        )
        if invalid_scope_count:
            raise RuntimeError(
                "Prod DB index_daily returned rows outside the requested code/date "
                f"scope: invalid_row_count={invalid_scope_count}."
            )

        duplicate_key_count = int(
            connection.execute(
                """
                SELECT count(*)
                FROM (
                  SELECT ts_code, trade_date
                  FROM prod_index_daily_source
                  GROUP BY ts_code, trade_date
                  HAVING count(*) > 1
                ) duplicate_keys
                """
            ).fetchone()[0]
        )
        if duplicate_key_count:
            raise RuntimeError(
                "Prod DB index_daily returned duplicate ts_code/trade_date keys: "
                f"duplicate_key_count={duplicate_key_count}."
            )

        coverage_row = connection.execute(
            f"""
            WITH expected AS (
              SELECT ts_code FROM {expected_code_set_sql}
            ),
            observed AS (
              SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
              FROM prod_index_daily_source
            )
            SELECT
              (SELECT count(*) FROM observed) AS returned_code_count,
              (
                SELECT count(*)
                FROM expected
                LEFT JOIN observed USING (ts_code)
                WHERE observed.ts_code IS NULL
              ) AS missing_code_count,
              (
                SELECT count(*)
                FROM observed
                LEFT JOIN expected USING (ts_code)
                WHERE expected.ts_code IS NULL
              ) AS extra_code_count
            """
        ).fetchone()
        returned_code_count = int(coverage_row[0])
        missing_code_count = int(coverage_row[1])
        extra_code_count = int(coverage_row[2])
        if missing_code_count or extra_code_count:
            missing_samples = _index_daily_code_diff_samples(
                connection,
                expected_code_set_sql=expected_code_set_sql,
                observed_codes_sql="""
                    SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
                    FROM prod_index_daily_source
                """,
                direction="missing",
            )
            extra_samples = _index_daily_code_diff_samples(
                connection,
                expected_code_set_sql=expected_code_set_sql,
                observed_codes_sql="""
                    SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
                    FROM prod_index_daily_source
                """,
                direction="extra",
            )
            raise RuntimeError(
                "Prod DB index_daily code coverage does not match DG dynamic "
                f"partitions for {normalized_partition_key}: "
                f"missing_code_count={missing_code_count}, "
                f"extra_code_count={extra_code_count}, "
                f"missing_samples={missing_samples}, extra_samples={extra_samples}."
            )

        connection.execute(
            copy_query_to_parquet(
                _prod_db_raw_index_daily_output_sql(),
                staging_path,
            )
        )
        observed_columns = tuple(_column_names(connection, staging_path))
        output_row_count = _row_count(connection, staging_path)
        if output_row_count != source_row_count:
            raise RuntimeError(
                "raw_index_daily staging row count differs from prod source: "
                f"source_row_count={source_row_count}, output_row_count={output_row_count}."
            )
        _assert_raw_index_daily_staging_contract(
            connection,
            staging_path=staging_path,
            partition_key=normalized_partition_key,
            expected_codes=expected_codes,
        )

    os.replace(staging_path, target_path)
    return IndexDailyRawWriteResult(
        raw_file_path=target_path,
        row_count=output_row_count,
        observed_columns=observed_columns,
        expected_code_count=len(expected_codes),
        expected_code_set_hash=index_code_set_hash(expected_codes),
        returned_code_count=returned_code_count,
        source_row_count=source_row_count,
        duplicate_key_count=duplicate_key_count,
        missing_code_count=missing_code_count,
        extra_code_count=extra_code_count,
    )


def _index_daily_expected_codes_sql(index_codes: Sequence[str]) -> str:
    rows = ", ".join(f"({duckdb_string(index_code)})" for index_code in index_codes)
    return f"(VALUES {rows}) AS expected(ts_code)"


def _index_daily_code_diff_samples(
    connection,
    *,
    expected_code_set_sql: str,
    observed_codes_sql: str,
    direction: str,
) -> list[str]:
    if direction == "missing":
        sql = f"""
        SELECT expected.ts_code
        FROM {expected_code_set_sql}
        LEFT JOIN ({observed_codes_sql}) observed USING (ts_code)
        WHERE observed.ts_code IS NULL
        ORDER BY expected.ts_code
        LIMIT 10
        """
    elif direction == "extra":
        sql = f"""
        SELECT observed.ts_code
        FROM ({observed_codes_sql}) observed
        LEFT JOIN (SELECT ts_code FROM {expected_code_set_sql}) expected USING (ts_code)
        WHERE expected.ts_code IS NULL
        ORDER BY observed.ts_code
        LIMIT 10
        """
    else:
        raise ValueError("direction must be missing or extra.")
    return [str(row[0]) for row in connection.execute(sql).fetchall()]


def _prod_db_raw_index_daily_output_sql() -> str:
    select_columns = ",\n      ".join(
        f"CAST({column} AS {INDEX_DAILY_RAW_COLUMN_TYPES[column]}) AS {column}"
        for column in INDEX_DAILY_RAW_COLUMNS
    )
    return f"""
    SELECT
      {select_columns}
    FROM prod_index_daily_source
    ORDER BY ts_code
    """


def _assert_raw_index_daily_staging_contract(
    connection,
    *,
    staging_path: Path,
    partition_key: str,
    expected_codes: Sequence[str],
) -> None:
    expected_trade_date = partition_key.replace("-", "")
    expected_codes_sql = ", ".join(duckdb_string(index_code) for index_code in expected_codes)
    columns = tuple(_column_names(connection, staging_path))
    if columns != INDEX_DAILY_RAW_COLUMNS:
        raise RuntimeError(
            "raw_index_daily staging columns do not match contract: "
            f"expected={list(INDEX_DAILY_RAW_COLUMNS)}, observed={list(columns)}."
        )
    invalid_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(staging_path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR trade_date IS NULL
               OR CAST(trade_date AS VARCHAR) != {duckdb_string(expected_trade_date)}
               OR CAST(ts_code AS VARCHAR) NOT IN ({expected_codes_sql})
            """
        ).fetchone()[0]
    )
    if invalid_count:
        raise RuntimeError(
            "raw_index_daily staging failed key/date scope validation: "
            f"invalid_row_count={invalid_count}."
        )
    duplicate_key_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_date
              FROM {read_parquet(staging_path, hive_partitioning=False)}
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
    )
    if duplicate_key_count:
        raise RuntimeError(
            "raw_index_daily staging has duplicate ts_code/trade_date keys: "
            f"duplicate_key_count={duplicate_key_count}."
        )


def _load_duckdb_postgres_extension(connection) -> None:
    try:
        connection.execute("LOAD postgres")
        return
    except Exception:  # noqa: BLE001 - retry with INSTALL for local envs.
        try:
            connection.execute("INSTALL postgres")
            connection.execute("LOAD postgres")
            return
        except Exception as install_error:
            raise RuntimeError(
                "DuckDB postgres extension is required for prod DB index_daily "
                "extraction. Install/load the DuckDB postgres extension before "
                "running raw_index_daily_update_job."
            ) from install_error


def _attach_prod_index_daily_postgres_database(
    connection,
    *,
    postgres_connection_string: str,
) -> None:
    attach_sql = (
        "ATTACH "
        + duckdb_string(postgres_connection_string)
        + (
            f" AS {PROD_INDEX_DAILY_DUCKDB_ATTACHED_DATABASE} "
            f"({PROD_INDEX_DAILY_DUCKDB_ATTACH_OPTIONS})"
        )
    )
    try:
        connection.execute(attach_sql)
    except Exception:  # noqa: BLE001 - avoid leaking conninfo through DuckDB errors.
        raise RuntimeError(
            "DuckDB failed to attach prod Postgres for index_daily extraction. "
            "Check PROD_POSTGRES_* environment variables, network access, and "
            "DuckDB postgres extension availability. Connection details are omitted."
        ) from None


def _index_daily_by_date_normalized_select(
    raw_path: Path,
    source_trade_date: str,
) -> str:
    return f"""
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date,
  CAST(open AS DOUBLE) AS open,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(close AS DOUBLE) AS close,
  CAST(pre_close AS DOUBLE) AS pre_close,
  CAST(change AS DOUBLE) AS change_amount,
  CAST(pct_chg AS DOUBLE) AS pct_chg,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount
FROM {read_parquet(raw_path, hive_partitioning=False)}
WHERE CAST(trade_date AS VARCHAR) = {duckdb_string(source_trade_date)}
"""


def _conflict_key_count_from_normalized_sql(connection, normalized_sql: str) -> int:
    return int(
        connection.execute(
            f"""
            WITH distinct_rows AS (
              SELECT DISTINCT *
              FROM ({normalized_sql}) normalized
            )
            SELECT count(*) AS conflict_key_count
            FROM (
              SELECT ts_code, trade_date
              FROM distinct_rows
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) conflict_keys
            """
        ).fetchone()[0]
    )


def _conflict_sample_keys_from_normalized_sql(
    connection,
    normalized_sql: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        WITH distinct_rows AS (
          SELECT DISTINCT *
          FROM ({normalized_sql}) normalized
        )
        SELECT ts_code, trade_date, count(*) AS version_count
        FROM distinct_rows
        GROUP BY ts_code, trade_date
        HAVING count(*) > 1
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    return _sample_dicts(["ts_code", "trade_date", "version_count"], rows)


def _duplicate_removed_count_from_normalized_sql(
    connection, normalized_sql: str
) -> int:
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        deduped AS (
          SELECT DISTINCT *
          FROM normalized
        )
        SELECT
          (SELECT count(*) FROM normalized) - (SELECT count(*) FROM deduped)
            AS duplicate_removed_count
        """
    ).fetchone()
    return int(row[0])


def _duplicate_sample_rows_from_normalized_sql(
    connection,
    normalized_sql: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        )
        SELECT
          ts_code,
          trade_date,
          open,
          high,
          low,
          close,
          pre_close,
          change_amount,
          pct_chg,
          vol,
          amount,
          count(*) AS duplicate_row_count
        FROM normalized
        GROUP BY
          ts_code,
          trade_date,
          open,
          high,
          low,
          close,
          pre_close,
          change_amount,
          pct_chg,
          vol,
          amount
        HAVING count(*) > 1
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    return _sample_dicts([*INDEX_DAILY_SILVER_COLUMNS, "duplicate_row_count"], rows)


def materialize_silver_index_daily_partition_from_raw_by_date(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    partition_key: str,
    log: DgStdoutLogger | None = None,
) -> SilverIndexDailyWriteResult:
    normalized_partition_key = normalize_iso_trade_date(partition_key)
    raw_path = raw_index_daily_path(lake_root_path, normalized_partition_key)
    if not raw_path.exists():
        raise FileNotFoundError(
            "Missing raw_index_daily by-date file for silver_index_daily: "
            f"{raw_path}"
        )

    return materialize_silver_index_daily_partition_from_raw_file(
        raw_path=raw_path,
        target_path=silver_index_daily_path(lake_root_path, normalized_partition_key),
        duckdb=duckdb,
        partition_key=normalized_partition_key,
        log=log,
    )


def materialize_silver_index_daily_partition_from_raw_file(
    *,
    raw_path: Path,
    target_path: Path,
    duckdb: DuckDBResource,
    partition_key: str,
    log: DgStdoutLogger | None = None,
) -> SilverIndexDailyWriteResult:
    """Run the formal Silver normalization against an explicit Raw/target pair."""

    with duckdb.connect() as connection:
        return write_silver_index_daily_partition_from_raw_file(
            connection,
            raw_path=raw_path,
            target_path=target_path,
            partition_key=partition_key,
            log=log,
        )


def write_silver_index_daily_partition_from_raw_file(
    connection,
    *,
    raw_path: Path,
    target_path: Path,
    partition_key: str,
    log: DgStdoutLogger | None = None,
) -> SilverIndexDailyWriteResult:
    """Connection-reusing form of the formal Silver normalization writer."""

    normalized_partition_key = normalize_iso_trade_date(partition_key)
    source_trade_date = normalized_partition_key.replace("-", "")
    if not raw_path.exists():
        raise FileNotFoundError(
            "Missing raw_index_daily file for silver_index_daily: " f"{raw_path}"
        )

    normalized_sql = _index_daily_by_date_normalized_select(
        raw_path,
        source_trade_date,
    )
    conflict_key_count = _conflict_key_count_from_normalized_sql(
        connection,
        normalized_sql,
    )
    if conflict_key_count:
        raise RuntimeError(
            "raw_index_daily has conflicting duplicate rows for "
            f"{normalized_partition_key}: "
            f"{_conflict_sample_keys_from_normalized_sql(connection, normalized_sql)}"
        )

    raw_row_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({normalized_sql}) normalized"
        ).fetchone()[0]
    )
    if raw_row_count <= 0:
        raise RuntimeError(
            "raw_index_daily contains no rows for silver_index_daily "
            f"partition {normalized_partition_key}."
        )
    duplicate_removed_count = _duplicate_removed_count_from_normalized_sql(
        connection,
        normalized_sql,
    )
    duplicate_sample_rows = _duplicate_sample_rows_from_normalized_sql(
        connection,
        normalized_sql,
    )
    _replace_parquet_from_query(
        connection,
        f"""
        SELECT DISTINCT *
        FROM ({normalized_sql}) normalized
        ORDER BY ts_code
        """,
        target_path,
    )
    columns = tuple(_column_names(connection, target_path))
    row_count = _row_count(connection, target_path)

    if log:
        log.stdout(
            "silver_partition_written",
            partition_key=normalized_partition_key,
            trade_date=source_trade_date,
            rows=row_count,
            raw_rows=raw_row_count,
            path=target_path,
        )

    return SilverIndexDailyWriteResult(
        partition_key=normalized_partition_key,
        silver_file_path=target_path,
        source_file_path=raw_path,
        source_row_count=raw_row_count,
        output_row_count=row_count,
        observed_columns=columns,
        duplicate_removed_count=duplicate_removed_count,
        duplicate_sample_rows=duplicate_sample_rows,
    )


def materialize_silver_index_daily_partitions_from_raw_by_date(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    partition_keys: Sequence[str],
    log: DgStdoutLogger | None = None,
) -> dict[str, dict[str, Any]]:
    partition_metadata: dict[str, dict[str, Any]] = {}
    for partition_key in tuple(sorted(set(partition_keys))):
        write_result = materialize_silver_index_daily_partition_from_raw_by_date(
            lake_root_path=lake_root_path,
            duckdb=duckdb,
            partition_key=partition_key,
            log=log,
        )
        partition_metadata[write_result.partition_key] = (
            write_result.materialization_metadata()
        )

    if log:
        log.stdout(
            "silver_partitions_completed",
            partitions=len(partition_metadata),
            total_rows=sum(
                item["output_row_count"] for item in partition_metadata.values()
            ),
        )

    return partition_metadata


@dg.asset(
    name="raw_index_daily",
    partitions_def=cn_a_index_trade_days,
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="index_daily",
        source_system=SourceSystem.PROD_CORE_DB,
        data_contract="prod_core_index_daily_by_date",
        column_schema=RAW_INDEX_DAILY_SCHEMA,
        path_template=lake_path_template(
            raw_index_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "source_table": "core_serving.index_daily_serving",
            "source_partition_set": cn_a_index_ts_codes.name,
            "source_policy": (
                "raw_index_daily reads the current Dagster cn_a_index_ts_codes "
                "dynamic partitions at runtime and exports only those codes from "
                "prod core_serving.index_daily_serving."
            ),
        },
    ),
    description="指数日线 raw 源镜像，按交易日从 prod core serving 只读同步 DG 管理的指数集合。",
)
def raw_index_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    config: IndexDailyRawConfig,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    if config.write_mode != "replace":
        raise ValueError("raw_index_daily only supports replace write_mode.")
    partition_key = normalize_iso_trade_date(context.partition_key)
    registered_index_codes = _registered_index_ts_codes(context)
    log = DgStdoutLogger("index_daily")
    log.stdout(
        "raw_index_daily_started",
        partition_key=partition_key,
        expected_code_count=len(registered_index_codes),
        write_mode=config.write_mode,
    )
    write_result = write_raw_index_daily_partition_from_prod_db(
        lake_root_path=lake_root.root(),
        duckdb=duckdb,
        prod_postgres=prod_postgres,
        partition_key=partition_key,
        index_codes=registered_index_codes,
        run_id=context.run_id,
    )
    extra_metadata = {
        **write_result.materialization_extra_metadata(partition_key=partition_key),
        **_human_materialization_metadata(
            summary=(
                "已写入指数日线 raw by-date 分区，来源为 prod core_serving.index_daily_serving。"
            ),
            next_action=(
                "等待 raw_index_daily 两个 blocking checks 通过；通过后 silver_index_daily 才能消费。"
            ),
            result_status="written",
            input_summary={
                "source_table": "core_serving.index_daily_serving",
                "source_mode": "prod_core_db_readonly",
                "partition_key": partition_key,
                "write_mode": write_result.write_mode,
                "query_count": write_result.query_count,
            },
            code_set_summary={
                "expected_code_count": write_result.expected_code_count,
                "expected_code_set_hash": write_result.expected_code_set_hash,
                "returned_code_count": write_result.returned_code_count,
                "missing_code_count": write_result.missing_code_count,
                "extra_code_count": write_result.extra_code_count,
                "duplicate_key_count": write_result.duplicate_key_count,
            },
            diagnostic_ref=(
                "完整诊断看 raw_index_daily_file_contract_check、"
                "raw_index_daily_code_coverage_check 和 run stdout。"
            ),
        ),
    }
    log.stdout(
        "raw_index_daily_completed",
        partition_key=partition_key,
        output_row_count=write_result.row_count,
        expected_code_count=write_result.expected_code_count,
        returned_code_count=write_result.returned_code_count,
        missing_code_count=write_result.missing_code_count,
        extra_code_count=write_result.extra_code_count,
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=write_result.raw_file_path,
            row_count=write_result.row_count,
            observed_columns=write_result.observed_columns,
            extra_metadata=extra_metadata,
        )
    )


@dg.asset(
    name="silver_index_daily",
    deps=[
        dg.AssetDep(raw_index_daily),
    ],
    partitions_def=cn_a_index_trade_days,
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="index_daily",
        source_system=SourceSystem.DERIVED,
        data_contract="active_index_daily",
        column_schema=SILVER_INDEX_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_index_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "source_asset": "raw_index_daily",
            "source_partition_set": cn_a_index_trade_days.name,
            "filter_policy": (
                "silver_index_daily reads the same trade_date raw_index_daily "
                "by-date file and preserves the raw file code set."
            ),
        },
    ),
    description="指数日线 silver 标准事实，从同交易日 raw_index_daily by-date 文件生成并保持 raw code set。",
)
def silver_index_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_keys = _selected_partition_keys(context)
    partition_metadata = materialize_silver_index_daily_partitions_from_raw_by_date(
        lake_root_path=lake_root.root(),
        duckdb=duckdb,
        partition_keys=partition_keys,
        log=DgStdoutLogger("index_daily"),
    )

    total_row_count = sum(
        item["output_row_count"] for item in partition_metadata.values()
    )
    duplicate_removed_count = sum(
        item["duplicate_removed_count"] for item in partition_metadata.values()
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            row_count=total_row_count,
            observed_columns=INDEX_DAILY_SILVER_COLUMNS,
            extra_metadata={
                **_human_materialization_metadata(
                    summary="已写入指数日线 silver 标准事实分区。",
                    next_action=(
                        "等待 silver_index_daily blocking checks 全部通过；通过后主要指数和其它下游才能消费。"
                    ),
                    result_status="written",
                    input_summary={
                        "source_asset": "raw_index_daily",
                        "partition_set": cn_a_index_trade_days.name,
                        "partition_count": len(partition_keys),
                    },
                    filter_summary={
                        "source_row_count": sum(
                            item["source_row_count"]
                            for item in partition_metadata.values()
                        ),
                        "output_row_count": total_row_count,
                        "duplicate_removed_count": duplicate_removed_count,
                    },
                    diagnostic_ref=(
                        "完整诊断看 silver_index_daily checks、partition_metadata 和 run stdout。"
                    ),
                ),
                "partition_keys": list(partition_keys),
                "partition_metadata": partition_metadata,
                "source_asset": "raw_index_daily",
            },
        )
    )
