"""Two aggregated checks: physical contract and current delivery evidence."""

import dagster as dg

from orchestrator.defs.asset_guards.daily_basic_readiness import (
    daily_basic_materializations,
    delivery_metadata,
    load_daily_basic_input_codes,
)
from orchestrator.defs.daily_basic_contract import DAILY_BASIC_ASSET, DAILY_BASIC_CHECKS
from orchestrator.defs.daily_basic_raw_io import (
    audit_daily_basic_coverage,
    audit_daily_basic_file,
    file_sha256,
)
from orchestrator.defs.partitions import cn_a_daily_basic_trade_days
from orchestrator.defs.paths import raw_daily_basic_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import build_check_metadata


def daily_basic_check_result(context, lake_root, duckdb, *, coverage):
    day = context.partition_key
    path = raw_daily_basic_path(lake_root.root(), day)
    record = daily_basic_materializations(context.instance, [day]).get(day)
    failed = []
    rows = 0
    try:
        before = file_sha256(path) if path.is_file() else None
        with duckdb.connect() as connection:
            audit = audit_daily_basic_file(connection, path, day)
            rows = audit.row_count
            failed.extend(audit.failed_rules)
            if coverage:
                if record is None:
                    failed.append("missing_delivery")
                else:
                    selected = context.run.asset_selection
                    # A materializing run cannot borrow a concurrent run's delivery.
                    materializing = dg.AssetKey(DAILY_BASIC_ASSET) in (
                        context.job_def.asset_layer.executable_asset_keys
                        if selected is None
                        else selected
                    )
                    steps = context.run.step_keys_to_execute
                    if steps is not None:
                        materializing = materializing and DAILY_BASIC_ASSET in steps
                    if (
                        materializing
                        and record.event_log_entry.run_id != context.run.run_id
                    ):
                        failed.append("different_run_delivery")
                    codes = load_daily_basic_input_codes(
                        context.instance, connection, lake_root.root(), day
                    )
                    failed.extend(
                        audit_daily_basic_coverage(
                            path, audit, codes, delivery_metadata(record)
                        )
                    )
        after = file_sha256(path) if path.is_file() else None
        latest = daily_basic_materializations(context.instance, [day]).get(day)
        if before != after or getattr(record, "storage_id", None) != getattr(
            latest, "storage_id", None
        ):
            failed.append("delivery_changed_during_check")
    except Exception:  # noqa: BLE001 -- failed inputs become a red check, never a green fallback.
        failed.append("input_or_delivery_unavailable")
    return dg.AssetCheckResult(
        passed=not failed,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata=build_check_metadata(
            check_scope="reconciliation",
            checked_row_count=rows,
            failed_row_count=rows if failed else 0,
            file_path=path,
            extra_metadata={
                "failed_rule_names": list(dict.fromkeys(failed)),
                "summary": "每日指标交付核验通过。"
                if not failed
                else "每日指标文件或交付依据不一致。",
                "next_action": "可继续使用。"
                if not failed
                else "查看失败规则；核对同日股票Raw和本次交付，修复后重跑。",
            },
        ),
    )


@dg.asset_check(
    asset=DAILY_BASIC_ASSET,
    name=DAILY_BASIC_CHECKS[0],
    partitions_def=cn_a_daily_basic_trade_days,
    blocking=True,
    description="核对18字段、日期、空键、重复键与文件可读性。",
)
def raw_tushare_daily_basic_file_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
):
    return daily_basic_check_result(context, lake_root, duckdb, coverage=False)


@dg.asset_check(
    asset=DAILY_BASIC_ASSET,
    name=DAILY_BASIC_CHECKS[1],
    partitions_def=cn_a_daily_basic_trade_days,
    blocking=True,
    description="核对当前交付指纹、行数和同日股票Raw最低代码覆盖，不重拉源数据。",
)
def raw_tushare_daily_basic_source_coverage_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
):
    return daily_basic_check_result(context, lake_root, duckdb, coverage=True)
