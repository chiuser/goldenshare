import os
from pathlib import Path

import dagster as dg

from orchestrator.defs.corrections.suspend_full_day import (
    SUSPEND_FULL_DAY_PATCH_SOURCE,
    SUSPEND_FULL_DAY_PATCH_VERSION,
    SUSPEND_FULL_DAY_RAW_OVERRIDE_SOURCE,
    SUSPEND_FULL_DAY_RAW_OVERRIDE_VERSION,
    suspend_full_day_raw_override_samples,
    suspend_full_day_raw_overrides_values_sql,
    suspend_full_day_ranges_values_sql,
)
from orchestrator.defs.corrections.suspend_timing import (
    SUSPEND_TIMING_CORRECTION_VERSION,
    suspend_timing_correction_samples,
    suspend_timing_corrections_values_sql,
)
from orchestrator.defs.duckdb_sql import (
    SUSPEND_D_RAW_REQUIRED_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
    suspend_d_normalized_select,
    silver_stock_suspend_daily_select,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import raw_suspend_d_path, silver_stock_suspend_daily_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import build_dataset_metadata
from orchestrator.defs.tushare_api_io import fetch_tushare_partition_to_raw


SUSPEND_D_RAW_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "trade_date": "VARCHAR",
    "suspend_timing": "VARCHAR",
    "suspend_type": "VARCHAR",
}


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


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


def _suspend_timing_correction_count(connection, target_path: Path) -> int:
    return int(
        connection.execute(
            f"""
            WITH corrections(ts_code, trade_date, corrected_suspend_timing) AS (
              {suspend_timing_corrections_values_sql()}
            )
            SELECT count(*) AS correction_count
            FROM {read_parquet(target_path, hive_partitioning=False)} silver
            INNER JOIN corrections
              ON silver.ts_code = corrections.ts_code
             AND silver.trade_date = corrections.trade_date
             AND silver.suspend_timing = corrections.corrected_suspend_timing
            """
        ).fetchone()[0]
    )


def _full_day_patch_ctes(raw_path: Path, partition_key: str) -> str:
    return f"""
    WITH normalized AS (
      {suspend_d_normalized_select(raw_path)}
    ),
    full_day_patch_ranges(ts_code, name, start_date, end_date) AS (
      {suspend_full_day_ranges_values_sql()}
    ),
    full_day_raw_overrides(
      ts_code,
      name,
      trade_date,
      corrected_suspend_type,
      corrected_suspend_timing
    ) AS (
      {suspend_full_day_raw_overrides_values_sql()}
    ),
    full_day_patches AS (
      SELECT
        ts_code,
        name,
        DATE '{partition_key}' AS trade_date,
        NULL::VARCHAR AS suspend_timing,
        'S'::VARCHAR AS suspend_type
      FROM full_day_patch_ranges
      WHERE DATE '{partition_key}' BETWEEN start_date AND end_date
    )
    """


def _full_day_patch_conflict_rows(
    connection,
    raw_path: Path,
    partition_key: str,
) -> list[dict[str, str | None]]:
    rows = connection.execute(
        f"""
        {_full_day_patch_ctes(raw_path, partition_key)}
        SELECT
          full_day_patches.ts_code,
          full_day_patches.name,
          full_day_patches.trade_date,
          normalized.suspend_type AS raw_suspend_type,
          normalized.suspend_timing AS raw_suspend_timing
        FROM full_day_patches
        INNER JOIN normalized
          ON full_day_patches.ts_code = normalized.ts_code
         AND full_day_patches.trade_date = normalized.trade_date
        WHERE NOT (
          normalized.suspend_type = 'S'
          AND normalized.suspend_timing IS NULL
        )
          AND NOT EXISTS (
            SELECT 1
            FROM full_day_raw_overrides
            WHERE full_day_raw_overrides.ts_code = full_day_patches.ts_code
              AND full_day_raw_overrides.trade_date = full_day_patches.trade_date
          )
        ORDER BY full_day_patches.ts_code
        LIMIT 20
        """
    ).fetchall()
    return [
        {
            "ts_code": row[0],
            "name": row[1],
            "trade_date": row[2].isoformat() if hasattr(row[2], "isoformat") else row[2],
            "raw_suspend_type": row[3],
            "raw_suspend_timing": row[4],
        }
        for row in rows
    ]


def _full_day_patch_metadata(
    connection,
    raw_path: Path,
    partition_key: str,
) -> tuple[int, list[dict[str, str | None]]]:
    row = connection.execute(
        f"""
        {_full_day_patch_ctes(raw_path, partition_key)}
        SELECT count(*) AS patch_count
        FROM full_day_patches
        WHERE NOT EXISTS (
          SELECT 1
          FROM normalized
          WHERE normalized.ts_code = full_day_patches.ts_code
            AND normalized.trade_date = full_day_patches.trade_date
            AND normalized.suspend_type = 'S'
            AND normalized.suspend_timing IS NULL
        )
        """
    ).fetchone()
    sample_rows = connection.execute(
        f"""
        {_full_day_patch_ctes(raw_path, partition_key)}
        SELECT
          full_day_patches.ts_code,
          full_day_patches.name,
          full_day_patches.trade_date,
          full_day_patches.suspend_type,
          full_day_patches.suspend_timing
        FROM full_day_patches
        WHERE NOT EXISTS (
          SELECT 1
          FROM normalized
          WHERE normalized.ts_code = full_day_patches.ts_code
            AND normalized.trade_date = full_day_patches.trade_date
            AND normalized.suspend_type = 'S'
            AND normalized.suspend_timing IS NULL
        )
        ORDER BY full_day_patches.ts_code
        LIMIT 20
        """
    ).fetchall()
    samples = [
        {
            "ts_code": sample[0],
            "name": sample[1],
            "trade_date": sample[2].isoformat()
            if hasattr(sample[2], "isoformat")
            else sample[2],
            "suspend_type": sample[3],
            "suspend_timing": sample[4],
        }
        for sample in sample_rows
    ]
    return int(row[0]), samples


def _full_day_raw_override_metadata(
    connection,
    raw_path: Path,
    partition_key: str,
) -> tuple[int, int, list[dict[str, str | None]]]:
    row = connection.execute(
        f"""
        {_full_day_patch_ctes(raw_path, partition_key)}
        SELECT
          count(DISTINCT full_day_raw_overrides.ts_code) AS override_key_count,
          count(*) AS removed_raw_row_count
        FROM normalized
        INNER JOIN full_day_raw_overrides
          ON normalized.ts_code = full_day_raw_overrides.ts_code
         AND normalized.trade_date = full_day_raw_overrides.trade_date
        """
    ).fetchone()
    sample_rows = connection.execute(
        f"""
        {_full_day_patch_ctes(raw_path, partition_key)}
        SELECT
          full_day_raw_overrides.ts_code,
          full_day_raw_overrides.name,
          full_day_raw_overrides.trade_date,
          normalized.suspend_type AS raw_suspend_type,
          normalized.suspend_timing AS raw_suspend_timing,
          full_day_raw_overrides.corrected_suspend_type,
          full_day_raw_overrides.corrected_suspend_timing
        FROM normalized
        INNER JOIN full_day_raw_overrides
          ON normalized.ts_code = full_day_raw_overrides.ts_code
         AND normalized.trade_date = full_day_raw_overrides.trade_date
        ORDER BY full_day_raw_overrides.ts_code, normalized.suspend_type
        LIMIT 20
        """
    ).fetchall()
    samples = [
        {
            "ts_code": sample[0],
            "name": sample[1],
            "trade_date": sample[2].isoformat()
            if hasattr(sample[2], "isoformat")
            else sample[2],
            "raw_suspend_type": sample[3],
            "raw_suspend_timing": sample[4],
            "corrected_suspend_type": sample[5],
            "corrected_suspend_timing": sample[6],
        }
        for sample in sample_rows
    ]
    return int(row[0]), int(row[1]), samples


@dg.asset(
    name="raw_tushare_suspend_d",
    partitions_def=cn_a_stock_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_dataset_metadata(dataset_id="suspend_d"),
    description="Tushare 停复牌日频原始数据。",
)
def raw_tushare_suspend_d(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    metadata = fetch_tushare_partition_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        api_name="suspend_d",
        api_params={"trade_date": partition_key.replace("-", "")},
        fields=SUSPEND_D_RAW_REQUIRED_COLUMNS,
        column_types=SUSPEND_D_RAW_COLUMN_TYPES,
        target_path=raw_suspend_d_path(lake_root.root(), partition_key),
        partition_key=partition_key,
        allow_empty=True,
    )

    return dg.MaterializeResult(
        metadata={
            **metadata,
            "layer": "raw",
            "source_api": "suspend_d",
            "data_contract": "source_mirror",
            "raw_contract": (
                "Tushare suspend_d source mirror: trade_date YYYYMMDD string, "
                "suspend_timing nullable string."
            ),
            "required_columns": list(SUSPEND_D_RAW_REQUIRED_COLUMNS),
            "write_summary": "Tushare API rows written to raw parquet with explicit source contract fields.",
        }
    )


@dg.asset(
    name="silver_stock_suspend_daily",
    deps=[raw_tushare_suspend_d],
    partitions_def=cn_a_stock_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_dataset_metadata(dataset_id="suspend_d"),
    description="股票日频停复牌标准表，记录停牌类型和时段。",
)
def silver_stock_suspend_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    raw_path = raw_suspend_d_path(lake_root.root(), partition_key)
    target_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw suspend_d file: {raw_path}")

    with duckdb.connect() as connection:
        full_day_patch_conflict_rows = _full_day_patch_conflict_rows(
            connection,
            raw_path,
            partition_key,
        )
        if full_day_patch_conflict_rows:
            raise dg.Failure(
                description=(
                    "Full-day suspend patch conflicts with existing raw suspend_d rows."
                ),
                metadata={
                    "raw_path": str(raw_path),
                    "partition_key": partition_key,
                    "full_day_suspend_patch_conflict_count": len(
                        full_day_patch_conflict_rows
                    ),
                    "full_day_suspend_patch_conflict_sample_rows": (
                        full_day_patch_conflict_rows
                    ),
                },
            )

        full_day_patch_count, full_day_patch_sample_rows = _full_day_patch_metadata(
            connection,
            raw_path,
            partition_key,
        )
        (
            full_day_raw_override_key_count,
            full_day_raw_override_removed_row_count,
            full_day_raw_override_sample_rows,
        ) = _full_day_raw_override_metadata(
            connection,
            raw_path,
            partition_key,
        )
        _replace_parquet_from_query(
            connection,
            silver_stock_suspend_daily_select(raw_path, partition_key),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)
        correction_count = _suspend_timing_correction_count(connection, target_path)

    return dg.MaterializeResult(
        metadata={
            "path": str(target_path),
            "raw_path": str(raw_path),
            "row_count": row_count,
            "columns": columns,
            "partition_key": partition_key,
            "layer": "silver",
            "data_contract": "standardized_stock_suspend_daily",
            "suspend_timing_correction_count": correction_count,
            "suspend_timing_correction_version": SUSPEND_TIMING_CORRECTION_VERSION,
            "suspend_timing_correction_sample_rows": suspend_timing_correction_samples(),
            "full_day_suspend_patch_count": full_day_patch_count,
            "full_day_suspend_patch_rule_version": SUSPEND_FULL_DAY_PATCH_VERSION,
            "full_day_suspend_patch_source": SUSPEND_FULL_DAY_PATCH_SOURCE,
            "full_day_suspend_patch_sample_rows": full_day_patch_sample_rows,
            "full_day_suspend_patch_conflict_count": 0,
            "full_day_suspend_raw_override_key_count": full_day_raw_override_key_count,
            "full_day_suspend_raw_override_removed_row_count": (
                full_day_raw_override_removed_row_count
            ),
            "full_day_suspend_raw_override_rule_version": (
                SUSPEND_FULL_DAY_RAW_OVERRIDE_VERSION
            ),
            "full_day_suspend_raw_override_source": SUSPEND_FULL_DAY_RAW_OVERRIDE_SOURCE,
            "full_day_suspend_raw_override_sample_rows": (
                full_day_raw_override_sample_rows
            ),
            "full_day_suspend_raw_override_rule_sample_rows": (
                suspend_full_day_raw_override_samples()
            ),
        }
    )
