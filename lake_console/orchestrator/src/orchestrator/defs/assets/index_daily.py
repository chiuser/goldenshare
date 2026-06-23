import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
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
    raw_index_daily_by_code_path,
    raw_index_daily_by_code_staging_dir,
    raw_index_daily_staging_path,
    silver_index_daily_path,
)
from orchestrator.defs.prod_db.index_daily import (
    PROD_INDEX_DAILY_DUCKDB_ATTACHED_DATABASE,
    PROD_INDEX_DAILY_DUCKDB_ATTACH_OPTIONS,
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
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_DAILY_SCHEMA,
    RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.configs import (
    IndexDailyRawConfig,
    IndexDailyRawByCodeConfig,
    normalize_iso_trade_date,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_api_io import fetch_tushare_index_daily_by_code_to_raw
from orchestrator.utils.dg_log_helper import DgStdoutLogger


INDEX_DAILY_RAW_COLUMN_TYPES = {column.name: column.type for column in RAW_INDEX_DAILY_SCHEMA}

INDEX_DAILY_SILVER_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_INDEX_DAILY_SCHEMA
}


def _source_date_window_from_config(
    config: IndexDailyRawByCodeConfig,
) -> tuple[str, str]:
    trade_date = normalize_iso_trade_date(config.trade_date).replace("-", "")
    return trade_date, trade_date


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
        except Exception as install_error:  # noqa: BLE001
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


def _read_parquet_paths(paths: Sequence[Path], *, union_by_name: bool = False) -> str:
    path_values = ", ".join(duckdb_string(path) for path in paths)
    union_clause = ", union_by_name=true" if union_by_name else ""
    return f"read_parquet([{path_values}], hive_partitioning=false{union_clause})"


def _index_daily_by_code_normalized_select(
    raw_paths: Sequence[Path],
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
FROM {_read_parquet_paths(raw_paths, union_by_name=True)}
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


def materialize_silver_index_daily_partitions_from_raw_by_code(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    partition_keys: Sequence[str],
    registered_index_codes: Sequence[str],
    log: DgStdoutLogger | None = None,
) -> dict[str, dict[str, Any]]:
    index_codes = tuple(sorted(set(registered_index_codes)))
    if not index_codes:
        raise RuntimeError(
            f"{cn_a_index_ts_codes.name} has no registered partition keys."
        )

    raw_paths_by_code = {
        index_code: raw_index_daily_by_code_path(lake_root_path, index_code)
        for index_code in index_codes
    }
    missing_raw_paths = [
        str(raw_path)
        for raw_path in raw_paths_by_code.values()
        if not raw_path.exists()
    ]
    if missing_raw_paths:
        raise FileNotFoundError(
            "Missing raw index daily by-code files for registered index codes: "
            f"{missing_raw_paths[:20]}"
        )

    raw_paths = tuple(raw_paths_by_code.values())
    partition_metadata: dict[str, dict[str, Any]] = {}
    with connect_configured_duckdb() as connection:
        for partition_key in tuple(sorted(set(partition_keys))):
            source_trade_date = partition_key.replace("-", "")
            target_path = silver_index_daily_path(lake_root_path, partition_key)
            normalized_sql = _index_daily_by_code_normalized_select(
                raw_paths,
                source_trade_date,
            )
            conflict_key_count = _conflict_key_count_from_normalized_sql(
                connection,
                normalized_sql,
            )
            if conflict_key_count:
                raise RuntimeError(
                    "raw_tushare_index_daily_by_code has conflicting duplicate rows for "
                    f"{partition_key}: "
                    f"{_conflict_sample_keys_from_normalized_sql(connection, normalized_sql)}"
                )

            raw_row_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({normalized_sql}) normalized"
                ).fetchone()[0]
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
            columns = _column_names(connection, target_path)
            row_count = _row_count(connection, target_path)
            partition_metadata[partition_key] = {
                "partition_key": partition_key,
                "file_path": str(target_path),
                "source_code_count": len(index_codes),
                "source_file_count": len(raw_paths),
                "missing_raw_file_count": 0,
                "raw_row_count": raw_row_count,
                "output_row_count": row_count,
                "output_columns": columns,
                "duplicate_removed_count": duplicate_removed_count,
                "duplicate_sample_rows": duplicate_sample_rows,
            }
            if log:
                log.stdout(
                    "silver_partition_written",
                    partition_key=partition_key,
                    trade_date=source_trade_date,
                    rows=row_count,
                    raw_rows=raw_row_count,
                    path=target_path,
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
    description="指数日线 raw 数据，按交易日从 prod core serving 只读同步 DG 管理的指数集合。",
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
    write_result = write_raw_index_daily_partition_from_prod_db(
        lake_root_path=lake_root.root(),
        duckdb=duckdb,
        prod_postgres=prod_postgres,
        partition_key=partition_key,
        index_codes=registered_index_codes,
        run_id=context.run_id,
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=write_result.raw_file_path,
            row_count=write_result.row_count,
            observed_columns=write_result.observed_columns,
            extra_metadata=write_result.materialization_extra_metadata(
                partition_key=partition_key,
            ),
        )
    )


@dg.asset(
    name="raw_tushare_index_daily_by_code",
    partitions_def=cn_a_index_ts_codes,
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="index_daily",
        source_system=SourceSystem.TUSHARE,
        source_api="index_daily",
        source_category_path="指数专题",
        source_doc="docs/sources/tushare/指数专题/0095_指数日线行情.md",
        data_contract="source_mirror_by_code",
        column_schema=RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA,
        path_template=lake_path_template(
            raw_index_daily_by_code_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
    ),
    description="Tushare 指数日线原始数据，按指数代码分区拉取并保存源站镜像。",
)
def raw_tushare_index_daily_by_code(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    config: IndexDailyRawByCodeConfig,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    ts_code = context.partition_key
    start_date, end_date = _source_date_window_from_config(config)
    target_path = raw_index_daily_by_code_path(lake_root.root(), ts_code)

    metadata = fetch_tushare_index_daily_by_code_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        fields=INDEX_DAILY_RAW_COLUMNS,
        column_types=INDEX_DAILY_RAW_COLUMN_TYPES,
        target_path=target_path,
        staging_dir=raw_index_daily_by_code_staging_dir(
            lake_root.root(),
            context.run_id,
            ts_code,
        ),
        write_mode=config.write_mode,
        log=DgStdoutLogger("index_daily"),
    )

    return dg.MaterializeResult(metadata=metadata)


@dg.asset(
    name="silver_index_daily",
    deps=[
        dg.AssetDep(
            raw_tushare_index_daily_by_code,
            partition_mapping=dg.AllPartitionMapping(),
        )
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
            "source_asset": "raw_tushare_index_daily_by_code",
            "source_partition_set": cn_a_index_ts_codes.name,
            "filter_policy": (
                "silver_index_daily reads registered cn_a_index_ts_codes raw-by-code files "
                "and filters rows by the current trade_date partition."
            ),
        },
    ),
    description="指数日线标准表，从按指数代码分区的 raw 文件集合按交易日生成。",
)
def silver_index_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_keys = _selected_partition_keys(context)
    registered_index_codes = _registered_index_ts_codes(context)
    partition_metadata = materialize_silver_index_daily_partitions_from_raw_by_code(
        lake_root_path=lake_root.root(),
        duckdb=duckdb,
        partition_keys=partition_keys,
        registered_index_codes=registered_index_codes,
        log=DgStdoutLogger("index_daily"),
    )

    total_row_count = sum(
        item["output_row_count"] for item in partition_metadata.values()
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            row_count=total_row_count,
            observed_columns=INDEX_DAILY_SILVER_COLUMNS,
            extra_metadata={
                "partition_keys": list(partition_keys),
                "partition_metadata": partition_metadata,
                "source_code_count": len(registered_index_codes),
            },
        )
    )
