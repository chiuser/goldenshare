"""Blocking file and standardization checks with explicit trade-day attribution."""

from functools import partial
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.moneyflow_ths import (
    raw_tushare_moneyflow_ths,
    silver_moneyflow_ths,
)
from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_file,
    audit_daily_moneyflow_standardization,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.partitions import cn_a_moneyflow_ths_trade_days
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_DUCKDB_MEMORY_LIMIT,
    MONEYFLOW_DUCKDB_THREADS,
    MONEYFLOW_THS_RAW_CHECK,
    MONEYFLOW_THS_SILVER_CHECK,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
)

audit_file = partial(audit_daily_moneyflow_file, dataset="moneyflow_ths")
audit_standardization = partial(
    audit_daily_moneyflow_standardization, dataset="moneyflow_ths"
)


def _check(context, lake_root, *, silver: bool) -> dg.AssetCheckResult:
    days = tuple(context.partition_keys)
    passed, reason, target = False, "single_partition_execution", None
    count = 0
    if len(days) == 1:
        day = days[0]
        raw = raw_moneyflow_path(lake_root.root(), "moneyflow_ths", day)
        target = (
            silver_moneyflow_path(lake_root.root(), "moneyflow_ths", day)
            if silver
            else raw
        )
        try:
            assert_moneyflow_memory_budget()
            # Read-only in-memory SQL, no temp directory or lake writes/spill.
            with connect_configured_duckdb(
                DuckDBConnectionSettings(
                    temp_directory=Path("/private/tmp"),
                    memory_limit=MONEYFLOW_DUCKDB_MEMORY_LIMIT,
                    threads=MONEYFLOW_DUCKDB_THREADS,
                ),
                temp_policy="existing_no_spill",
            ) as connection:
                if silver:
                    count = audit_standardization(connection, raw, target, day)
                else:
                    count = audit_file(connection, raw, day)
            passed, reason = True, "passed"
        except MoneyflowContractError as error:
            reason = str(error)
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION if silver else CheckScope.SCHEMA,
            checked_row_count=count if passed else 0,
            failed_row_count=0 if passed else None,
            file_path=target,
            extra_metadata={
                "reason_code": reason,
                "partition_key": days[0] if len(days) == 1 else None,
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_moneyflow_ths,
    partitions_def=cn_a_moneyflow_ths_trade_days,
    name=MONEYFLOW_THS_RAW_CHECK,
    blocking=True,
)
def raw_tushare_moneyflow_ths_file_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _check(context, lake_root, silver=False)


@dg.asset_check(
    asset=silver_moneyflow_ths,
    partitions_def=cn_a_moneyflow_ths_trade_days,
    name=MONEYFLOW_THS_SILVER_CHECK,
    blocking=True,
    additional_deps=[raw_tushare_moneyflow_ths],
)
def silver_moneyflow_ths_standardization_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _check(context, lake_root, silver=True)
