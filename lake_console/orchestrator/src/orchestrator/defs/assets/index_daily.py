import os
from collections.abc import Sequence
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
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_index_daily_by_code_path,
    raw_index_daily_by_code_staging_dir,
    silver_index_daily_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.configs import (
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
        path_template=lake_path_template(
            raw_index_daily_by_code_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={"expected_source_columns": list(INDEX_DAILY_RAW_COLUMNS)},
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
        path_template=lake_path_template(
            silver_index_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "expected_columns": list(INDEX_DAILY_SILVER_COLUMNS),
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
            columns=INDEX_DAILY_SILVER_COLUMNS,
            extra_metadata={
                "partition_keys": list(partition_keys),
                "partition_metadata": partition_metadata,
                "source_code_count": len(registered_index_codes),
            },
        )
    )
