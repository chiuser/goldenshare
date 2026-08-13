"""Blocking reconciliation check for stock daily QFQ nine-turn serving."""

import dagster as dg

from orchestrator.defs.assets.stock_daily_qfq_nineturn_prod_core import (
    load_gold_stock_daily_qfq_nineturn_rows_for_prod_sync,
    prod_core_stock_daily_qfq_nineturn,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.prod_db.stock_daily_qfq_nineturn import (
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CHECK_NAME,
    audit_prod_core_stock_daily_qfq_nineturn_partition,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresWriteResource,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


@dg.asset_check(
    asset=prod_core_stock_daily_qfq_nineturn,
    name=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CHECK_NAME,
    partitions_def=cn_a_stock_trade_days,
    blocking=True,
)
def prod_core_stock_daily_qfq_nineturn_partition_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    prod_postgres_write: ProdPostgresWriteResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    root = lake_root.root()
    source_path = gold_stock_daily_qfq_nineturn_path(root, partition_key)
    try:
        expected_rows = load_gold_stock_daily_qfq_nineturn_rows_for_prod_sync(
            duckdb_resource=duckdb,
            source_path=source_path,
            qfq_source_path=gold_stock_daily_qfq_path(root, partition_key),
            partition_key=partition_key,
        )
        with prod_postgres_write.connect_readonly() as connection:
            audit = audit_prod_core_stock_daily_qfq_nineturn_partition(
                connection=connection,
                rows=expected_rows,
                partition_key=partition_key,
            )
    except Exception as error:  # noqa: BLE001 - check records a bounded failure.
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=0,
                failed_row_count=0,
                file_path=source_path,
                extra_metadata={
                    "partition_key": partition_key,
                    "reason_code": "scan_error",
                    "failed_rule_names": ["serving_scan_completed"],
                    "error": str(error)[:500],
                },
            ),
        )
    return dg.AssetCheckResult(
        passed=audit.passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=audit.read_back_row_count,
            failed_row_count=(0 if audit.passed else audit.expected_row_count),
            file_path=source_path,
            extra_metadata={
                "partition_key": partition_key,
                "reason_code": "ready" if audit.passed else "serving_drift",
                "expected_row_count": audit.expected_row_count,
                "read_back_row_count": audit.read_back_row_count,
                "expected_content_hash": audit.expected_content_hash,
                "observed_content_hash": audit.observed_content_hash,
                "failed_rule_names": list(audit.failed_rule_names),
            },
        ),
    )
