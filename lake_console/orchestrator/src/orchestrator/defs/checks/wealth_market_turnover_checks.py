import dagster as dg

from orchestrator.defs.assets.wealth_market_turnover import gold_wealth_market_turnover
from orchestrator.defs.paths import gold_wealth_market_turnover_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.wealth_market_turnover_contract import (
    WEALTH_MARKET_TURNOVER_CHECK_NAME,
    WealthMarketTurnoverIntegrityAudit,
    audit_gold_wealth_market_turnover_file_contract,
    audit_gold_wealth_market_turnover_recomputed_from_silver,
    wealth_market_turnover_input_paths,
)


@dg.asset_check(asset=gold_wealth_market_turnover, blocking=True)
def gold_wealth_market_turnover_integrity_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    target_path = gold_wealth_market_turnover_path(lake_root.root(), partition_key)
    input_paths = wealth_market_turnover_input_paths(lake_root.root(), partition_key)
    duckdb_resource = duckdb

    with duckdb_resource.connect() as connection:
        file_audit = audit_gold_wealth_market_turnover_file_contract(
            connection=connection,
            target_path=target_path,
            partition_key=partition_key,
        )
        if not file_audit.passed:
            return _check_result_from_audit(file_audit, file_path=target_path)

        recompute_audit = audit_gold_wealth_market_turnover_recomputed_from_silver(
            connection=connection,
            target_path=target_path,
            input_paths=input_paths,
            partition_key=partition_key,
        )
        return _check_result_from_audit(recompute_audit, file_path=target_path)


def _check_result_from_audit(
    audit: WealthMarketTurnoverIntegrityAudit,
    *,
    file_path,
) -> dg.AssetCheckResult:
    summary = (
        "财富成交额 gold 完整性检查通过。"
        if audit.passed
        else "财富成交额 gold 完整性检查失败，先看 failure_stage 和 reason_code。"
    )
    next_action = (
        "无需处理，等待 prod core serving 同步。"
        if audit.passed
        else "先修复缺失的 silver_stk_mins 五频度输入或 gold points_json 输出，再重跑 gold_wealth_market_turnover。"
    )
    return dg.AssetCheckResult(
        passed=audit.passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=audit.checked_row_count,
            failed_row_count=audit.failed_row_count,
            file_path=file_path,
            missing_file_paths=audit.missing_file_paths,
            extra_metadata={
                "summary": summary,
                "next_action": next_action,
                "rule_summary": {
                    "passed": audit.passed,
                    "failure_stage": audit.failure_stage or "",
                    "reason_code": audit.reason_code or "",
                    "checked_row_count": audit.checked_row_count,
                    "failed_row_count": audit.failed_row_count,
                    "missing_file_count": len(audit.missing_file_paths),
                },
                "check_name": WEALTH_MARKET_TURNOVER_CHECK_NAME,
                "failure_stage": audit.failure_stage or "",
                "reason_code": audit.reason_code or "",
                "sample_rows": list(audit.sample_rows),
                **audit.metadata,
            },
        ),
    )
