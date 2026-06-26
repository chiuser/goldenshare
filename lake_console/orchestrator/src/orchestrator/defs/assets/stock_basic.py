import os
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    STOCK_BASIC_RAW_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
    silver_stock_basic_select,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    lake_path_template,
    raw_stock_basic_path,
    silver_stock_basic_path,
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
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STOCK_BASIC_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_api_io import fetch_tushare_full_file_to_raw
from orchestrator.utils.dg_log_helper import DgStdoutLogger


STOCK_BASIC_API_PARAMS = {"list_status": "L,D,P,G"}
STOCK_BASIC_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_STOCK_BASIC_SCHEMA
}
LOGGER = DgStdoutLogger("basic_facts.stock_basic")


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


def _list_status_distribution(
    connection,
    path: Path,
    *,
    hive_partitioning: bool = False,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT list_status, count(*) AS row_count
        FROM {read_parquet(path, hive_partitioning=hive_partitioning)}
        GROUP BY list_status
        ORDER BY list_status
        """
    ).fetchall()
    return [
        {
            "list_status": row[0],
            "row_count": int(row[1]),
        }
        for row in rows
    ]


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


@dg.asset(
    name="raw_tushare_stock_basic",
    group_name="basic",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stock_basic",
        source_system=SourceSystem.TUSHARE,
        source_api="stock_basic",
        source_category_path="股票数据 / 基础数据",
        source_doc="docs/sources/tushare/股票数据/基础数据/0025_股票基础信息.md",
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_STOCK_BASIC_SCHEMA,
        path_template=lake_path_template(
            raw_stock_basic_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "raw_contract": (
                "Tushare stock_basic explicit fields; date fields remain YYYYMMDD strings."
            ),
            "update_policy": "daily_full_snapshot_api_update",
        },
    ),
    description=(
        "Tushare 股票基础信息 raw 源镜像，保留上市、退市、暂停和退市整理等全状态股票身份字段，"
        "供当前股票池和历史生命周期事实生成。"
    ),
)
def raw_tushare_stock_basic(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    path = raw_stock_basic_path(lake_root.root())
    LOGGER.stdout("stock_basic_raw_started", list_status=STOCK_BASIC_API_PARAMS["list_status"])
    metadata = fetch_tushare_full_file_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        api_name="stock_basic",
        api_params=STOCK_BASIC_API_PARAMS,
        fields=STOCK_BASIC_RAW_COLUMNS,
        column_types=STOCK_BASIC_RAW_COLUMN_TYPES,
        target_path=path,
        allow_empty=False,
    )

    with connect_configured_duckdb() as connection:
        list_status_distribution = _list_status_distribution(
            connection,
            path,
            hive_partitioning=False,
        )

    LOGGER.stdout(
        "stock_basic_raw_completed",
        row_count=metadata.get("dagster/row_count"),
    )
    return dg.MaterializeResult(
        metadata={
            **metadata,
            **build_materialization_metadata(
                extra_metadata={
                    "summary": "已写入 Tushare 股票基础信息 raw 全状态快照。",
                    "next_action": "等待 raw blocking checks 通过后生成当前股票池和历史生命周期事实。",
                    "result_status": "written",
                    "input_summary": "来源为 Tushare stock_basic，list_status=L,D,P,G。",
                    "filter_summary": "raw 层不做 current-listed 过滤，保留源站全状态股票身份。",
                    "diagnostic_ref": "完整诊断看 raw_stock_basic checks 和 run stdout。",
                    "list_status_distribution": list_status_distribution,
                }
            ),
        }
    )


@dg.asset(
    name="silver_stock_basic",
    deps=["raw_tushare_stock_basic"],
    group_name="basic",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stock_basic",
        source_system=SourceSystem.DERIVED,
        data_contract="current_listed_cny_stock_basic_lifecycle",
        column_schema=SILVER_STOCK_BASIC_SCHEMA,
        path_template=lake_path_template(
            silver_stock_basic_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "filter_policy": (
                "silver_stock_basic keeps only current list_status='L' and "
                "curr_type='CNY' stocks."
            )
        },
    ),
    description=(
        "当前上市 A 股股票基础信息 silver 标准事实，只保留 list_status='L' 且 curr_type='CNY' 的当前股票池，"
        "供日线、分钟线和市场统计链路作为当日基础股票池使用。"
    ),
)
def silver_stock_basic(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    raw_path = raw_stock_basic_path(lake_root.root())
    target_path = silver_stock_basic_path(lake_root.root())
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw stock basic file: {raw_path}")

    LOGGER.stdout("stock_basic_silver_started")
    with connect_configured_duckdb() as connection:
        source_row_count = _row_count(connection, raw_path, hive_partitioning=False)
        source_list_status_distribution = _list_status_distribution(
            connection,
            raw_path,
            hive_partitioning=False,
        )
        _replace_parquet_from_query(
            connection,
            silver_stock_basic_select(raw_path),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)
        list_status_distribution = _list_status_distribution(
            connection,
            target_path,
            hive_partitioning=False,
        )
    LOGGER.stdout(
        "stock_basic_silver_completed",
        source_row_count=source_row_count,
        row_count=row_count,
        filtered_out_row_count=source_row_count - row_count,
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            observed_columns=columns,
            extra_metadata={
                "summary": "已生成当前上市 CNY 股票基础信息 silver 快照。",
                "next_action": "等待 silver_stock_basic blocking checks 通过后供下游日频和分钟线资产消费。",
                "result_status": "written",
                "input_summary": "输入为 raw_tushare_stock_basic 全状态快照。",
                "filter_summary": (
                    f"保留当前上市 CNY 股票 {row_count} 行，过滤 "
                    f"{source_row_count - row_count} 行非当前上市或非 CNY 记录。"
                ),
                "diagnostic_ref": "完整诊断看 silver_stock_basic checks 和 run stdout。",
                "source_row_count": source_row_count,
                "kept_row_count": row_count,
                "filtered_out_row_count": source_row_count - row_count,
                "source_list_status_distribution": source_list_status_distribution,
                "list_status_distribution": list_status_distribution,
            },
        )
    )
