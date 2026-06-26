import os
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
    silver_stock_lifecycle_select,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    lake_path_template,
    raw_stock_basic_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_LIFECYCLE_SCHEMA,
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
from orchestrator.utils.dg_log_helper import DgStdoutLogger


LOGGER = DgStdoutLogger("basic_facts.stock_lifecycle")


def _column_names(
    connection,
    path: Path,
    *,
    hive_partitioning: bool = False,
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
    name="silver_stock_lifecycle",
    deps=["raw_tushare_stock_basic"],
    group_name="basic",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stock_lifecycle",
        source_system=SourceSystem.DERIVED,
        data_contract="historical_cny_stock_lifecycle",
        column_schema=SILVER_STOCK_LIFECYCLE_SCHEMA,
        path_template=lake_path_template(
            silver_stock_lifecycle_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "filter_policy": (
                "silver_stock_lifecycle keeps historical CNY stock lifecycle "
                "facts from raw_tushare_stock_basic, including delisted stocks."
            )
        },
    ),
    description=(
        "历史 A 股股票生命周期 silver 标准事实，保留 CNY 股票从上市到退市的生命周期，"
        "供历史行情覆盖、退市股票校验和下游日期口径使用。"
    ),
)
def silver_stock_lifecycle(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    duckdb_resource = duckdb
    raw_path = raw_stock_basic_path(lake_root.root())
    target_path = silver_stock_lifecycle_path(lake_root.root())
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw stock basic file: {raw_path}")

    LOGGER.stdout("stock_lifecycle_started")
    with duckdb_resource.connect() as connection:
        source_row_count = _row_count(connection, raw_path, hive_partitioning=False)
        source_list_status_distribution = _list_status_distribution(
            connection,
            raw_path,
            hive_partitioning=False,
        )
        _replace_parquet_from_query(
            connection,
            silver_stock_lifecycle_select(raw_path),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)
        cny_stock_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS cny_stock_count
                FROM {read_parquet(target_path, hive_partitioning=False)}
                WHERE is_cny_stock
                """
            ).fetchone()[0]
        )
        list_status_distribution = _list_status_distribution(
            connection,
            target_path,
            hive_partitioning=False,
        )
    LOGGER.stdout(
        "stock_lifecycle_completed",
        source_row_count=source_row_count,
        row_count=row_count,
        cny_stock_count=cny_stock_count,
        filtered_out_row_count=source_row_count - row_count,
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            observed_columns=columns,
            extra_metadata={
                "summary": "已生成历史 CNY 股票生命周期事实，包含当前和已退市股票。",
                "next_action": "等待 silver_stock_lifecycle blocking checks 通过后供历史行情和覆盖率校验使用。",
                "result_status": "written",
                "input_summary": "输入为 raw_tushare_stock_basic 全状态快照。",
                "filter_summary": (
                    f"保留历史 CNY 股票 {row_count} 行，其中 is_cny_stock=true "
                    f"{cny_stock_count} 行；过滤 {source_row_count - row_count} 行。"
                ),
                "diagnostic_ref": "完整诊断看 silver_stock_lifecycle checks 和 run stdout。",
                "source_row_count": source_row_count,
                "cny_stock_count": cny_stock_count,
                "filtered_out_row_count": source_row_count - row_count,
                "source_list_status_distribution": source_list_status_distribution,
                "list_status_distribution": list_status_distribution,
            },
        )
    )
