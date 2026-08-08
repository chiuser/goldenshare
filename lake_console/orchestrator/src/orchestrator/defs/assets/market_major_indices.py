import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.index_daily import (
    INDEX_DAILY_SILVER_COLUMNS,
    silver_index_daily,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_market_major_indices_daily_path,
    lake_path_template,
    silver_index_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.seeds.market.major_indices import (
    MAJOR_INDICES_SEED_COLUMNS,
    active_major_indices_seed_rows,
    load_major_indices_seed,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger

MARKET_MAJOR_INDICES_DAILY_COLUMNS = tuple(
    column.name for column in GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA
)

MARKET_MAJOR_INDICES_DAILY_COLUMN_TYPES = {
    column.name: column.type for column in GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA
}


def _selected_partition_keys(context: dg.AssetExecutionContext) -> tuple[str, ...]:
    return tuple(sorted(set(context.partition_keys)))


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]
    )


def _sample_dicts(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
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


def create_major_indices_seed_table(
    connection, table_name: str = "major_indices_seed"
) -> int:
    rows = load_major_indices_seed()
    connection.execute(
        f"""
        CREATE TEMP TABLE {table_name} (
          rank INTEGER,
          ts_code VARCHAR,
          display_name VARCHAR,
          effective_start_date DATE,
          effective_end_date DATE
        )
        """
    )
    connection.executemany(
        f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?)",
        [
            (
                row.rank,
                row.ts_code,
                row.display_name,
                row.effective_start_date,
                row.effective_end_date,
            )
            for row in rows
        ],
    )
    return len(rows)


def write_gold_market_major_indices_daily_partition(
    connection,
    *,
    seed_table_name: str,
    seed_count: int,
    silver_path: Path,
    target_path: Path,
    partition_key: str,
) -> dict[str, Any]:
    """Write one Gold partition using the same contract as the formal asset."""

    active_seed_rows = active_major_indices_seed_rows(partition_key)
    if not silver_path.exists():
        raise FileNotFoundError(
            "Missing silver_index_daily partition before generating major indices: "
            f"{silver_path}"
        )
    missing_count, missing_samples = _missing_seed_codes_in_silver(
        connection,
        seed_table_name=seed_table_name,
        silver_path=silver_path,
        partition_key=partition_key,
    )
    if missing_count:
        raise RuntimeError(
            "silver_index_daily is missing major index rows for "
            f"{partition_key}: {missing_samples}"
        )
    _replace_parquet_from_query(
        connection,
        _major_indices_daily_select_sql(
            seed_table_name=seed_table_name,
            silver_path=silver_path,
            partition_key=partition_key,
        ),
        target_path,
    )
    return {
        "partition_key": partition_key,
        "file_path": str(target_path),
        "output_row_count": _row_count(connection, target_path),
        "output_columns": _column_names(connection, target_path),
        "seed_row_count": seed_count,
        "active_seed_row_count": len(active_seed_rows),
        "inactive_seed_row_count": seed_count - len(active_seed_rows),
        "active_seed_codes": [row.ts_code for row in active_seed_rows],
        "seed_columns": list(MAJOR_INDICES_SEED_COLUMNS),
        "source_asset": "silver_index_daily",
        "source_file_path": str(silver_path),
    }


def _active_seed_filter_sql(partition_key: str, *, seed_alias: str = "seed") -> str:
    trade_date_sql = f"DATE {duckdb_string(partition_key)}"
    return f"""
    {seed_alias}.effective_start_date <= {trade_date_sql}
    AND (
      {seed_alias}.effective_end_date IS NULL
      OR {trade_date_sql} <= {seed_alias}.effective_end_date
    )
    """


def _major_indices_daily_select_sql(
    *,
    seed_table_name: str,
    silver_path: Path,
    partition_key: str,
) -> str:
    silver_columns = set(INDEX_DAILY_SILVER_COLUMNS)
    required_silver_columns = {
        "trade_date",
        "ts_code",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change_amount",
        "pct_chg",
        "vol",
        "amount",
    }
    missing_silver_columns = sorted(required_silver_columns - silver_columns)
    if missing_silver_columns:
        raise RuntimeError(
            f"INDEX_DAILY_SILVER_COLUMNS missing: {missing_silver_columns}"
        )

    return f"""
    SELECT
      CAST(silver.trade_date AS DATE) AS trade_date,
      CAST(seed.rank AS INTEGER) AS rank,
      CAST(seed.ts_code AS VARCHAR) AS ts_code,
      CAST(seed.display_name AS VARCHAR) AS display_name,
      CAST(silver.open AS DOUBLE) AS open,
      CAST(silver.high AS DOUBLE) AS high,
      CAST(silver.low AS DOUBLE) AS low,
      CAST(silver.close AS DOUBLE) AS close,
      CAST(silver.pre_close AS DOUBLE) AS pre_close,
      CAST(silver.change_amount AS DOUBLE) AS change_amount,
      CAST(silver.pct_chg AS DOUBLE) AS pct_chg,
      CAST(silver.vol AS DOUBLE) AS vol,
      CAST(silver.amount AS DOUBLE) AS amount
    FROM {seed_table_name} seed
    INNER JOIN {read_parquet(silver_path, hive_partitioning=False)} silver
      ON seed.ts_code = silver.ts_code
     AND silver.trade_date = DATE {duckdb_string(partition_key)}
    WHERE {_active_seed_filter_sql(partition_key)}
    ORDER BY seed.rank
    """


def _missing_seed_codes_in_silver(
    connection,
    *,
    seed_table_name: str,
    silver_path: Path,
    partition_key: str,
) -> tuple[int, list[dict[str, Any]]]:
    missing_sql = f"""
    SELECT seed.rank, seed.ts_code, seed.display_name
    FROM {seed_table_name} seed
    LEFT JOIN {read_parquet(silver_path, hive_partitioning=False)} silver
      ON seed.ts_code = silver.ts_code
     AND silver.trade_date = DATE {duckdb_string(partition_key)}
    WHERE {_active_seed_filter_sql(partition_key)}
      AND silver.ts_code IS NULL
    """
    missing_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({missing_sql}) missing_codes"
        ).fetchone()[0]
    )
    rows = connection.execute(
        f"""
        {missing_sql}
        ORDER BY rank, ts_code
        LIMIT 20
        """
    ).fetchall()
    return missing_count, _sample_dicts(["rank", "ts_code", "display_name"], rows)


def _human_materialization_metadata(
    *,
    partition_keys: tuple[str, ...],
    partition_metadata: dict[str, dict[str, Any]],
    seed_count: int,
    total_row_count: int,
) -> dict[str, Any]:
    active_seed_row_counts = {
        partition_key: metadata["active_seed_row_count"]
        for partition_key, metadata in partition_metadata.items()
    }
    return {
        "summary": "已生成主要指数日线 gold 分区，供首页和市场概览展示主要指数行情。",
        "next_action": "等待 gold_market_major_indices_daily blocking checks 全部通过；通过后 serving 和前端展示链路可以消费。",
        "result_status": "written",
        "input_summary": {
            "source_asset": "silver_index_daily",
            "seed_source": "orchestrator.seeds.market.major_indices",
            "partition_count": len(partition_keys),
            "seed_row_count": seed_count,
        },
        "metric_summary": {
            "output_row_count": total_row_count,
            "active_seed_row_counts": active_seed_row_counts,
        },
        "diagnostic_ref": "完整诊断看 gold_market_major_indices_daily checks、partition_metadata 和 run stdout。",
    }


@dg.asset(
    name="gold_market_major_indices_daily",
    deps=[silver_index_daily],
    partitions_def=cn_a_index_trade_days,
    group_name="market",
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="market_major_indices_daily",
        source_system=SourceSystem.DERIVED,
        data_contract="market_major_indices_daily",
        path_template=lake_path_template(
            gold_market_major_indices_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        column_schema=GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
        extra_metadata={
            "source_asset": "silver_index_daily",
            "seed_source": "orchestrator.seeds.market.major_indices",
            "seed_columns": list(MAJOR_INDICES_SEED_COLUMNS),
        },
    ),
    description="主要指数日线 gold 展示事实，按交易日读取版本化主要指数 seed 和 silver_index_daily 行情，供首页与市场概览消费。",
)
def gold_market_major_indices_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_keys = _selected_partition_keys(context)
    partition_metadata: dict[str, dict[str, Any]] = {}
    seed_count = 0
    log = DgStdoutLogger("market_major_indices")
    log.stdout(
        "gold_market_major_indices_started",
        partition_count=len(partition_keys),
        first_partition=partition_keys[0] if partition_keys else None,
        last_partition=partition_keys[-1] if partition_keys else None,
    )

    with connect_configured_duckdb() as connection:
        seed_count = create_major_indices_seed_table(connection)
        for partition_key in partition_keys:
            silver_path = silver_index_daily_path(lake_root.root(), partition_key)
            target_path = gold_market_major_indices_daily_path(
                lake_root.root(), partition_key
            )
            partition_metadata[partition_key] = (
                write_gold_market_major_indices_daily_partition(
                    connection,
                    seed_table_name="major_indices_seed",
                    seed_count=seed_count,
                    silver_path=silver_path,
                    target_path=target_path,
                    partition_key=partition_key,
                )
            )

    total_row_count = sum(
        item["output_row_count"] for item in partition_metadata.values()
    )
    log.stdout(
        "gold_market_major_indices_completed",
        partition_count=len(partition_metadata),
        output_row_count=total_row_count,
        seed_row_count=seed_count,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            row_count=total_row_count,
            observed_columns=(
                next(iter(partition_metadata.values()))["output_columns"]
                if partition_metadata
                else ()
            ),
            extra_metadata={
                **_human_materialization_metadata(
                    partition_keys=partition_keys,
                    partition_metadata=partition_metadata,
                    seed_count=seed_count,
                    total_row_count=total_row_count,
                ),
                "partition_keys": list(partition_keys),
                "partition_metadata": partition_metadata,
            },
        )
    )
