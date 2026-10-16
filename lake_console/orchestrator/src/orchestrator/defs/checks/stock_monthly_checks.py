"""Read-only monthly file, partition and current-materialization reconciliation checks."""

import dagster as dg
import duckdb

from orchestrator.defs.assets.stock_monthly import (
    raw_tushare_stk_period_bar_adj_month,
)
from orchestrator.defs.partitions import cn_a_stock_months
from orchestrator.defs.paths import raw_stock_monthly_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_check_names,
)
from orchestrator.defs.stock_period_checks import verify_period_materialization


def audit_monthly_file(connection, root, source, month, *, schema_only=False):
    from orchestrator.defs.io.stock_period_raw import audit_file

    StockMonthlySource(source)
    return audit_file(root, "month", month)


def _build_check(asset, source, name, kind):
    scope = (
        CheckScope.SCHEMA,
        CheckScope.PARTITION_ALIGNMENT,
        CheckScope.RECONCILIATION,
    )[kind]

    @dg.asset_check(
        asset=asset, name=name, partitions_def=cn_a_stock_months, blocking=True
    )
    def check(context: dg.AssetCheckExecutionContext, lake_root: LakeRootResource):
        try:
            evidence = audit_monthly_file(
                None, lake_root.root(), source, context.partition_key
            )
            if kind == 2:
                records = context.instance.fetch_materializations(
                    dg.AssetRecordsFilter(
                        asset_key=asset.key, asset_partitions=[context.partition_key]
                    ),
                    limit=1,
                ).records
                verify_period_materialization(
                    records[0] if records else None,
                    context.partition_key,
                    raw_stock_monthly_path(
                        lake_root.root(), source, context.partition_key
                    ),
                    rows=evidence["rows"],
                )
            return dg.AssetCheckResult(
                passed=True,
                metadata=build_check_metadata(
                    check_scope=scope, extra_metadata=evidence
                ),
            )
        except (ValueError, OSError, KeyError, TypeError, IndexError, duckdb.Error):
            return dg.AssetCheckResult(
                passed=False,
                severity=dg.AssetCheckSeverity.ERROR,
                metadata=build_check_metadata(
                    check_scope=scope,
                    extra_metadata={
                        "reason_code": "monthly_file_or_delivery_invalid",
                        "source": source.value,
                        "month": context.partition_key,
                        "next_action": "核查本次月份文件及最新物化的路径、行数和检查绑定。",
                    },
                ),
            )

    return check


for _asset, _source in (
    (raw_tushare_stk_period_bar_adj_month, StockMonthlySource.PRIMARY_ADJUSTED),
):
    for _index, _name in enumerate(monthly_check_names(_source)):
        globals()[_name] = _build_check(_asset, _source, _name, _index)
del _asset, _source, _index, _name
