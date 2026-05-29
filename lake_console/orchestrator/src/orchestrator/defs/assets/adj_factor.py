import os
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
    adj_factor_normalized_select,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
    silver_adj_factor_select,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_basic_path,
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


def _silver_filter_counts(connection, raw_path: Path, basic_path: Path) -> dict[str, int]:
    normalized_sql = adj_factor_normalized_select(raw_path)
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        current_listed AS (
          SELECT DISTINCT ts_code, list_date
          FROM {read_parquet(basic_path, hive_partitioning=False)}
          WHERE list_status = 'L'
        ),
        selected AS (
          SELECT normalized.*
          FROM normalized
          INNER JOIN current_listed USING (ts_code)
          WHERE normalized.trade_date >= current_listed.list_date
        )
        SELECT
          (SELECT count(*) FROM normalized) AS source_row_count,
          (SELECT count(*) FROM current_listed) AS current_listed_stock_count,
          (SELECT count(*) FROM selected) AS selected_row_count,
          (SELECT count(*) FROM normalized) - (SELECT count(*) FROM selected)
            AS rejected_row_count
        """
    ).fetchone()
    return {
        "source_row_count": int(row[0]),
        "current_listed_stock_count": int(row[1]),
        "selected_row_count": int(row[2]),
        "rejected_row_count": int(row[3]),
    }


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
    deps=[raw_tushare_adj_factor, silver_stock_basic],
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
                "Keep current listed stocks only and keep rows on/after list_date; "
                "raw remains the Tushare source mirror."
            ),
            "upstream_ready_policy": (
                "silver_stock_basic must exist before silver_adj_factor is produced; "
                "stock basic is a read-only prerequisite."
            ),
        },
    ),
    description="复权因子标准表，按当前上市股票和上市日期过滤。",
)
def silver_adj_factor(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    raw_path = raw_adj_factor_path(lake_root.root(), partition_key)
    basic_path = silver_stock_basic_path(lake_root.root())
    target_path = silver_adj_factor_path(lake_root.root(), partition_key)
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw adj factor file: {raw_path}")
    if not basic_path.exists():
        raise FileNotFoundError(f"Missing silver stock basic file: {basic_path}")

    with duckdb.connect() as connection:
        filter_counts = _silver_filter_counts(connection, raw_path, basic_path)
        _replace_parquet_from_query(
            connection,
            silver_adj_factor_select(raw_path, basic_path),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            observed_columns=columns,
            extra_metadata={
                "raw_file_path": str(raw_path),
                "stock_basic_file_path": str(basic_path),
                "partition_key": partition_key,
                **filter_counts,
            },
        )
    )
