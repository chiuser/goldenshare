"""Blocking file and standardization checks with explicit trade-day attribution."""

from datetime import date
from functools import partial
from pathlib import Path

import dagster as dg
from sqlalchemy.exc import SQLAlchemyError

from orchestrator.defs.assets.moneyflow_ind_dc import (
    raw_tushare_moneyflow_ind_dc,
    silver_moneyflow_ind_dc,
)
from orchestrator.defs.checks.daily_audit_coverage import (
    TARGET_VERSION_TAG,
    is_requested_version,
    stat_version,
)
from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_file,
    audit_daily_moneyflow_standardization,
)
from orchestrator.defs.daily_data_audit.dc_index_review import read_dc_index_standard
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.partitions import cn_a_moneyflow_ind_dc_trade_days
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_DUCKDB_MEMORY_LIMIT,
    MONEYFLOW_DUCKDB_THREADS,
    MONEYFLOW_IND_DC_RAW_CHECK,
    MONEYFLOW_IND_DC_SILVER_CHECK,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
)

audit_file = partial(audit_daily_moneyflow_file, dataset="moneyflow_ind_dc")
audit_standardization = partial(
    audit_daily_moneyflow_standardization, dataset="moneyflow_ind_dc"
)
BOARD_RAW_RUN_TAG = "audit/board_raw_run_id"
BOARD_STANDARD_RUN_TAG = "audit/board_standard_run_id"
BOARD_COVERAGE_META = "goldenshare/board_coverage"
_BOARD_CATEGORIES = {"行业": "行业板块", "概念": "概念板块", "地域": "地域板块"}


def _board_coverage_inputs(context, day, version):
    if version is None or not is_requested_version(context, version):
        return None, None, None
    raw_run_id = context.run.tags.get(BOARD_RAW_RUN_TAG)
    standard_run_id = context.run.tags.get(BOARD_STANDARD_RUN_TAG)
    try:
        records = context.instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=raw_tushare_moneyflow_ind_dc.key, asset_partitions=[day]
            ),
            limit=1,
        ).records
        if not records:
            return None, None, None
        raw = records[0]
        metadata = raw.asset_materialization.metadata
        digest = metadata.get("goldenshare/file_sha256")
        published_version = metadata.get("goldenshare/audit_file_version")
        # Older publications have only the hash. The late selection verifies it
        # and pins the file stat as well as the Raw run in the Check request.
        if (
            not digest
            or not raw.event_log_entry.run_id
            or (raw_run_id and raw.event_log_entry.run_id != raw_run_id)
            or (published_version is None and not (raw_run_id and context.run.tags.get(TARGET_VERSION_TAG)))
            or (published_version is not None and published_version.value != version)
        ):
            return None, None, None
        standard = read_dc_index_standard(context.instance, date.fromisoformat(day))
        if standard_run_id and (not standard or standard["version"] != standard_run_id):
            return None, None, None
    except SQLAlchemyError:
        return None, None, None
    return raw.event_log_entry.run_id, digest.value, standard


def _board_coverage(raw_run_id, digest, standard, observed_keys):
    if standard is None:
        return {
            "raw_run_id": raw_run_id, "file_version": digest, "standard_version": None,
            "status": "pending", "expected_count": None, "actual_count": None,
            "missing_codes": [], "extra_codes": [],
        }
    expected = {(board["category"], board["code"]) for board in standard["boards"]}
    actual = {
        (_BOARD_CATEGORIES[category], code.strip().upper())
        for category, code in observed_keys if code and code.strip()
    }
    return {
        "raw_run_id": raw_run_id, "file_version": digest,
        "standard_version": standard["version"],
        "status": "complete" if expected == actual else "gap",
        "expected_count": len(expected), "actual_count": len(actual),
        "missing_codes": sorted({code for _, code in expected - actual}),
        "extra_codes": sorted({code for _, code in actual - expected}),
    }


def _check(context, lake_root, *, silver: bool) -> dg.AssetCheckResult:
    days = tuple(context.partition_keys)
    passed, reason, target = False, "single_partition_execution", None
    count = 0
    coverage = None
    if len(days) == 1:
        day = days[0]
        raw = raw_moneyflow_path(lake_root.root(), "moneyflow_ind_dc", day)
        target = (
            silver_moneyflow_path(lake_root.root(), "moneyflow_ind_dc", day)
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
                    version = stat_version(raw)
                    raw_run_id, digest, standard = _board_coverage_inputs(context, day, version)
                    observed_keys = set()
                    if standard is None:
                        count = audit_file(connection, raw, day)
                    else:
                        count = audit_file(connection, raw, day, observed_board_keys=observed_keys)
                    if raw_run_id and stat_version(raw) == version:
                        coverage = _board_coverage(raw_run_id, digest, standard, observed_keys)
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
                **({BOARD_COVERAGE_META: coverage} if coverage is not None else {}),
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_moneyflow_ind_dc,
    partitions_def=cn_a_moneyflow_ind_dc_trade_days,
    name=MONEYFLOW_IND_DC_RAW_CHECK,
    blocking=True,
)
def raw_tushare_moneyflow_ind_dc_file_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _check(context, lake_root, silver=False)


@dg.asset_check(
    asset=silver_moneyflow_ind_dc,
    partitions_def=cn_a_moneyflow_ind_dc_trade_days,
    name=MONEYFLOW_IND_DC_SILVER_CHECK,
    blocking=True,
    additional_deps=[raw_tushare_moneyflow_ind_dc],
)
def silver_moneyflow_ind_dc_standardization_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _check(context, lake_root, silver=True)
