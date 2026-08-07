"""Single blocking core checks for major-index minute assets."""

from collections.abc import Sequence
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.major_index_mins_raw import (
    RAW_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.assets.major_index_mins_silver import (
    SILVER_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.major_index_mins_quality import (
    prepare_major_index_mins_raw_expected_tables,
    prepare_major_index_mins_silver_expected_tables,
    validate_major_index_mins_raw_relation,
    validate_major_index_mins_silver_relation,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_RAW_CHECKS,
    MAJOR_INDEX_MINS_SILVER_CHECKS,
    effective_raw_request_codes_for_date,
    effective_silver_codes_for_date,
    normalize_major_index_mins_silver_freq,
    raw_scope_hash_for_partition,
    silver_scope_hash_for_date,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _partition_key(context: dg.AssetCheckExecutionContext) -> str | None:
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
    expected_code_count: int = 0,
    scope_hash: str | None = None,
    failure_samples: Sequence[dict[str, object]] = (),
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=file_path,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            extra_metadata={
                "partition_key": partition_key,
                "failed_rule_names": list(failed_rules),
                "reason_code": reason_code,
                "expected_code_count": expected_code_count,
                "scope_hash": scope_hash,
                "failure_samples": list(failure_samples)[:5],
            },
        ),
    )


def evaluate_major_index_mins_core_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb_resource: DuckDBResource,
    layer: str,
    frequency: str,
) -> dg.AssetCheckResult:
    partition_key = _partition_key(context)
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
    normalized_frequency = normalize_major_index_mins_silver_freq(frequency)
    if layer == "raw":
        path = raw_major_index_mins_path(
            lake_root.root(),
            normalized_frequency,
            partition_key,
        )
    elif layer == "silver":
        path = silver_major_index_mins_path(
            lake_root.root(),
            normalized_frequency,
            partition_key,
        )
    else:
        raise ValueError(f"unsupported major-index minute check layer: {layer!r}")
    expected_codes = (
        effective_raw_request_codes_for_date(partition_key)
        if layer == "raw"
        else effective_silver_codes_for_date(partition_key)
    )
    scope_hash = (
        raw_scope_hash_for_partition(partition_key, normalized_frequency)
        if layer == "raw"
        else silver_scope_hash_for_date(partition_key)
    )
    if not path.exists():
        return _result(
            passed=False,
            partition_key=partition_key,
            file_path=path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("file_exists",),
            reason_code="file_missing",
            expected_code_count=len(expected_codes),
            scope_hash=scope_hash,
        )
    try:
        with duckdb_resource.connect() as connection:
            if layer == "raw":
                prepare_major_index_mins_raw_expected_tables(
                    connection,
                    expected_codes=expected_codes,
                    frequency=normalized_frequency,
                    partition_key=partition_key,
                )
                validation = validate_major_index_mins_raw_relation(
                    connection,
                    relation_sql=read_parquet(path, hive_partitioning=False),
                    expected_codes=expected_codes,
                    frequency=normalized_frequency,
                    partition_key=partition_key,
                )
            else:
                prepare_major_index_mins_silver_expected_tables(
                    connection,
                    expected_codes=expected_codes,
                    frequency=normalized_frequency,
                )
                validation = validate_major_index_mins_silver_relation(
                    connection,
                    relation_sql=read_parquet(path, hive_partitioning=False),
                    expected_codes=expected_codes,
                    frequency=normalized_frequency,
                    partition_key=partition_key,
                    require_null_vwap=normalized_frequency in {"90min", "120min"},
                )
        failed_row_count = (
            validation.invalid_row_count
            + validation.duplicate_key_count
            + validation.missing_session_row_count
            + validation.extra_session_row_count
        )
        return _result(
            passed=not validation.errors,
            partition_key=partition_key,
            file_path=path,
            checked_row_count=validation.row_count,
            failed_row_count=failed_row_count,
            failed_rules=validation.errors,
            reason_code=(
                "ready"
                if not validation.errors
                else f"{layer}_major_index_mins_core_check_failed"
            ),
            expected_code_count=len(expected_codes),
            scope_hash=scope_hash,
        )
    except Exception as error:  # noqa: BLE001 - check reports corrupt files.
        return _result(
            passed=False,
            partition_key=partition_key,
            file_path=path,
            checked_row_count=0,
            failed_row_count=0,
            failed_rules=("parquet_schema_and_contract",),
            reason_code="parquet_unreadable",
            expected_code_count=len(expected_codes),
            scope_hash=scope_hash,
            failure_samples=({"error_type": type(error).__name__},),
        )


def _build_check(
    *,
    asset: dg.AssetsDefinition,
    name: str,
    layer: str,
    frequency: str,
) -> dg.AssetsDefinition:
    @dg.asset_check(
        asset=asset,
        name=name,
        partitions_def=cn_major_index_mins_trade_days,
        blocking=True,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return evaluate_major_index_mins_core_check(
            context=context,
            lake_root=lake_root,
            duckdb_resource=duckdb,
            layer=layer,
            frequency=frequency,
        )

    return check


RAW_MAJOR_INDEX_MINS_CHECKS = tuple(
    _build_check(
        asset=asset,
        name=check_name,
        layer="raw",
        frequency=frequency,
    )
    for asset, check_name, frequency in zip(
        RAW_MAJOR_INDEX_MINS_ASSETS,
        MAJOR_INDEX_MINS_RAW_CHECKS,
        ("1min", "5min", "15min", "30min", "60min"),
        strict=True,
    )
)

(
    raw_major_index_mins_1m_core_check,
    raw_major_index_mins_5m_core_check,
    raw_major_index_mins_15m_core_check,
    raw_major_index_mins_30m_core_check,
    raw_major_index_mins_60m_core_check,
) = RAW_MAJOR_INDEX_MINS_CHECKS

SILVER_MAJOR_INDEX_MINS_CHECKS = tuple(
    _build_check(
        asset=asset,
        name=check_name,
        layer="silver",
        frequency=frequency,
    )
    for asset, check_name, frequency in zip(
        SILVER_MAJOR_INDEX_MINS_ASSETS,
        MAJOR_INDEX_MINS_SILVER_CHECKS,
        ("1min", "5min", "15min", "30min", "60min", "90min", "120min"),
        strict=True,
    )
)

(
    silver_major_index_mins_1m_core_check,
    silver_major_index_mins_5m_core_check,
    silver_major_index_mins_15m_core_check,
    silver_major_index_mins_30m_core_check,
    silver_major_index_mins_60m_core_check,
    silver_major_index_mins_90m_core_check,
    silver_major_index_mins_120m_core_check,
) = SILVER_MAJOR_INDEX_MINS_CHECKS

__all__ = [
    "RAW_MAJOR_INDEX_MINS_CHECKS",
    "SILVER_MAJOR_INDEX_MINS_CHECKS",
    "evaluate_major_index_mins_core_check",
    "raw_major_index_mins_1m_core_check",
    "raw_major_index_mins_5m_core_check",
    "raw_major_index_mins_15m_core_check",
    "raw_major_index_mins_30m_core_check",
    "raw_major_index_mins_60m_core_check",
    "silver_major_index_mins_1m_core_check",
    "silver_major_index_mins_5m_core_check",
    "silver_major_index_mins_15m_core_check",
    "silver_major_index_mins_30m_core_check",
    "silver_major_index_mins_60m_core_check",
    "silver_major_index_mins_90m_core_check",
    "silver_major_index_mins_120m_core_check",
]
