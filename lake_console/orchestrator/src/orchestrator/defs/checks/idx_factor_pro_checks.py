"""Raw and Silver contract checks for Tushare ``idx_factor_pro``."""

from dataclasses import dataclass
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.idx_factor_pro_raw import raw_tushare_idx_factor_pro
from orchestrator.defs.assets.idx_factor_pro_silver import silver_index_factor_pro
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.idx_factor_pro_raw_writer import (
    IdxFactorProRawAudit,
    validate_idx_factor_pro_raw_relation,
)
from orchestrator.defs.io.idx_factor_pro_silver_writer import (
    IdxFactorProRawSilverParityAudit,
    IdxFactorProSilverAudit,
    validate_idx_factor_pro_raw_silver_parity,
    validate_idx_factor_pro_silver_relation,
)
from orchestrator.defs.partitions import cn_major_index_factor_trade_days
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    silver_index_factor_pro_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_RAW_CHECKS,
    IDX_FACTOR_PRO_RAW_NULLABLE_CHECK,
    IDX_FACTOR_PRO_SILVER_CHECKS,
    active_idx_factor_pro_daily_codes,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


@dataclass(frozen=True, slots=True)
class IdxFactorProRawFileAudit:
    partition_key: str
    file_path: Path
    expected_codes: tuple[str, ...]
    relation: IdxFactorProRawAudit | None
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class IdxFactorProSilverFileAudit:
    partition_key: str
    raw_file_path: Path
    silver_file_path: Path
    expected_codes: tuple[str, ...]
    raw_relation: IdxFactorProRawAudit | None
    silver_relation: IdxFactorProSilverAudit | None
    parity: IdxFactorProRawSilverParityAudit | None
    raw_error_type: str | None = None
    silver_error_type: str | None = None


def audit_idx_factor_pro_raw_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
) -> IdxFactorProRawFileAudit:
    expected_codes = active_idx_factor_pro_daily_codes(partition_key)
    file_path = raw_idx_factor_pro_path(lake_root_path, partition_key)
    if not file_path.exists():
        return IdxFactorProRawFileAudit(
            partition_key=partition_key,
            file_path=file_path,
            expected_codes=expected_codes,
            relation=None,
            error_type="file_missing",
        )
    try:
        with duckdb_resource.connect() as connection:
            relation = validate_idx_factor_pro_raw_relation(
                connection,
                relation_sql=read_parquet(file_path, hive_partitioning=False),
                expected_codes=expected_codes,
                partition_key=partition_key,
            )
    except Exception as error:  # noqa: BLE001 - checks report corrupt files.
        return IdxFactorProRawFileAudit(
            partition_key=partition_key,
            file_path=file_path,
            expected_codes=expected_codes,
            relation=None,
            error_type=type(error).__name__,
        )
    return IdxFactorProRawFileAudit(
        partition_key=partition_key,
        file_path=file_path,
        expected_codes=expected_codes,
        relation=relation,
    )


def audit_idx_factor_pro_silver_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
) -> IdxFactorProSilverFileAudit:
    expected_codes = active_idx_factor_pro_daily_codes(partition_key)
    raw_file_path = raw_idx_factor_pro_path(lake_root_path, partition_key)
    silver_file_path = silver_index_factor_pro_path(lake_root_path, partition_key)
    raw_error_type = "file_missing" if not raw_file_path.exists() else None
    silver_error_type = "file_missing" if not silver_file_path.exists() else None
    if raw_error_type or silver_error_type:
        return IdxFactorProSilverFileAudit(
            partition_key=partition_key,
            raw_file_path=raw_file_path,
            silver_file_path=silver_file_path,
            expected_codes=expected_codes,
            raw_relation=None,
            silver_relation=None,
            parity=None,
            raw_error_type=raw_error_type,
            silver_error_type=silver_error_type,
        )

    raw_relation: IdxFactorProRawAudit | None = None
    silver_relation: IdxFactorProSilverAudit | None = None
    parity: IdxFactorProRawSilverParityAudit | None = None
    try:
        with duckdb_resource.connect() as connection:
            raw_sql = read_parquet(raw_file_path, hive_partitioning=False)
            silver_sql = read_parquet(silver_file_path, hive_partitioning=False)
            raw_relation = validate_idx_factor_pro_raw_relation(
                connection,
                relation_sql=raw_sql,
                expected_codes=expected_codes,
                partition_key=partition_key,
            )
            silver_relation = validate_idx_factor_pro_silver_relation(
                connection,
                relation_sql=silver_sql,
                expected_codes=expected_codes,
                partition_key=partition_key,
            )
            if not raw_relation.errors and not silver_relation.errors:
                parity = validate_idx_factor_pro_raw_silver_parity(
                    connection,
                    raw_relation_sql=raw_sql,
                    silver_relation_sql=silver_sql,
                )
    except Exception as error:  # noqa: BLE001 - checks report corrupt files.
        error_type = type(error).__name__
        if raw_relation is None:
            raw_error_type = error_type
        else:
            silver_error_type = error_type
    return IdxFactorProSilverFileAudit(
        partition_key=partition_key,
        raw_file_path=raw_file_path,
        silver_file_path=silver_file_path,
        expected_codes=expected_codes,
        raw_relation=raw_relation,
        silver_relation=silver_relation,
        parity=parity,
        raw_error_type=raw_error_type,
        silver_error_type=silver_error_type,
    )


def _partition_key(context: dg.AssetCheckExecutionContext) -> str | None:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    return partition_keys[0] if len(partition_keys) == 1 else None


def _failed_rules(
    audit: IdxFactorProRawFileAudit,
    *,
    check_kind: str,
) -> tuple[str, ...]:
    relation = audit.relation
    if relation is None:
        return (audit.error_type or "parquet_unreadable",)
    if check_kind == "contract":
        return relation.schema_errors
    if check_kind == "scope":
        return relation.scope_errors
    if check_kind == "key":
        return relation.key_errors
    if check_kind == "parity":
        return tuple(
            dict.fromkeys(
                relation.parity_errors
                + (("missing_codes",) if relation.missing_codes else ())
                + (("extra_codes",) if relation.extra_codes else ())
            )
        )
    if check_kind == "nullable":
        return relation.schema_errors
    raise ValueError(f"unsupported idx_factor_pro check kind: {check_kind!r}")


def failed_idx_factor_pro_raw_check_names(
    audit: IdxFactorProRawFileAudit,
) -> tuple[str, ...]:
    """Return the exact blocking Raw checks that fail for one file audit."""

    return tuple(
        name
        for name, check_kind in zip(
            IDX_FACTOR_PRO_RAW_CHECKS,
            ("contract", "scope", "key", "parity"),
            strict=True,
        )
        if _failed_rules(audit, check_kind=check_kind)
    )


def evaluate_idx_factor_pro_raw_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb_resource: DuckDBResource,
    check_kind: str,
) -> dg.AssetCheckResult:
    partition_key = _partition_key(context)
    if partition_key is None:
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                checked_row_count=0,
                failed_row_count=0,
                extra_metadata={
                    "reason_code": "single_partition_required",
                    "failed_rule_names": ["single_partition_execution"],
                },
            ),
            severity=(
                dg.AssetCheckSeverity.WARN
                if check_kind == "nullable"
                else dg.AssetCheckSeverity.ERROR
            ),
        )
    audit = audit_idx_factor_pro_raw_partition(
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb_resource,
        partition_key=partition_key,
    )
    failed_rules = _failed_rules(audit, check_kind=check_kind)
    relation = audit.relation
    checked_row_count = relation.row_count if relation is not None else 0
    failed_row_count = 0
    if relation is not None:
        failed_row_count = (
            relation.invalid_key_count
            + relation.invalid_date_count
            + relation.duplicate_key_count
            + len(relation.missing_codes)
            + len(relation.extra_codes)
        )
    return dg.AssetCheckResult(
        passed=not failed_rules,
        metadata=build_check_metadata(
            check_scope={
                "contract": CheckScope.SCHEMA,
                "scope": CheckScope.PARTITION_ALIGNMENT,
                "key": CheckScope.KEY_UNIQUENESS,
                "parity": CheckScope.RECONCILIATION,
                "nullable": CheckScope.VALUE_SANITY,
            }[check_kind],
            file_path=audit.file_path,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            missing_file_paths=(
                (audit.file_path,) if audit.error_type == "file_missing" else ()
            ),
            extra_metadata={
                "partition_key": partition_key,
                "reason_code": (
                    "ready"
                    if not failed_rules
                    else f"idx_factor_pro_{check_kind}_failed"
                ),
                "failed_rule_names": list(failed_rules),
                "expected_code_count": len(audit.expected_codes),
                "observed_code_count": (
                    relation.distinct_code_count if relation is not None else 0
                ),
                "missing_code_count": (
                    len(relation.missing_codes) if relation is not None else 0
                ),
                "extra_code_count": (
                    len(relation.extra_codes) if relation is not None else 0
                ),
                "top_null_ratios": (
                    [
                        {"column": column, "null_ratio": round(ratio, 6)}
                        for column, ratio in relation.null_ratios[:20]
                    ]
                    if relation is not None
                    else []
                ),
                "error_type": audit.error_type,
            },
        ),
        severity=(
            dg.AssetCheckSeverity.WARN
            if check_kind == "nullable"
            else dg.AssetCheckSeverity.ERROR
        ),
    )


def _silver_failed_rules(
    audit: IdxFactorProSilverFileAudit,
    *,
    check_kind: str,
) -> tuple[str, ...]:
    if check_kind == "contract":
        if audit.silver_relation is None:
            return (audit.silver_error_type or "silver_parquet_unreadable",)
        return audit.silver_relation.schema_errors
    if check_kind == "parity":
        rules: tuple[str, ...] = ()
        if audit.raw_relation is None:
            rules += (audit.raw_error_type or "raw_parquet_unreadable",)
        else:
            rules += audit.raw_relation.errors
        if audit.silver_relation is None:
            rules += (audit.silver_error_type or "silver_parquet_unreadable",)
        else:
            rules += audit.silver_relation.scope_errors + audit.silver_relation.key_errors
        if audit.parity is None:
            rules += ("parity_not_evaluated",)
        else:
            rules += audit.parity.source_parity_errors
        return tuple(dict.fromkeys(rules))
    if check_kind == "cast":
        if audit.parity is None:
            return ("cast_integrity_not_evaluated",)
        return audit.parity.cast_integrity_errors
    raise ValueError(f"unsupported idx_factor_pro Silver check kind: {check_kind!r}")


def failed_idx_factor_pro_silver_check_names(
    audit: IdxFactorProSilverFileAudit,
) -> tuple[str, ...]:
    """Return the exact blocking Silver checks that fail for one file audit."""

    return tuple(
        name
        for name, check_kind in zip(
            IDX_FACTOR_PRO_SILVER_CHECKS,
            ("contract", "parity", "cast"),
            strict=True,
        )
        if _silver_failed_rules(audit, check_kind=check_kind)
    )


def evaluate_idx_factor_pro_silver_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb_resource: DuckDBResource,
    check_kind: str,
) -> dg.AssetCheckResult:
    partition_key = _partition_key(context)
    if partition_key is None:
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                checked_row_count=0,
                failed_row_count=0,
                extra_metadata={
                    "reason_code": "single_partition_required",
                    "failed_rule_names": ["single_partition_execution"],
                },
            ),
            severity=dg.AssetCheckSeverity.ERROR,
        )
    audit = audit_idx_factor_pro_silver_partition(
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb_resource,
        partition_key=partition_key,
    )
    failed_rules = _silver_failed_rules(audit, check_kind=check_kind)
    silver_relation = audit.silver_relation
    parity = audit.parity
    checked_row_count = (
        silver_relation.row_count if silver_relation is not None else 0
    )
    failed_row_count = 0
    if check_kind == "contract" and silver_relation is not None:
        failed_row_count = checked_row_count if failed_rules else 0
    elif check_kind == "parity":
        failed_row_count = (
            len(parity.missing_keys) + len(parity.extra_keys)
            if parity is not None
            else checked_row_count
        )
    elif check_kind == "cast":
        failed_row_count = (
            parity.numeric_mismatch_count
            if parity is not None
            else checked_row_count
        )
    return dg.AssetCheckResult(
        passed=not failed_rules,
        metadata=build_check_metadata(
            check_scope={
                "contract": CheckScope.SCHEMA,
                "parity": CheckScope.RECONCILIATION,
                "cast": CheckScope.VALUE_SANITY,
            }[check_kind],
            file_path=audit.silver_file_path,
            input_file_paths=(audit.raw_file_path, audit.silver_file_path),
            missing_file_paths=tuple(
                path
                for path, error_type in (
                    (audit.raw_file_path, audit.raw_error_type),
                    (audit.silver_file_path, audit.silver_error_type),
                )
                if error_type == "file_missing"
            ),
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            extra_metadata={
                "partition_key": partition_key,
                "reason_code": (
                    "ready"
                    if not failed_rules
                    else f"idx_factor_pro_silver_{check_kind}_failed"
                ),
                "failed_rule_names": list(failed_rules),
                "expected_code_count": len(audit.expected_codes),
                "observed_code_count": (
                    silver_relation.distinct_code_count
                    if silver_relation is not None
                    else 0
                ),
                "raw_row_count": (
                    audit.raw_relation.row_count
                    if audit.raw_relation is not None
                    else 0
                ),
                "silver_row_count": checked_row_count,
                "missing_key_count": len(parity.missing_keys) if parity else 0,
                "extra_key_count": len(parity.extra_keys) if parity else 0,
                "numeric_mismatch_count": (
                    parity.numeric_mismatch_count if parity else 0
                ),
                "nonnull_value_lost_count": (
                    parity.raw_nonnull_to_silver_null_count if parity else 0
                ),
                "source_null_filled_count": (
                    parity.raw_null_to_silver_nonnull_count if parity else 0
                ),
                "mismatch_samples": (
                    [
                        {
                            "ts_code": sample[0],
                            "column": sample[1],
                            "raw_value": sample[2],
                            "silver_value": sample[3],
                        }
                        for sample in parity.mismatch_samples[:20]
                    ]
                    if parity is not None
                    else []
                ),
                "raw_error_type": audit.raw_error_type,
                "silver_error_type": audit.silver_error_type,
            },
        ),
        severity=dg.AssetCheckSeverity.ERROR,
    )


def _build_check(
    *,
    name: str,
    check_kind: str,
    blocking: bool,
) -> dg.AssetsDefinition:
    @dg.asset_check(
        asset=raw_tushare_idx_factor_pro,
        name=name,
        partitions_def=cn_major_index_factor_trade_days,
        blocking=blocking,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return evaluate_idx_factor_pro_raw_check(
            context=context,
            lake_root=lake_root,
            duckdb_resource=duckdb,
            check_kind=check_kind,
        )

    return check


(
    raw_tushare_idx_factor_pro_contract_check,
    raw_tushare_idx_factor_pro_partition_scope_check,
    raw_tushare_idx_factor_pro_key_integrity_check,
    raw_tushare_idx_factor_pro_selection_parity_check,
) = tuple(
    _build_check(name=name, check_kind=kind, blocking=True)
    for name, kind in zip(
        IDX_FACTOR_PRO_RAW_CHECKS,
        ("contract", "scope", "key", "parity"),
        strict=True,
    )
)

raw_tushare_idx_factor_pro_nullable_drift_check = _build_check(
    name=IDX_FACTOR_PRO_RAW_NULLABLE_CHECK,
    check_kind="nullable",
    blocking=False,
)


def _build_silver_check(*, name: str, check_kind: str) -> dg.AssetsDefinition:
    @dg.asset_check(
        asset=silver_index_factor_pro,
        name=name,
        partitions_def=cn_major_index_factor_trade_days,
        blocking=True,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return evaluate_idx_factor_pro_silver_check(
            context=context,
            lake_root=lake_root,
            duckdb_resource=duckdb,
            check_kind=check_kind,
        )

    return check


(
    silver_index_factor_pro_contract_check,
    silver_index_factor_pro_source_parity_check,
    silver_index_factor_pro_cast_integrity_check,
) = tuple(
    _build_silver_check(name=name, check_kind=kind)
    for name, kind in zip(
        IDX_FACTOR_PRO_SILVER_CHECKS,
        ("contract", "parity", "cast"),
        strict=True,
    )
)


__all__ = [
    "IdxFactorProRawFileAudit",
    "IdxFactorProSilverFileAudit",
    "audit_idx_factor_pro_raw_partition",
    "audit_idx_factor_pro_silver_partition",
    "evaluate_idx_factor_pro_raw_check",
    "evaluate_idx_factor_pro_silver_check",
    "failed_idx_factor_pro_raw_check_names",
    "failed_idx_factor_pro_silver_check_names",
    "raw_tushare_idx_factor_pro_contract_check",
    "raw_tushare_idx_factor_pro_key_integrity_check",
    "raw_tushare_idx_factor_pro_nullable_drift_check",
    "raw_tushare_idx_factor_pro_partition_scope_check",
    "raw_tushare_idx_factor_pro_selection_parity_check",
    "silver_index_factor_pro_cast_integrity_check",
    "silver_index_factor_pro_contract_check",
    "silver_index_factor_pro_source_parity_check",
]
