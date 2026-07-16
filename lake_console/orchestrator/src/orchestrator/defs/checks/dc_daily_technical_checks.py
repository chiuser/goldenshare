"""Single partition-attributable core check for Gold board indicators."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.dc_daily_technical_asset import gold_dc_daily_technical
from orchestrator.defs.assets.dc_board_silver import silver_dc_daily
from orchestrator.defs.asset_guards.dc_daily_technical_quality import (
    GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
    audit_gold_dc_daily_technical_partition,
)
from orchestrator.defs.partitions import cn_a_dc_daily_trade_days
from orchestrator.defs.paths import gold_dc_daily_technical_path, silver_dc_daily_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _selected_partition(context: dg.AssetCheckExecutionContext) -> str | None:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    return partition_keys[0] if len(partition_keys) == 1 else None


def _result(
    *,
    passed: bool,
    partition_key: str | None,
    file_path: Path | None,
    checked_row_count: int,
    failed_row_count: int,
    failed_rules: Sequence[str],
    reason_code: str,
    sample_rows: Sequence[dict[str, Any]] = (),
    extra_metadata: dict[str, object] | None = None,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            file_path=file_path,
            input_file_paths=(
                (str(file_path),) if file_path is not None else ()
            ),
            extra_metadata={
                "partition_key": partition_key,
                "failed_rules": list(failed_rules),
                "reason_code": reason_code,
                "failure_samples": list(sample_rows)[:5],
                **(extra_metadata or {}),
            },
        ),
    )


@dg.asset_check(
    asset=gold_dc_daily_technical,
    additional_deps=[silver_dc_daily],
    name=GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
    partitions_def=cn_a_dc_daily_trade_days,
    blocking=True,
)
def gold_dc_daily_technical_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = _selected_partition(context)
    if partition_key is None:
        return _result(
            passed=False,
            partition_key=None,
            file_path=None,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("single_partition_execution",),
            reason_code="multiple_partition_execution",
        )

    target_path = gold_dc_daily_technical_path(lake_root.root(), partition_key)
    source_path = silver_dc_daily_path(lake_root.root(), partition_key)
    try:
        duckdb_resource = duckdb
        with duckdb_resource.connect() as connection:
            audit = audit_gold_dc_daily_technical_partition(
                connection=connection,
                lake_root=lake_root.root(),
                trade_date=partition_key,
            )
    except Exception as exc:
        return _result(
            passed=False,
            partition_key=partition_key,
            file_path=target_path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("quality_scan_completed",),
            reason_code="scan_error",
            extra_metadata={"scan_error": str(exc)[:500], "source_file_path": str(source_path)},
        )

    return _result(
        passed=audit.passed,
        partition_key=partition_key,
        file_path=target_path,
        checked_row_count=audit.checked_row_count,
        failed_row_count=audit.failed_row_count,
        failed_rules=audit.failed_rules,
        reason_code=audit.reason_code,
        sample_rows=audit.sample_rows,
        extra_metadata={
            "source_file_path": str(source_path),
            **dict(audit.metadata),
        },
    )


__all__ = ["gold_dc_daily_technical_core_check"]
