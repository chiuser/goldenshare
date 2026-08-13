"""Shared single-partition core-check evaluator for canonical Gold minute bars."""

from collections.abc import Sequence
from pathlib import Path

import dagster as dg

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.cn_a_gold_minute_bars import (
    audit_canonical_gold_minute_relation,
)
from orchestrator.defs.io.cn_a_gold_minute_writer import load_minute_source_codes
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def canonical_gold_minute_check_failure(
    *,
    reason_code: str,
    failed_rule_names: Sequence[str],
    partition_key: str | None = None,
    file_path: Path | None = None,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=file_path,
            checked_row_count=0,
            failed_row_count=0,
            extra_metadata={
                "partition_key": partition_key,
                "reason_code": reason_code,
                "failed_rule_names": list(failed_rule_names),
            },
        ),
    )


def evaluate_canonical_gold_minute_core_check(
    *,
    connection,
    target_path: Path,
    source_path: Path,
    target_freq: int,
    partition_key: str,
    expected_codes: Sequence[object] | None = None,
) -> dg.AssetCheckResult:
    if not target_path.is_file():
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.SCHEMA,
                file_path=target_path,
                checked_row_count=0,
                failed_row_count=0,
                extra_metadata={
                    "partition_key": partition_key,
                    "reason_code": "file_missing",
                    "failed_rule_names": ["file_exists"],
                },
            ),
        )
    try:
        codes = (
            tuple(expected_codes)
            if expected_codes is not None
            else load_minute_source_codes(connection, source_path)
        )
        audit = audit_canonical_gold_minute_relation(
            connection,
            relation_sql=(
                f"SELECT * FROM {read_parquet(target_path, hive_partitioning=False)}"
            ),
            target_freq=target_freq,
            partition_key=partition_key,
            expected_codes=codes,
        )
        return dg.AssetCheckResult(
            passed=audit.ready,
            metadata=build_check_metadata(
                check_scope=CheckScope.SCHEMA,
                file_path=target_path,
                checked_row_count=audit.row_count,
                failed_row_count=sum(
                    (
                        audit.duplicate_key_count,
                        audit.missing_key_count,
                        audit.unexpected_key_count,
                        audit.invalid_partition_count,
                        audit.invalid_frequency_count,
                        audit.invalid_target_time_count,
                        audit.non_1m_0930_row_count,
                        audit.post_close_row_count,
                        audit.invalid_value_count,
                        audit.invalid_exchange_count,
                    )
                ),
                extra_metadata={
                    "partition_key": partition_key,
                    "reason_code": "ready" if audit.ready else "core_check_failed",
                    "failed_rule_names": list(audit.failed_rules),
                    "expected_row_count": audit.expected_row_count,
                    "expected_code_count": len(codes),
                    "elapsed_ms": round(audit.elapsed_ms, 3),
                },
            ),
        )
    except Exception as error:  # noqa: BLE001 - checks report corrupt files.
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.SCHEMA,
                file_path=target_path,
                checked_row_count=0,
                failed_row_count=0,
                extra_metadata={
                    "partition_key": partition_key,
                    "reason_code": "scan_error",
                    "failed_rule_names": ["parquet_schema_and_contract"],
                    "scan_error_type": type(error).__name__,
                },
            ),
        )


__all__ = [
    "canonical_gold_minute_check_failure",
    "evaluate_canonical_gold_minute_core_check",
]
