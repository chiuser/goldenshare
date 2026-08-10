"""Single-date fail-closed Lake readiness for ``idx_factor_pro``."""

from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityDateReadiness,
)
from orchestrator.defs.checks.idx_factor_pro_checks import (
    audit_idx_factor_pro_raw_partition,
    audit_idx_factor_pro_silver_partition,
    failed_idx_factor_pro_raw_check_names,
    failed_idx_factor_pro_silver_check_names,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_RAW_CHECKS,
    IDX_FACTOR_PRO_SILVER_CHECKS,
    normalize_idx_factor_pro_trade_date,
)


def raw_idx_factor_pro_lake_readiness(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    trade_date: str,
) -> ContinuityDateReadiness:
    """Audit one Raw partition without reading Dagster event history."""

    started_at = perf_counter()
    partition_key = normalize_idx_factor_pro_trade_date(trade_date)
    audit = audit_idx_factor_pro_raw_partition(
        lake_root_path=lake_root,
        duckdb_resource=duckdb_resource,
        partition_key=partition_key,
    )
    if not audit.file_path.exists():
        return ContinuityDateReadiness(
            trade_date=partition_key,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason="idx_factor_pro Raw file missing",
            missing_check_names=IDX_FACTOR_PRO_RAW_CHECKS,
            missing_file_paths=(str(audit.file_path),),
            summary={
                "layer": "raw",
                "reason_code": "file_missing",
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
    failed_checks = failed_idx_factor_pro_raw_check_names(audit)
    relation = audit.relation
    return ContinuityDateReadiness(
        trade_date=partition_key,
        ready=not failed_checks,
        materialized=True,
        checks_passed=not failed_checks,
        reason=(
            "idx_factor_pro Raw ready"
            if not failed_checks
            else "idx_factor_pro Raw blocking checks failed"
        ),
        failed_check_names=failed_checks,
        summary={
            "layer": "raw",
            "reason_code": "ready" if not failed_checks else "blocking_check_failed",
            "checked_row_count": relation.row_count if relation is not None else 0,
            "failed_check_count": len(failed_checks),
            "error_type": audit.error_type,
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
        },
    )


def silver_idx_factor_pro_lake_readiness(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    trade_date: str,
) -> ContinuityDateReadiness:
    """Audit one Silver partition and its same-date Raw source."""

    started_at = perf_counter()
    partition_key = normalize_idx_factor_pro_trade_date(trade_date)
    audit = audit_idx_factor_pro_silver_partition(
        lake_root_path=lake_root,
        duckdb_resource=duckdb_resource,
        partition_key=partition_key,
    )
    if not audit.silver_file_path.exists():
        return ContinuityDateReadiness(
            trade_date=partition_key,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason="idx_factor_pro Silver file missing",
            missing_check_names=IDX_FACTOR_PRO_SILVER_CHECKS,
            missing_file_paths=(str(audit.silver_file_path),),
            summary={
                "layer": "silver",
                "reason_code": "file_missing",
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
    failed_checks = failed_idx_factor_pro_silver_check_names(audit)
    relation = audit.silver_relation
    return ContinuityDateReadiness(
        trade_date=partition_key,
        ready=not failed_checks,
        materialized=True,
        checks_passed=not failed_checks,
        reason=(
            "idx_factor_pro Silver ready"
            if not failed_checks
            else "idx_factor_pro Silver blocking checks failed"
        ),
        failed_check_names=failed_checks,
        summary={
            "layer": "silver",
            "reason_code": "ready" if not failed_checks else "blocking_check_failed",
            "checked_row_count": relation.row_count if relation is not None else 0,
            "failed_check_count": len(failed_checks),
            "raw_error_type": audit.raw_error_type,
            "silver_error_type": audit.silver_error_type,
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
        },
    )


__all__ = [
    "raw_idx_factor_pro_lake_readiness",
    "silver_idx_factor_pro_lake_readiness",
]
