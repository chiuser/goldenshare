"""Publish validated stock daily QFQ nine-turn Gold partitions to prod serving."""

from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.qfq_nineturn import gold_stock_daily_qfq_nineturn
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.prod_db.stock_daily_qfq_nineturn import (
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE,
    replace_prod_core_stock_daily_qfq_nineturn_partition,
)
from orchestrator.defs.qfq_nineturn_integrity import audit_qfq_nineturn_integrity
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresWriteResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
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
from orchestrator.defs.run_contracts.qfq_nineturn import QFQ_NINETURN_VERSION
from orchestrator.utils.dg_log_helper import DgStdoutLogger

PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PATH_TEMPLATE = (
    "postgresql://prod/core_serving.equity_qfq_nineturn_daily"
    "?trade_date={partition_key}"
)
_GOLD_COLUMNS = PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS[:7]


@dg.asset(
    name="prod_core_stock_daily_qfq_nineturn",
    deps=[gold_stock_daily_qfq_nineturn],
    partitions_def=cn_a_stock_trade_days,
    group_name="quote",
    tags=build_asset_tags(
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.QUOTE_DATA,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="stock_daily_qfq_nineturn",
        source_system=SourceSystem.DERIVED,
        data_contract="core_serving.equity_qfq_nineturn_daily",
        source_doc=(
            "wealth/docs/system/"
            "detail-page-nine-turn-integration-low-level-design-v1.md"
        ),
        path_template=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PATH_TEMPLATE,
        column_schema=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
        extra_metadata={
            "target_system": "prod_postgres",
            "target_table": PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE,
            "source_asset": "gold_stock_daily_qfq_nineturn",
            "formula_version": QFQ_NINETURN_VERSION,
            "replace_contract": "transactional_delete_insert_read_back",
        },
    ),
    description=(
        "将自主计算的股票日线前复权九转 Gold 分区事务发布到 prod PostgreSQL；"
        "不消费 Tushare 神奇九转。"
    ),
)
def prod_core_stock_daily_qfq_nineturn(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    prod_postgres_write: ProdPostgresWriteResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    root = lake_root.root()
    source_path = gold_stock_daily_qfq_nineturn_path(root, partition_key)
    qfq_source_path = gold_stock_daily_qfq_path(root, partition_key)
    log = DgStdoutLogger("qfq_nineturn")
    log.stdout(
        "prod_core_stock_daily_qfq_nineturn_started",
        partition_key=partition_key,
        target_table=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE,
    )
    rows = load_gold_stock_daily_qfq_nineturn_rows_for_prod_sync(
        duckdb_resource=duckdb,
        source_path=source_path,
        qfq_source_path=qfq_source_path,
        partition_key=partition_key,
    )
    with prod_postgres_write.connect() as connection:
        audit = replace_prod_core_stock_daily_qfq_nineturn_partition(
            connection=connection,
            rows=rows,
            partition_key=partition_key,
        )
    log.stdout(
        "prod_core_stock_daily_qfq_nineturn_completed",
        partition_key=partition_key,
        output_row_count=audit.row_count,
        read_back_row_count=audit.read_back_row_count,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PATH_TEMPLATE.format(
                partition_key=partition_key
            ),
            row_count=audit.row_count,
            observed_columns=audit.observed_columns,
            extra_metadata={
                "summary": "已同步股票日线前复权九转到 prod PostgreSQL serving。",
                "result_status": "written",
                "partition_key": partition_key,
                "source_asset": "gold_stock_daily_qfq_nineturn",
                "source_gold_path": str(source_path),
                "target_table": PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE,
                "formula_version": QFQ_NINETURN_VERSION,
                "read_back_row_count": audit.read_back_row_count,
                "content_hash": audit.content_hash,
                "replace_mode": "transactional_delete_then_bulk_insert",
            },
        )
    )


def load_gold_stock_daily_qfq_nineturn_rows_for_prod_sync(
    *,
    duckdb_resource: DuckDBResource,
    source_path: Path,
    qfq_source_path: Path,
    partition_key: str,
) -> tuple[dict[str, Any], ...]:
    with duckdb_resource.connect() as connection:
        diagnostics = audit_qfq_nineturn_integrity(
            connection,
            target_path=source_path,
            source_paths=(qfq_source_path,),
            partition_key=partition_key,
            freq=None,
        )
        if not diagnostics.passed:
            raise RuntimeError(
                "Gold stock daily QFQ nine-turn contract failed before prod sync: "
                f"rules={diagnostics.failed_rule_names}."
            )
        rows = connection.execute(
            f"""
            SELECT
              ts_code,
              trade_date,
              close_qfq,
              up_count,
              down_count,
              nine_up_turn,
              nine_down_turn
            FROM {read_parquet(source_path, hive_partitioning=False)}
            ORDER BY ts_code
            """
        ).fetchall()
    return tuple(dict(zip(_GOLD_COLUMNS, row, strict=True)) for row in rows)
