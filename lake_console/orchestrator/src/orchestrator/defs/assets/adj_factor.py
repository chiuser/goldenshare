import os
from dataclasses import dataclass
from pathlib import Path

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
    adj_factor_normalized_select,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    silver_cny_stock_lifecycle_select,
    silver_adj_factor_select,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
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
from orchestrator.defs.tushare_api_io import fetch_tushare_partition_to_raw


ADJ_FACTOR_COLUMNS = tuple(column.name for column in SILVER_ADJ_FACTOR_SCHEMA)

ADJ_FACTOR_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_ADJ_FACTOR_SCHEMA
}

ADJ_FACTOR_SILVER_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_ADJ_FACTOR_SCHEMA
}


@dataclass(frozen=True)
class SilverAdjFactorPartitionWriteResult:
    raw_file_path: Path
    stock_lifecycle_file_path: Path
    silver_file_path: Path
    source_row_count: int
    lifecycle_stock_count: int
    selected_row_count: int
    rejected_row_count: int
    row_count: int
    observed_columns: tuple[str, ...]

    def materialization_extra_metadata(self, partition_key: str) -> dict[str, object]:
        return {
            "raw_file_path": str(self.raw_file_path),
            "stock_lifecycle_file_path": str(self.stock_lifecycle_file_path),
            "partition_key": partition_key,
            "source_row_count": self.source_row_count,
            "lifecycle_stock_count": self.lifecycle_stock_count,
            "selected_row_count": self.selected_row_count,
            "rejected_row_count": self.rejected_row_count,
        }


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


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


def _silver_filter_counts(
    connection,
    raw_path: Path,
    stock_lifecycle_path: Path,
) -> dict[str, int]:
    normalized_sql = adj_factor_normalized_select(raw_path)
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        stock_lifecycle AS (
          {silver_cny_stock_lifecycle_select(stock_lifecycle_path)}
        ),
        selected AS (
          SELECT normalized.*
          FROM normalized
          INNER JOIN stock_lifecycle USING (ts_code)
          WHERE normalized.trade_date >= stock_lifecycle.list_date
            AND (
              stock_lifecycle.delist_date IS NULL
              OR normalized.trade_date <= stock_lifecycle.delist_date
            )
        )
        SELECT
          (SELECT count(*) FROM normalized) AS source_row_count,
          (SELECT count(*) FROM stock_lifecycle) AS lifecycle_stock_count,
          (SELECT count(*) FROM selected) AS selected_row_count,
          (SELECT count(*) FROM normalized) - (SELECT count(*) FROM selected)
            AS rejected_row_count
        """
    ).fetchone()
    return {
        "source_row_count": int(row[0]),
        "lifecycle_stock_count": int(row[1]),
        "selected_row_count": int(row[2]),
        "rejected_row_count": int(row[3]),
    }


def write_silver_adj_factor_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_key: str,
    overwrite: bool = False,
) -> SilverAdjFactorPartitionWriteResult:
    raw_path = raw_adj_factor_path(lake_root, partition_key)
    stock_lifecycle_path = silver_stock_lifecycle_path(lake_root)
    target_path = silver_adj_factor_path(lake_root, partition_key)
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw adj factor file: {raw_path}")
    if not stock_lifecycle_path.exists():
        raise FileNotFoundError(
            f"Missing silver stock lifecycle file: {stock_lifecycle_path}"
        )
    if target_path.exists() and not overwrite:
        raise FileExistsError(f"Silver adj factor file already exists: {target_path}")

    with connect_configured_duckdb() as connection:
        filter_counts = _silver_filter_counts(connection, raw_path, stock_lifecycle_path)
        _replace_parquet_from_query(
            connection,
            silver_adj_factor_select(raw_path, stock_lifecycle_path),
            target_path,
        )
        columns = tuple(
            _column_names(connection, target_path, hive_partitioning=False)
        )
        row_count = _row_count(connection, target_path, hive_partitioning=False)

    return SilverAdjFactorPartitionWriteResult(
        raw_file_path=raw_path,
        stock_lifecycle_file_path=stock_lifecycle_path,
        silver_file_path=target_path,
        source_row_count=filter_counts["source_row_count"],
        lifecycle_stock_count=filter_counts["lifecycle_stock_count"],
        selected_row_count=filter_counts["selected_row_count"],
        rejected_row_count=filter_counts["rejected_row_count"],
        row_count=row_count,
        observed_columns=columns,
    )


@dg.asset(
    name="raw_tushare_adj_factor",
    partitions_def=cn_a_stock_current_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="adj_factor",
        source_system=SourceSystem.TUSHARE,
        source_api="adj_factor",
        source_category_path="股票数据 / 行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0028_复权因子.md",
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
        path_template=lake_path_template(
            raw_adj_factor_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata={
            "raw_contract": (
                "Tushare adj_factor source mirror: trade_date is a YYYYMMDD string."
            ),
            "write_summary": (
                "Tushare API rows are written to raw parquet with explicit source "
                "contract fields."
            ),
        },
    ),
    description="Tushare 复权因子原始数据。",
)
def raw_tushare_adj_factor(
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
        api_name="adj_factor",
        api_params={"trade_date": partition_key.replace("-", "")},
        fields=ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
        column_types=ADJ_FACTOR_RAW_COLUMN_TYPES,
        target_path=raw_adj_factor_path(lake_root.root(), partition_key),
        partition_key=partition_key,
        allow_empty=False,
    )

    return dg.MaterializeResult(metadata=metadata)


@dg.asset(
    name="silver_adj_factor",
    deps=[raw_tushare_adj_factor, silver_stock_lifecycle],
    partitions_def=cn_a_stock_current_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="adj_factor",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_adj_factor",
        column_schema=SILVER_ADJ_FACTOR_SCHEMA,
        path_template=lake_path_template(
            silver_adj_factor_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "filter_policy": (
                "Keep lifecycle-valid CNY stocks on/after list_date and on/before "
                "delist_date when present; "
                "raw remains the Tushare source mirror."
            ),
            "upstream_ready_policy": (
                "silver_stock_lifecycle must exist before silver_adj_factor is "
                "produced; lifecycle is a read-only prerequisite."
            ),
        },
    ),
    description="复权因子标准表，按历史股票生命周期过滤。",
)
def silver_adj_factor(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    write_result = write_silver_adj_factor_partition(
        lake_root=lake_root.root(),
        duckdb=duckdb,
        partition_key=partition_key,
        overwrite=True,
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=write_result.silver_file_path,
            row_count=write_result.row_count,
            observed_columns=write_result.observed_columns,
            extra_metadata=write_result.materialization_extra_metadata(partition_key),
        )
    )
