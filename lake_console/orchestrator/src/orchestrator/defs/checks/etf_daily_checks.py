"""Blocking Raw checks for ETF daily source datasets."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.etf_daily import (
    raw_tushare_fund_adj,
    raw_tushare_fund_daily,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawAudit,
    EtfDailyRawSpec,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.etf_daily import (
    RAW_FUND_ADJ_CHECKS,
    RAW_FUND_DAILY_CHECKS,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
)


@dataclass(frozen=True, slots=True)
class EtfDailyRawFileAudit:
    spec: EtfDailyRawSpec
    partition_key: str
    file_path: Path
    relation: EtfDailyRawAudit | None
    materialization_metadata: dict[str, Any] | None
    materialization_errors: tuple[str, ...]
    error_type: str | None


def _metadata_scalar(value: Any) -> Any:
    return getattr(value, "value", value)


def _latest_materialization_metadata(
    *,
    instance: dg.DagsterInstance,
    asset_key: str,
    partition_key: str,
) -> dict[str, Any] | None:
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key),
            asset_partitions=[partition_key],
        ),
        limit=1,
    ).records
    if not records:
        return None
    materialization = records[0].asset_materialization
    if materialization is None:
        return None
    return {
        key: _metadata_scalar(value)
        for key, value in materialization.metadata.items()
    }


def _integer_metadata(metadata: dict[str, Any] | None, key: str) -> int | None:
    if metadata is None:
        return None
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _materialization_errors(
    *,
    metadata: dict[str, Any] | None,
    relation: EtfDailyRawAudit | None,
) -> tuple[str, ...]:
    if metadata is None:
        return ("materialization_missing",)
    errors: list[str] = []
    expected_counts = {
        "goldenshare/source_row_count": _integer_metadata(
            metadata, "goldenshare/source_row_count"
        ),
        "goldenshare/normalized_row_count": _integer_metadata(
            metadata, "goldenshare/normalized_row_count"
        ),
        "goldenshare/written_row_count": _integer_metadata(
            metadata, "goldenshare/written_row_count"
        ),
    }
    if any(value is None for value in expected_counts.values()):
        errors.append("materialization_row_counts_missing")
    elif relation is not None and any(
        value != relation.row_count for value in expected_counts.values()
    ):
        errors.append("materialization_row_counts_mismatch")
    return tuple(errors)


def audit_etf_daily_raw_partition(
    *,
    instance: dg.DagsterInstance,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    spec: EtfDailyRawSpec,
    partition_key: str,
) -> EtfDailyRawFileAudit:
    file_path = spec.target_path_builder(lake_root_path, partition_key)
    metadata = _latest_materialization_metadata(
        instance=instance,
        asset_key=spec.asset_key,
        partition_key=partition_key,
    )
    if not file_path.is_file():
        return EtfDailyRawFileAudit(
            spec=spec,
            partition_key=partition_key,
            file_path=file_path,
            relation=None,
            materialization_metadata=metadata,
            materialization_errors=_materialization_errors(
                metadata=metadata,
                relation=None,
            ),
            error_type="file_missing",
        )
    source_count = _integer_metadata(
        metadata,
        "goldenshare/source_row_count",
    )
    try:
        with duckdb_resource.connect() as connection:
            relation = audit_etf_daily_raw_relation(
                connection,
                relation_sql=read_parquet(file_path, hive_partitioning=False),
                spec=spec,
                partition_key=partition_key,
                expected_source_row_count=source_count,
            )
    except Exception as error:  # noqa: BLE001 - checks report corrupt files.
        return EtfDailyRawFileAudit(
            spec=spec,
            partition_key=partition_key,
            file_path=file_path,
            relation=None,
            materialization_metadata=metadata,
            materialization_errors=_materialization_errors(
                metadata=metadata,
                relation=None,
            ),
            error_type=type(error).__name__,
        )
    return EtfDailyRawFileAudit(
        spec=spec,
        partition_key=partition_key,
        file_path=file_path,
        relation=relation,
        materialization_metadata=metadata,
        materialization_errors=_materialization_errors(
            metadata=metadata,
            relation=relation,
        ),
        error_type=None,
    )


def _partition_key(context: dg.AssetCheckExecutionContext) -> str | None:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    return partition_keys[0] if len(partition_keys) == 1 else None


def _failed_rules(
    audit: EtfDailyRawFileAudit,
    *,
    check_kind: str,
) -> tuple[str, ...]:
    relation = audit.relation
    if relation is None:
        return (audit.error_type or "parquet_unreadable",)
    if check_kind == "source_contract":
        return tuple(
            dict.fromkeys(
                relation.source_contract_errors + audit.materialization_errors
            )
        )
    if check_kind == "partition_scope":
        return relation.partition_scope_errors
    if check_kind == "key_integrity":
        return relation.key_integrity_errors
    raise ValueError(f"unsupported ETF daily Raw check kind: {check_kind!r}")


def evaluate_etf_daily_raw_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb_resource: DuckDBResource,
    spec: EtfDailyRawSpec,
    check_kind: str,
) -> dg.AssetCheckResult:
    partition_key = _partition_key(context)
    if partition_key is None:
        return dg.AssetCheckResult(
            passed=False,
            severity=dg.AssetCheckSeverity.ERROR,
            metadata=build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                checked_row_count=0,
                failed_row_count=0,
                extra_metadata={
                    "reason_code": "single_partition_required",
                    "failed_rule_names": ["single_partition_execution"],
                    "next_action": "请只选择一个交易日重新执行检查。",
                },
            ),
        )
    audit = audit_etf_daily_raw_partition(
        instance=context.instance,
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb_resource,
        spec=spec,
        partition_key=partition_key,
    )
    failed_rules = _failed_rules(audit, check_kind=check_kind)
    relation = audit.relation
    checked_row_count = relation.row_count if relation is not None else 0
    if relation is None:
        failed_row_count = 0
    elif check_kind == "partition_scope":
        failed_row_count = relation.invalid_date_count + (
            1 if relation.row_count == 0 else 0
        )
    elif check_kind == "key_integrity":
        failed_row_count = (
            relation.invalid_key_count + relation.duplicate_key_count
        )
    else:
        failed_row_count = checked_row_count if failed_rules else 0
    return dg.AssetCheckResult(
        passed=not failed_rules,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata=build_check_metadata(
            check_scope={
                "source_contract": CheckScope.SCHEMA,
                "partition_scope": CheckScope.PARTITION_ALIGNMENT,
                "key_integrity": CheckScope.KEY_UNIQUENESS,
            }[check_kind],
            file_path=audit.file_path,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            missing_file_paths=(
                (audit.file_path,) if audit.error_type == "file_missing" else ()
            ),
            extra_metadata={
                "asset_key": spec.asset_key,
                "partition_key": partition_key,
                "reason_code": (
                    "ready"
                    if not failed_rules
                    else f"etf_daily_raw_{check_kind}_failed"
                ),
                "failed_rule_names": list(failed_rules),
                "observed_columns": (
                    list(relation.columns) if relation is not None else []
                ),
                "observed_column_types": (
                    list(relation.column_types) if relation is not None else []
                ),
                "invalid_key_count": (
                    relation.invalid_key_count if relation is not None else 0
                ),
                "duplicate_key_count": (
                    relation.duplicate_key_count if relation is not None else 0
                ),
                "invalid_date_count": (
                    relation.invalid_date_count if relation is not None else 0
                ),
                "content_hash": (
                    relation.content_hash if relation is not None else None
                ),
                "failure_samples": (
                    list(relation.failure_samples) if relation is not None else []
                ),
                "error_type": audit.error_type,
                "conclusion": (
                    "Raw 分区结构符合准入合同。"
                    if not failed_rules
                    else "Raw 分区未通过准入检查。"
                ),
                "next_action": (
                    "无需处理。"
                    if not failed_rules
                    else "查看失败规则和样本，修复源端或候选文件后重跑。"
                ),
            },
        ),
    )


def _build_raw_check(
    *,
    asset: dg.AssetsDefinition,
    spec: EtfDailyRawSpec,
    name: str,
    check_kind: str,
) -> dg.AssetsDefinition:
    @dg.asset_check(
        asset=asset,
        name=name,
        partitions_def=cn_a_etf_mins_trade_days,
        blocking=True,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return evaluate_etf_daily_raw_check(
            context=context,
            lake_root=lake_root,
            duckdb_resource=duckdb,
            spec=spec,
            check_kind=check_kind,
        )

    return check


(
    raw_tushare_fund_daily_source_contract_check,
    raw_tushare_fund_daily_partition_scope_check,
    raw_tushare_fund_daily_key_integrity_check,
) = tuple(
    _build_raw_check(
        asset=raw_tushare_fund_daily,
        spec=FUND_DAILY_RAW_SPEC,
        name=name,
        check_kind=kind,
    )
    for name, kind in zip(
        RAW_FUND_DAILY_CHECKS,
        ("source_contract", "partition_scope", "key_integrity"),
        strict=True,
    )
)

(
    raw_tushare_fund_adj_source_contract_check,
    raw_tushare_fund_adj_partition_scope_check,
    raw_tushare_fund_adj_key_integrity_check,
) = tuple(
    _build_raw_check(
        asset=raw_tushare_fund_adj,
        spec=FUND_ADJ_RAW_SPEC,
        name=name,
        check_kind=kind,
    )
    for name, kind in zip(
        RAW_FUND_ADJ_CHECKS,
        ("source_contract", "partition_scope", "key_integrity"),
        strict=True,
    )
)


__all__ = [
    "EtfDailyRawFileAudit",
    "audit_etf_daily_raw_partition",
    "evaluate_etf_daily_raw_check",
    "raw_tushare_fund_adj_key_integrity_check",
    "raw_tushare_fund_adj_partition_scope_check",
    "raw_tushare_fund_adj_source_contract_check",
    "raw_tushare_fund_daily_key_integrity_check",
    "raw_tushare_fund_daily_partition_scope_check",
    "raw_tushare_fund_daily_source_contract_check",
]
