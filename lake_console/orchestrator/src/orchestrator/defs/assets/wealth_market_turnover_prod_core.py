from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.wealth_market_turnover import gold_wealth_market_turnover
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import gold_wealth_market_turnover_path
from orchestrator.defs.prod_db.wealth_market_turnover import (
    PROD_CORE_WEALTH_MARKET_TURNOVER_COLUMNS,
    PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE,
    replace_prod_core_wealth_market_turnover_partition,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresWriteResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
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
from orchestrator.defs.wealth_market_turnover_contract import (
    GOLD_WEALTH_MARKET_TURNOVER_COLUMNS,
    audit_gold_wealth_market_turnover_file_contract,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


PROD_CORE_WEALTH_MARKET_TURNOVER_PATH_TEMPLATE = (
    "postgresql://prod/core_serving.wealth_market_turnover_snapshot"
    "?trade_date={partition_key}"
)


def _human_materialization_metadata(
    *,
    partition_key: str,
    source_path: Path,
    row_count: int,
    read_back_row_count: int,
    points_json_hash: str,
) -> dict[str, object]:
    return {
        "summary": "已同步财富端市场成交额快照到 prod PostgreSQL core serving 表。",
        "next_action": "确认 prod read-back row count 与 gold 输出一致；后续财富 API 可按 serving 表读取。",
        "result_status": "written",
        "input_summary": {
            "source_asset": "gold_wealth_market_turnover",
            "partition_key": partition_key,
            "source_gold_path": str(source_path),
        },
        "serving_summary": {
            "target_system": "prod_postgres",
            "target_table": PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE,
            "replace_mode": "transactional_delete_then_insert",
            "row_count": row_count,
            "read_back_row_count": read_back_row_count,
            "points_json_hash": points_json_hash,
        },
        "diagnostic_ref": "完整诊断看 prod_core_wealth_market_turnover materialization metadata 和 run stdout。",
    }


@dg.asset(
    name="prod_core_wealth_market_turnover",
    deps=[gold_wealth_market_turnover],
    partitions_def=cn_a_stock_mins_silver_trade_days,
    group_name="wealth",
    tags=build_asset_tags(
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="wealth_market_turnover",
        source_system=SourceSystem.DERIVED,
        data_contract="core_serving.wealth_market_turnover_snapshot",
        source_doc="wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html",
        path_template=PROD_CORE_WEALTH_MARKET_TURNOVER_PATH_TEMPLATE,
        column_schema=GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
        extra_metadata={
            "target_system": "prod_postgres",
            "target_table": PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE,
            "source_asset": "gold_wealth_market_turnover",
            "replace_contract": "transactional_delete_insert_read_back",
        },
    ),
    description="同步财富市场成交额 gold 快照到 prod PostgreSQL core serving 表。",
)
def prod_core_wealth_market_turnover(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    prod_postgres_write: ProdPostgresWriteResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    source_path = gold_wealth_market_turnover_path(lake_root.root(), partition_key)
    log = DgStdoutLogger("wealth_market_turnover")
    log.stdout(
        "prod_core_wealth_market_turnover_started",
        partition_key=partition_key,
        target_table=PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE,
    )

    rows = load_gold_wealth_market_turnover_rows_for_prod_sync(
        duckdb_resource=duckdb,
        source_path=source_path,
        partition_key=partition_key,
    )
    with prod_postgres_write.connect() as connection:
        audit = replace_prod_core_wealth_market_turnover_partition(
            connection=connection,
            rows=rows,
            partition_key=partition_key,
        )

    log.stdout(
        "prod_core_wealth_market_turnover_completed",
        partition_key=partition_key,
        target_table=PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE,
        output_row_count=audit.row_count,
        read_back_row_count=audit.read_back_row_count,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=PROD_CORE_WEALTH_MARKET_TURNOVER_PATH_TEMPLATE.format(
                partition_key=partition_key,
            ),
            row_count=audit.row_count,
            observed_columns=audit.observed_columns,
            extra_metadata={
                **_human_materialization_metadata(
                    partition_key=partition_key,
                    source_path=source_path,
                    row_count=audit.row_count,
                    read_back_row_count=audit.read_back_row_count,
                    points_json_hash=audit.points_json_hash,
                ),
                "partition_key": partition_key,
                "source_asset": "gold_wealth_market_turnover",
                "source_gold_path": str(source_path),
                "prod_table": PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE,
                "replace_mode": "transactional_delete_then_insert",
                "points_json_hash": audit.points_json_hash,
                "read_back_row_count": audit.read_back_row_count,
            },
        )
    )


def load_gold_wealth_market_turnover_rows_for_prod_sync(
    *,
    duckdb_resource: DuckDBResource,
    source_path: Path,
    partition_key: str,
) -> tuple[dict[str, Any], ...]:
    with duckdb_resource.connect() as connection:
        file_audit = audit_gold_wealth_market_turnover_file_contract(
            connection=connection,
            target_path=source_path,
            partition_key=partition_key,
        )
        if not file_audit.passed:
            raise RuntimeError(
                "gold wealth_market_turnover file contract failed before prod sync: "
                f"reason_code={file_audit.reason_code}."
            )
        rows = connection.execute(
            f"""
            SELECT
              type,
              market,
              trade_date,
              freq,
              build_status,
              latest_trade_time,
              total_amount,
              total_vol,
              security_count,
              source_row_count,
              points_json,
              build_version,
              built_at,
              build_note
            FROM {read_parquet(source_path, hive_partitioning=False)}
            ORDER BY freq
            """
        ).fetchall()
    return tuple(
        dict(zip(GOLD_WEALTH_MARKET_TURNOVER_COLUMNS, row, strict=True))
        for row in rows
    )


WEALTH_MARKET_TURNOVER_PROD_CORE_COLUMNS = (
    PROD_CORE_WEALTH_MARKET_TURNOVER_COLUMNS
)
