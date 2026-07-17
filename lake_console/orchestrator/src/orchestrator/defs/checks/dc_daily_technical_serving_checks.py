"""Partition-attributable checks for local and Prod board technical serving."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import dagster as dg
from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.assets.dc_daily_technical_asset import gold_dc_daily_technical
from orchestrator.defs.assets.dc_daily_technical_serving import (
    _read_gold_rows,
    ch_dc_daily_technical,
    prod_ch_dc_daily_technical,
)
from orchestrator.defs.asset_guards.dc_daily_technical_quality import (
    GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
)
from orchestrator.defs.partitions import cn_a_dc_daily_trade_days
from orchestrator.defs.paths import gold_dc_daily_technical_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_TECHNICAL_INDICATOR_VERSION,
    DC_DAILY_TECHNICAL_PARAMS_KEY,
)
from orchestrator.defs.run_contracts.dc_daily_technical_serving import (
    DC_DAILY_TECHNICAL_SERVING_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_TABLE,
    PROD_CH_DC_DAILY_TECHNICAL_CHECKS,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


CH_DC_DAILY_TECHNICAL_CHECK_NAME = "ch_dc_daily_technical_core_check"
PROD_CH_DC_DAILY_TECHNICAL_CHECK_NAME = PROD_CH_DC_DAILY_TECHNICAL_CHECKS[0]


def _selected_partition(context: dg.AssetCheckExecutionContext) -> str | None:
    keys = tuple(sorted(set(context.partition_keys)))
    return keys[0] if len(keys) == 1 else None


def _check_result(
    *,
    passed: bool,
    partition_key: str | None,
    source_path: Path | None,
    checked_row_count: int,
    failed_row_count: int,
    failed_rules: Sequence[str],
    reason_code: str,
    failure_samples: Sequence[dict[str, object]] = (),
    extra_metadata: dict[str, object] | None = None,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            file_path=source_path,
            input_file_paths=(str(source_path),) if source_path else (),
            extra_metadata={
                "partition_key": partition_key,
                "failed_rules": list(failed_rules),
                "reason_code": reason_code,
                "failure_samples": list(failure_samples)[:5],
                **(extra_metadata or {}),
            },
        ),
    )


def _target_rows(client, partition_key: str) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in client.execute(
            f"SELECT {', '.join(DC_DAILY_TECHNICAL_SERVING_COLUMNS)} "
            f"FROM {DC_DAILY_TECHNICAL_SERVING_TABLE} "
            "WHERE trade_date = %(trade_date)s ORDER BY category, ts_code",
            {"trade_date": partition_key},
        )
    ]


def _target_rows_with_updated_at(client, partition_key: str) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in client.execute(
            f"SELECT {', '.join(DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS)} "
            f"FROM {DC_DAILY_TECHNICAL_SERVING_TABLE} "
            "WHERE trade_date = %(trade_date)s ORDER BY category, ts_code",
            {"trade_date": partition_key},
        )
    ]


def _row_sample(row: tuple[Any, ...]) -> dict[str, object]:
    return {
        "ts_code": row[0],
        "trade_date": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
        "category": row[2],
    }


def _date_value(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _technical_key(row: tuple[Any, ...]) -> tuple[object, str, object]:
    return row[0], _date_value(row[1]), row[2]


def _updated_at_is_not_older(
    local_row: tuple[Any, ...],
    prod_row: tuple[Any, ...],
) -> bool:
    if len(local_row) <= len(DC_DAILY_TECHNICAL_SERVING_COLUMNS):
        return False
    if len(prod_row) <= len(DC_DAILY_TECHNICAL_SERVING_COLUMNS):
        return False
    local_value = local_row[-1]
    prod_value = prod_row[-1]
    if local_value is None or prod_value is None:
        return False
    if isinstance(local_value, datetime) and isinstance(prod_value, datetime):
        local_value = local_value.replace(tzinfo=None)
        prod_value = prod_value.replace(tzinfo=None)
    return prod_value >= local_value


@dg.asset_check(
    asset=ch_dc_daily_technical,
    additional_deps=[gold_dc_daily_technical],
    name=CH_DC_DAILY_TECHNICAL_CHECK_NAME,
    partitions_def=cn_a_dc_daily_trade_days,
    blocking=True,
)
def ch_dc_daily_technical_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = _selected_partition(context)
    if partition_key is None:
        return _check_result(
            passed=False,
            partition_key=None,
            source_path=None,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("single_partition_execution",),
            reason_code="multiple_partition_execution",
        )

    source_path = gold_dc_daily_technical_path(lake_root.root(), partition_key)
    try:
        duckdb_resource = duckdb
        with duckdb_resource.connect() as connection:
            source_rows = _read_gold_rows(
                connection,
                source_path,
                partition_key=partition_key,
            )
        with clickhouse.get_connection() as client:
            target_rows = _target_rows(client, partition_key)
    except Exception as error:
        return _check_result(
            passed=False,
            partition_key=partition_key,
            source_path=source_path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("serving_scan_completed",),
            reason_code="scan_error",
            extra_metadata={"scan_error": str(error)[:500]},
        )

    failed_rules: list[str] = []
    if not target_rows:
        failed_rules.append("target_partition_exists_and_non_empty")

    target_keys = [(row[0], _date_value(row[1]), row[2]) for row in target_rows]
    duplicate_count = len(target_keys) - len(set(target_keys))
    if duplicate_count:
        failed_rules.append("business_key_unique")
    date_mismatch_count = sum(
        1 for row in target_rows if _date_value(row[1]) != partition_key
    )
    if date_mismatch_count:
        failed_rules.append("trade_date_matches_partition")
    invalid_identity_count = sum(
        1
        for row in target_rows
        if row[0] is None
        or not str(row[0]).strip()
        or row[2] is None
        or not str(row[2]).strip()
    )
    if invalid_identity_count:
        failed_rules.append("business_key_non_null")
    metadata_mismatch_count = sum(
        1
        for row in target_rows
        if row[-2] != DC_DAILY_TECHNICAL_PARAMS_KEY
        or row[-1] != DC_DAILY_TECHNICAL_INDICATOR_VERSION
    )
    if metadata_mismatch_count:
        failed_rules.append("indicator_metadata_matches_contract")
    if len(target_rows) != len(source_rows):
        failed_rules.append("row_count_matches_gold")

    sample_rows = tuple(_row_sample(row) for row in target_rows[:5])
    return _check_result(
        passed=not failed_rules,
        partition_key=partition_key,
        source_path=source_path,
        checked_row_count=len(target_rows),
        failed_row_count=sum(
            value
            for value in (
                duplicate_count,
                date_mismatch_count,
                invalid_identity_count,
                metadata_mismatch_count,
                abs(len(target_rows) - len(source_rows)),
            )
            if value
        ),
        failed_rules=failed_rules,
        reason_code="ready" if not failed_rules else "core_check_failed",
        failure_samples=sample_rows if failed_rules else (),
        extra_metadata={
            "target_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
            "expected_gold_row_count": len(source_rows),
            "target_row_count": len(target_rows),
            "duplicate_key_count": duplicate_count,
            "date_mismatch_count": date_mismatch_count,
            "invalid_identity_count": invalid_identity_count,
            "metadata_mismatch_count": metadata_mismatch_count,
            "null_semantics": "MA/BOLL warmup NULL preserved",
        },
    )


@dg.asset_check(
    asset=prod_ch_dc_daily_technical,
    additional_deps=[ch_dc_daily_technical],
    name=PROD_CH_DC_DAILY_TECHNICAL_CHECK_NAME,
    partitions_def=cn_a_dc_daily_trade_days,
    blocking=True,
)
def prod_ch_dc_daily_technical_core_check(
    context: dg.AssetCheckExecutionContext,
    clickhouse: ClickhouseResource,
    prod_clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = _selected_partition(context)
    if partition_key is None:
        return _check_result(
            passed=False,
            partition_key=None,
            source_path=None,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("single_partition_execution",),
            reason_code="multiple_partition_execution",
            extra_metadata={"target_system": "prod_clickhouse"},
        )

    try:
        with (
            clickhouse.get_connection() as local_client,
            prod_clickhouse.get_connection() as prod_client,
        ):
            local_rows = _target_rows_with_updated_at(local_client, partition_key)
            prod_rows = _target_rows_with_updated_at(prod_client, partition_key)
    except Exception as error:
        return _check_result(
            passed=False,
            partition_key=partition_key,
            source_path=None,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("serving_scan_completed",),
            reason_code="scan_error",
            extra_metadata={
                "target_system": "prod_clickhouse",
                "scan_error": str(error)[:500],
            },
        )

    business_width = len(DC_DAILY_TECHNICAL_SERVING_COLUMNS)
    local_keys = [_technical_key(row) for row in local_rows]
    prod_keys = [_technical_key(row) for row in prod_rows]
    local_by_key = {key: row for key, row in zip(local_keys, local_rows)}
    prod_by_key = {key: row for key, row in zip(prod_keys, prod_rows)}
    local_duplicate_count = len(local_keys) - len(set(local_keys))
    prod_duplicate_count = len(prod_keys) - len(set(prod_keys))
    missing_keys = sorted(set(local_by_key) - set(prod_by_key), key=str)
    extra_keys = sorted(set(prod_by_key) - set(local_by_key), key=str)
    content_mismatch_keys = [
        key
        for key in sorted(set(local_by_key) & set(prod_by_key), key=str)
        if local_by_key[key][:business_width] != prod_by_key[key][:business_width]
    ]
    metadata_mismatch_count = sum(
        1
        for row in prod_rows
        if row[-3] != DC_DAILY_TECHNICAL_PARAMS_KEY
        or row[-2] != DC_DAILY_TECHNICAL_INDICATOR_VERSION
    )
    date_mismatch_count = sum(
        1 for row in prod_rows if _date_value(row[1]) != partition_key
    )
    invalid_identity_count = sum(
        1
        for row in prod_rows
        if row[0] is None
        or not str(row[0]).strip()
        or row[2] is None
        or not str(row[2]).strip()
    )
    updated_at_not_older_count = sum(
        1
        for key in set(local_by_key) & set(prod_by_key)
        if not _updated_at_is_not_older(local_by_key[key], prod_by_key[key])
    )

    failed_rules: list[str] = []
    if not prod_rows:
        failed_rules.append("prod_target_partition_exists_and_non_empty")
    if local_duplicate_count or prod_duplicate_count:
        failed_rules.append("business_key_unique")
    if missing_keys or extra_keys or content_mismatch_keys:
        failed_rules.append("prod_rows_match_local")
    if date_mismatch_count:
        failed_rules.append("trade_date_matches_partition")
    if invalid_identity_count:
        failed_rules.append("business_key_non_null")
    if metadata_mismatch_count:
        failed_rules.append("indicator_metadata_matches_contract")
    if updated_at_not_older_count:
        failed_rules.append("prod_updated_at_not_older_than_local")

    samples = tuple(_row_sample(row) for row in prod_rows[:5])
    return _check_result(
        passed=not failed_rules,
        partition_key=partition_key,
        source_path=None,
        checked_row_count=len(prod_rows),
        failed_row_count=(
            len(missing_keys)
            + len(extra_keys)
            + len(content_mismatch_keys)
            + date_mismatch_count
            + invalid_identity_count
            + metadata_mismatch_count
            + updated_at_not_older_count
            + local_duplicate_count
            + prod_duplicate_count
        ),
        failed_rules=failed_rules,
        reason_code="ready" if not failed_rules else "core_check_failed",
        failure_samples=samples if failed_rules else (),
        extra_metadata={
            "target_system": "prod_clickhouse",
            "target_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
            "local_row_count": len(local_rows),
            "prod_row_count": len(prod_rows),
            "local_duplicate_key_count": local_duplicate_count,
            "prod_duplicate_key_count": prod_duplicate_count,
            "missing_key_count": len(missing_keys),
            "extra_key_count": len(extra_keys),
            "content_mismatch_count": len(content_mismatch_keys),
            "date_mismatch_count": date_mismatch_count,
            "invalid_identity_count": invalid_identity_count,
            "metadata_mismatch_count": metadata_mismatch_count,
            "updated_at_not_older_count": updated_at_not_older_count,
            "missing_key_samples": [str(value) for value in missing_keys[:5]],
            "extra_key_samples": [str(value) for value in extra_keys[:5]],
            "content_mismatch_samples": [
                str(value) for value in content_mismatch_keys[:5]
            ],
        },
    )


__all__ = [
    "CH_DC_DAILY_TECHNICAL_CHECK_NAME",
    "PROD_CH_DC_DAILY_TECHNICAL_CHECK_NAME",
    "ch_dc_daily_technical_core_check",
    "prod_ch_dc_daily_technical_core_check",
]
