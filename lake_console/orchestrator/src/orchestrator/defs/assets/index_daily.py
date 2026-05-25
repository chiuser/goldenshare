import os
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import dagster as dg

from orchestrator.defs.assets.index_daily_active_pool import silver_index_daily_active_pool
from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_RAW_COLUMNS,
    INDEX_DAILY_SILVER_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    index_daily_normalized_select,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import (
    raw_index_daily_by_code_path,
    raw_index_daily_by_code_staging_dir,
    raw_index_daily_path,
    raw_index_daily_staging_dir,
    silver_index_daily_active_pool_path,
    silver_index_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResource
from orchestrator.defs.tushare_api_io import (
    fetch_tushare_index_daily_by_code_to_raw,
    fetch_tushare_index_daily_to_raw_partitions,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


INDEX_DAILY_RAW_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "trade_date": "VARCHAR",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "pre_close": "DOUBLE",
    "change": "DOUBLE",
    "pct_chg": "DOUBLE",
    "vol": "DOUBLE",
    "amount": "DOUBLE",
}

INDEX_DAILY_SILVER_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "trade_date": "DATE",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "pre_close": "DOUBLE",
    "change_amount": "DOUBLE",
    "pct_chg": "DOUBLE",
    "vol": "DOUBLE",
    "amount": "DOUBLE",
}


class IndexDailyRawByCodeConfig(dg.Config):
    start_date: str
    end_date: str
    write_mode: Literal["replace"]


def _source_date_from_config(value: str, field_name: str) -> str:
    stripped = value.strip()
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from error

    if parsed < datetime.strptime("2000-01-01", "%Y-%m-%d").date():
        raise ValueError(f"{field_name} must not be earlier than 2000-01-01.")
    return parsed.strftime("%Y%m%d")


def _source_date_window_from_config(config: IndexDailyRawByCodeConfig) -> tuple[str, str]:
    start_date = _source_date_from_config(config.start_date, "start_date")
    end_date = _source_date_from_config(config.end_date, "end_date")
    if start_date > end_date:
        raise ValueError("start_date must be earlier than or equal to end_date.")
    return start_date, end_date


def _selected_partition_keys(context: dg.AssetExecutionContext) -> tuple[str, ...]:
    return tuple(sorted(set(context.partition_keys)))


def _column_names(connection, path: Path, *, hive_partitioning: bool = False) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(count_parquet_query(path, hive_partitioning=hive_partitioning)).fetchone()[
            0
        ]
    )


def _sample_dicts(columns: list[str], rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def load_active_index_entries(connection, active_pool_path: Path) -> list[dict[str, str]]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT
          ts_code,
          COALESCE(NULLIF(trim(display_name), ''), '-') AS name
        FROM {read_parquet(active_pool_path, hive_partitioning=False)}
        WHERE ts_code IS NOT NULL AND trim(ts_code) != ''
        ORDER BY ts_code
        """
    ).fetchall()
    return [
        {
            "ts_code": str(row[0]),
            "name": str(row[1]) if row[1] is not None else "-",
        }
        for row in rows
    ]


def load_active_index_codes(connection, active_pool_path: Path) -> list[str]:
    return [
        active_index_entry["ts_code"]
        for active_index_entry in load_active_index_entries(connection, active_pool_path)
    ]


def _conflict_key_count(connection, raw_path: Path) -> int:
    normalized_sql = index_daily_normalized_select(raw_path)
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


def _conflict_sample_keys(connection, raw_path: Path) -> list[dict[str, Any]]:
    normalized_sql = index_daily_normalized_select(raw_path)
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


def _duplicate_removed_count(connection, raw_path: Path) -> int:
    normalized_sql = index_daily_normalized_select(raw_path)
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


def _duplicate_sample_rows(connection, raw_path: Path) -> list[dict[str, Any]]:
    normalized_sql = index_daily_normalized_select(raw_path)
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


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


def _registered_index_ts_codes(context: dg.AssetExecutionContext) -> tuple[str, ...]:
    codes = tuple(sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name)))
    if not codes:
        raise RuntimeError(f"{cn_a_index_ts_codes.name} has no registered partition keys.")
    return codes


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


def _duplicate_removed_count_from_normalized_sql(connection, normalized_sql: str) -> int:
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
        raise RuntimeError(f"{cn_a_index_ts_codes.name} has no registered partition keys.")

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
    with duckdb.connect() as connection:
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
                connection.execute(f"SELECT count(*) FROM ({normalized_sql}) normalized").fetchone()[
                    0
                ]
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
                "path": str(target_path),
                "source_code_count": len(index_codes),
                "source_file_count": len(raw_paths),
                "missing_raw_file_count": 0,
                "raw_row_count": raw_row_count,
                "row_count": row_count,
                "columns": columns,
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
            total_rows=sum(item["row_count"] for item in partition_metadata.values()),
        )

    return partition_metadata


def materialize_silver_index_daily_partitions(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    partition_keys: Sequence[str],
    log: DgStdoutLogger | None = None,
) -> dict[str, dict[str, Any]]:
    active_pool_path = silver_index_daily_active_pool_path(lake_root_path)
    if not active_pool_path.exists():
        raise FileNotFoundError(f"Missing silver index daily active pool file: {active_pool_path}")

    partition_metadata: dict[str, dict[str, Any]] = {}
    with duckdb.connect() as connection:
        active_pool_count = len(load_active_index_codes(connection, active_pool_path))
        for partition_key in tuple(sorted(set(partition_keys))):
            raw_path = raw_index_daily_path(lake_root_path, partition_key)
            target_path = silver_index_daily_path(lake_root_path, partition_key)
            if not raw_path.exists():
                raise FileNotFoundError(f"Missing raw index daily file: {raw_path}")

            conflict_key_count = _conflict_key_count(connection, raw_path)
            if conflict_key_count:
                raise RuntimeError(
                    "raw_tushare_index_daily has conflicting duplicate rows for "
                    f"{partition_key}: {_conflict_sample_keys(connection, raw_path)}"
                )

            raw_row_count = _row_count(connection, raw_path)
            duplicate_removed_count = _duplicate_removed_count(connection, raw_path)
            duplicate_sample_rows = _duplicate_sample_rows(connection, raw_path)
            _replace_parquet_from_query(
                connection,
                silver_index_daily_select(raw_path, active_pool_path),
                target_path,
            )
            columns = _column_names(connection, target_path)
            row_count = _row_count(connection, target_path)
            missing_active_count = max(active_pool_count - row_count, 0)
            coverage_rate = round(row_count * 100.0 / active_pool_count, 4) if active_pool_count else 0.0
            partition_metadata[partition_key] = {
                "path": str(target_path),
                "raw_path": str(raw_path),
                "row_count": row_count,
                "raw_row_count": raw_row_count,
                "active_pool_count": active_pool_count,
                "missing_active_count": missing_active_count,
                "coverage_rate": coverage_rate,
                "columns": columns,
                "duplicate_removed_count": duplicate_removed_count,
                "duplicate_sample_rows": duplicate_sample_rows,
            }
            if log:
                log.stdout(
                    "silver_partition_written",
                    partition_key=partition_key,
                    trade_date=partition_key.replace("-", ""),
                    rows=row_count,
                    raw_rows=raw_row_count,
                    path=target_path,
                )

    if log:
        log.stdout(
            "silver_partitions_completed",
            partitions=len(partition_metadata),
            total_rows=sum(item["row_count"] for item in partition_metadata.values()),
        )

    return partition_metadata


@dg.asset(
    name="raw_tushare_index_daily_by_code",
    partitions_def=cn_a_index_ts_codes,
    group_name="index",
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
    )

    return dg.MaterializeResult(
        metadata={
            **metadata,
            "layer": "raw",
            "source_api": "index_daily",
            "data_contract": "source_mirror_by_code",
            "expected_source_columns": list(INDEX_DAILY_RAW_COLUMNS),
        }
    )


@dg.asset(
    name="raw_tushare_index_daily",
    deps=[silver_index_daily_active_pool],
    partitions_def=cn_a_index_trade_days,
    group_name="index",
    description="Tushare 指数日线原始数据，按有效指数池拉取。",
)
def raw_tushare_index_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_keys = _selected_partition_keys(context)
    active_pool_path = silver_index_daily_active_pool_path(lake_root.root())
    if not active_pool_path.exists():
        raise FileNotFoundError(f"Missing silver index daily active pool file: {active_pool_path}")

    with duckdb.connect() as connection:
        active_index_entries = load_active_index_entries(connection, active_pool_path)

    target_paths = {
        partition_key: raw_index_daily_path(lake_root.root(), partition_key)
        for partition_key in partition_keys
    }
    log = DgStdoutLogger("index_daily")
    metadata = fetch_tushare_index_daily_to_raw_partitions(
        tushare=tushare,
        duckdb=duckdb,
        active_index_entries=active_index_entries,
        partition_keys=partition_keys,
        fields=INDEX_DAILY_RAW_COLUMNS,
        column_types=INDEX_DAILY_RAW_COLUMN_TYPES,
        target_paths=target_paths,
        staging_dir=raw_index_daily_staging_dir(lake_root.root(), context.run_id),
        log=log,
    )

    return dg.MaterializeResult(
        metadata={
            **metadata,
            "layer": "raw",
            "source_api": "index_daily",
            "data_contract": "active_pool_source_mirror",
            "expected_source_columns": list(INDEX_DAILY_RAW_COLUMNS),
            "request_scope": "silver_index_daily_active_pool",
        }
    )


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

    total_row_count = sum(item["row_count"] for item in partition_metadata.values())
    return dg.MaterializeResult(
        metadata={
            "layer": "silver",
            "data_contract": "active_index_daily",
            "partition_keys": list(partition_keys),
            "row_count": total_row_count,
            "partition_metadata": partition_metadata,
            "expected_columns": list(INDEX_DAILY_SILVER_COLUMNS),
            "source_asset": "raw_tushare_index_daily_by_code",
            "source_partition_set": cn_a_index_ts_codes.name,
            "source_code_count": len(registered_index_codes),
            "filter_policy": (
                "silver_index_daily reads registered cn_a_index_ts_codes raw-by-code files "
                "and filters rows by the current trade_date partition."
            ),
        }
    )
