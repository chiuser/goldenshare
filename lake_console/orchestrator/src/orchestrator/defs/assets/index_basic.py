import os
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    INDEX_BASIC_RAW_COLUMNS,
    INDEX_BASIC_SILVER_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
    silver_index_basic_select,
)
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import raw_index_basic_path, silver_index_basic_path
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
from orchestrator.defs.run_contracts.metadata import (
    READY_FOR_TRADE_DATE_METADATA_KEY,
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_api_io import fetch_tushare_full_file_to_raw


INDEX_BASIC_RAW_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "name": "VARCHAR",
    "fullname": "VARCHAR",
    "market": "VARCHAR",
    "publisher": "VARCHAR",
    "index_type": "VARCHAR",
    "category": "VARCHAR",
    "base_date": "VARCHAR",
    "base_point": "DOUBLE",
    "list_date": "VARCHAR",
    "weight_rule": "VARCHAR",
    "desc": "VARCHAR",
    "exp_date": "VARCHAR",
}

CN_A_TIMEZONE = ZoneInfo("Asia/Shanghai")


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


def _market_distribution(connection, path: Path) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT market, count(*) AS row_count
        FROM {read_parquet(path, hive_partitioning=False)}
        GROUP BY market
        ORDER BY market
        """
    ).fetchall()
    return [{"market": row[0], "row_count": int(row[1])} for row in rows]


def _raw_terminated_index_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            f"""
            SELECT count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exp_date IS NOT NULL AND trim(CAST(exp_date AS VARCHAR)) != ''
            """
        ).fetchone()[0]
    )


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    pending_parquet_path = target_path.with_name(f"{target_path.name}.tmp")
    if pending_parquet_path.exists():
        pending_parquet_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, pending_parquet_path))
    os.replace(pending_parquet_path, target_path)


def _latest_registered_index_trade_date(
    registered_trade_days: Sequence[str],
    today: str,
) -> str | None:
    eligible_trade_days = tuple(
        trade_date
        for trade_date in sorted(set(registered_trade_days))
        if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _resolve_ready_for_trade_date(context: dg.AssetExecutionContext) -> str:
    today = datetime.now(CN_A_TIMEZONE).date().isoformat()
    registered_trade_days = tuple(
        context.instance.get_dynamic_partitions(cn_a_index_trade_days.name)
    )
    ready_for_trade_date = _latest_registered_index_trade_date(
        registered_trade_days,
        today,
    )
    if ready_for_trade_date:
        return ready_for_trade_date

    raise RuntimeError(
        "silver_index_basic cannot resolve ready_for_trade_date: "
        f"{cn_a_index_trade_days.name} has no registered trade date on or before "
        f"{today}. Run index_trade_day_sensor first or register index trade day "
        "partitions."
    )


@dg.asset(
    name="raw_tushare_index_basic",
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="index_basic",
        source_system=SourceSystem.TUSHARE,
        source_api="index_basic",
        source_category_path="指数专题",
        source_doc="docs/sources/tushare/指数专题/0094_指数基本信息.md",
        data_contract="source_mirror",
        path_template="data_lake/raw/tushare/index_basic/full/part-000.parquet",
        extra_metadata={
            "expected_source_columns": list(INDEX_BASIC_RAW_COLUMNS),
            "update_policy": "daily_full_snapshot_api_update",
        },
    ),
    description="Tushare 指数基础信息原始数据。",
)
def raw_tushare_index_basic(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    path = raw_index_basic_path(lake_root.root())
    metadata = fetch_tushare_full_file_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        api_name="index_basic",
        api_params={},
        fields=INDEX_BASIC_RAW_COLUMNS,
        column_types=INDEX_BASIC_RAW_COLUMN_TYPES,
        target_path=path,
        allow_empty=False,
    )

    with duckdb.connect() as connection:
        market_distribution = _market_distribution(connection, path)
        terminated_index_count = _raw_terminated_index_count(connection, path)

    return dg.MaterializeResult(
        metadata={
            **metadata,
            **build_materialization_metadata(
                extra_metadata={
                    "market_distribution": market_distribution,
                    "terminated_index_count": terminated_index_count,
                }
            ),
        }
    )


@dg.asset(
    name="silver_index_basic",
    deps=[raw_tushare_index_basic],
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="index_basic",
        source_system=SourceSystem.DERIVED,
        data_contract="effective_index_basic",
        path_template="data_lake/silver/index_basic/full/part-000.parquet",
        extra_metadata={
            "filter_policy": (
                "silver_index_basic automatically uses the latest registered "
                "cn_a_index_trade_days date, and keeps indexes with exp_date "
                "null or exp_date > ready_for_trade_date."
            ),
            "expected_columns": list(INDEX_BASIC_SILVER_COLUMNS),
        },
    ),
    config_schema={},
    description="有效指数基础信息标准表，排除已终止指数。",
)
def silver_index_basic(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    ready_for_trade_date = _resolve_ready_for_trade_date(context)
    raw_path = raw_index_basic_path(lake_root.root())
    target_path = silver_index_basic_path(lake_root.root())
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw index basic file: {raw_path}")

    with duckdb.connect() as connection:
        source_row_count = _row_count(connection, raw_path)
        source_market_distribution = _market_distribution(connection, raw_path)
        source_terminated_index_count = _raw_terminated_index_count(
            connection, raw_path
        )
        _replace_parquet_from_query(
            connection,
            silver_index_basic_select(raw_path, ready_for_trade_date),
            target_path,
        )
        columns = _column_names(connection, target_path)
        row_count = _row_count(connection, target_path)
        market_distribution = _market_distribution(connection, target_path)

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            columns=columns,
            extra_metadata={
                "source_row_count": source_row_count,
                "kept_row_count": row_count,
                "filtered_out_row_count": source_row_count - row_count,
                "source_terminated_index_count": source_terminated_index_count,
                READY_FOR_TRADE_DATE_METADATA_KEY: ready_for_trade_date,
                "source_market_distribution": source_market_distribution,
                "market_distribution": market_distribution,
            },
        )
    )
