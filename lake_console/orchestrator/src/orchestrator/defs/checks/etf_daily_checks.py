"""Raw and Silver checks for ETF daily source datasets."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.etf_daily import (
    raw_tushare_fund_adj,
    raw_tushare_fund_daily,
    silver_etf_adj_factor,
    silver_etf_daily,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawAudit,
    EtfDailyRawSpec,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    EtfDailyCoverageAudit,
    EtfDailyDomainAudit,
    EtfDailySilverAudit,
    EtfDailySilverSpec,
    EtfDailySourceFilterAudit,
    EtfDailySourceParityAudit,
    audit_etf_daily_basic_coverage,
    audit_etf_daily_domain,
    audit_etf_daily_silver_relation,
    audit_etf_daily_source_filter,
    audit_etf_daily_source_parity,
    validate_etf_daily_basic_reference,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
)
from orchestrator.defs.run_contracts.etf_daily import (
    RAW_FUND_ADJ_CHECKS,
    RAW_FUND_DAILY_CHECKS,
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
    SILVER_ETF_ADJ_FACTOR_COVERAGE_CHECK,
    SILVER_ETF_DAILY_BLOCKING_CHECKS,
    SILVER_ETF_DAILY_COVERAGE_CHECK,
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


@dataclass(frozen=True, slots=True)
class EtfDailySilverFileAudit:
    spec: EtfDailySilverSpec
    partition_key: str
    raw_file_path: Path
    silver_file_path: Path
    basic_reference: EtfBasicSilverSnapshotReference | None
    relation: EtfDailySilverAudit | None
    source_filter: EtfDailySourceFilterAudit | None
    source_parity: EtfDailySourceParityAudit | None
    domain: EtfDailyDomainAudit | None
    coverage: EtfDailyCoverageAudit | None
    materialization_metadata: dict[str, Any] | None
    materialization_errors: tuple[str, ...]
    basic_reference_errors: tuple[str, ...]
    raw_errors: tuple[str, ...]
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
        key: _metadata_scalar(value) for key, value in materialization.metadata.items()
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


def _basic_reference_from_metadata(
    metadata: dict[str, Any] | None,
) -> tuple[EtfBasicSilverSnapshotReference | None, tuple[str, ...]]:
    if metadata is None:
        return None, ("materialization_missing",)
    value = metadata.get("goldenshare/basic_reference")
    if not isinstance(value, Mapping):
        return None, ("basic_reference_metadata_missing",)
    try:
        reference = EtfBasicSilverSnapshotReference.model_validate(dict(value))
        return reference.validate_contract(), ()
    except (TypeError, ValueError) as error:
        return None, (f"basic_reference_metadata_{type(error).__name__}",)


def _silver_materialization_errors(
    *,
    metadata: dict[str, Any] | None,
    relation: EtfDailySilverAudit | None,
    parity: EtfDailySourceParityAudit | None,
    reference: EtfBasicSilverSnapshotReference | None,
) -> tuple[str, ...]:
    if metadata is None:
        return ("materialization_missing",)
    errors: list[str] = []
    expected_integer_values = {
        "dagster/row_count": relation.row_count if relation is not None else None,
        "goldenshare/written_row_count": (
            relation.row_count if relation is not None else None
        ),
        "goldenshare/raw_row_count": (
            parity.raw_row_count if parity is not None else None
        ),
        "goldenshare/selected_row_count": (
            parity.selected_row_count if parity is not None else None
        ),
        "goldenshare/rejected_row_count": (
            parity.rejected_row_count if parity is not None else None
        ),
    }
    for key, expected in expected_integer_values.items():
        observed = _integer_metadata(metadata, key)
        if observed is None:
            errors.append(
                f"{key.removeprefix('goldenshare/').replace('/', '_')}_missing"
            )
        elif expected is not None and observed != expected:
            errors.append(
                f"{key.removeprefix('goldenshare/').replace('/', '_')}_mismatch"
            )
    if relation is not None:
        content_hash = metadata.get("goldenshare/content_hash")
        if not isinstance(content_hash, str):
            errors.append("content_hash_missing")
        elif content_hash != relation.content_hash:
            errors.append("content_hash_mismatch")
    if reference is not None:
        flat_reference_values = {
            "goldenshare/basic_reference_fingerprint": reference.reference_fingerprint,
            "goldenshare/basic_raw_snapshot_hash": reference.raw_snapshot_hash,
            "goldenshare/basic_silver_content_hash": reference.silver_content_hash,
            "goldenshare/basic_raw_uri": reference.raw_uri,
            "goldenshare/basic_silver_uri": reference.silver_uri,
        }
        for key, expected in flat_reference_values.items():
            if metadata.get(key) != expected:
                errors.append(
                    f"{key.removeprefix('goldenshare/').replace('/', '_')}_mismatch"
                )
    return tuple(dict.fromkeys(errors))


def audit_etf_daily_silver_partition(
    *,
    instance: dg.DagsterInstance,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    spec: EtfDailySilverSpec,
    partition_key: str,
    check_kind: str | None = None,
) -> EtfDailySilverFileAudit:
    """Build one shared audit used by all six checks for a Silver asset."""

    supported_kinds = {
        None,
        "contract",
        "source_filter",
        "source_parity",
        "key_integrity",
        "domain",
        "coverage",
    }
    if check_kind not in supported_kinds:
        raise ValueError(f"unsupported ETF daily Silver check kind: {check_kind!r}")
    needs_raw = check_kind in {None, "source_parity", "coverage"}
    needs_basic = check_kind in {None, "source_filter", "source_parity", "coverage"}
    needs_domain = check_kind in {None, "domain"}
    raw_file_path = spec.raw_spec.target_path_builder(lake_root_path, partition_key)
    silver_file_path = spec.target_path_builder(lake_root_path, partition_key)
    metadata = _latest_materialization_metadata(
        instance=instance,
        asset_key=spec.asset_key,
        partition_key=partition_key,
    )
    reference, reference_errors = _basic_reference_from_metadata(metadata)
    required_paths = (
        (raw_file_path, silver_file_path) if needs_raw else (silver_file_path,)
    )
    missing_paths = tuple(path for path in required_paths if not path.is_file())
    if missing_paths:
        return EtfDailySilverFileAudit(
            spec=spec,
            partition_key=partition_key,
            raw_file_path=raw_file_path,
            silver_file_path=silver_file_path,
            basic_reference=reference,
            relation=None,
            source_filter=None,
            source_parity=None,
            domain=None,
            coverage=None,
            materialization_metadata=metadata,
            materialization_errors=_silver_materialization_errors(
                metadata=metadata,
                relation=None,
                parity=None,
                reference=reference,
            ),
            basic_reference_errors=reference_errors,
            raw_errors=("raw_file_missing",) if raw_file_path in missing_paths else (),
            error_type=(
                "silver_file_missing"
                if silver_file_path in missing_paths
                else "raw_file_missing"
            ),
        )
    if needs_basic and reference is not None:
        try:
            reference = validate_etf_daily_basic_reference(
                lake_root_path=lake_root_path,
                duckdb_resource=duckdb_resource,
                basic_reference=reference,
            )
        except Exception as error:  # noqa: BLE001 - check reports invalid reference.
            reference_errors = (
                *reference_errors,
                f"basic_reference_{type(error).__name__}",
            )
    relation: EtfDailySilverAudit | None = None
    source_filter: EtfDailySourceFilterAudit | None = None
    source_parity: EtfDailySourceParityAudit | None = None
    domain: EtfDailyDomainAudit | None = None
    coverage: EtfDailyCoverageAudit | None = None
    raw_errors: tuple[str, ...] = ()
    error_type: str | None = None
    try:
        with duckdb_resource.connect() as connection:
            silver_sql = read_parquet(silver_file_path, hive_partitioning=False)
            relation = audit_etf_daily_silver_relation(
                connection,
                relation_sql=silver_sql,
                spec=spec,
                partition_key=partition_key,
            )
            raw_sql: str | None = None
            if needs_raw:
                raw_sql = read_parquet(raw_file_path, hive_partitioning=False)
                raw_relation = audit_etf_daily_raw_relation(
                    connection,
                    relation_sql=raw_sql,
                    spec=spec.raw_spec,
                    partition_key=partition_key,
                )
                raw_errors = raw_relation.error_codes
            if (
                needs_basic
                and not relation.schema_errors
                and reference is not None
                and not reference_errors
            ):
                basic_sql = read_parquet(
                    Path(reference.silver_uri),
                    hive_partitioning=False,
                )
                if check_kind in {None, "source_filter"}:
                    source_filter = audit_etf_daily_source_filter(
                        connection,
                        silver_relation_sql=silver_sql,
                        basic_relation_sql=basic_sql,
                    )
                if (
                    check_kind in {None, "source_parity"}
                    and raw_sql is not None
                    and not raw_errors
                    and not relation.error_codes
                ):
                    source_parity = audit_etf_daily_source_parity(
                        connection,
                        raw_relation_sql=raw_sql,
                        silver_relation_sql=silver_sql,
                        basic_relation_sql=basic_sql,
                        spec=spec,
                    )
                if (
                    check_kind in {None, "coverage"}
                    and raw_sql is not None
                    and not raw_errors
                    and not relation.error_codes
                ):
                    coverage = audit_etf_daily_basic_coverage(
                        connection,
                        raw_relation_sql=raw_sql,
                        silver_relation_sql=silver_sql,
                        basic_relation_sql=basic_sql,
                        partition_key=partition_key,
                    )
            if needs_domain and not relation.schema_errors:
                domain = audit_etf_daily_domain(
                    connection,
                    silver_relation_sql=silver_sql,
                    spec=spec,
                )
    except Exception as error:  # noqa: BLE001 - checks report corrupt files.
        error_type = type(error).__name__
    return EtfDailySilverFileAudit(
        spec=spec,
        partition_key=partition_key,
        raw_file_path=raw_file_path,
        silver_file_path=silver_file_path,
        basic_reference=reference,
        relation=relation,
        source_filter=source_filter,
        source_parity=source_parity,
        domain=domain,
        coverage=coverage,
        materialization_metadata=metadata,
        materialization_errors=_silver_materialization_errors(
            metadata=metadata,
            relation=relation,
            parity=source_parity,
            reference=reference,
        ),
        basic_reference_errors=tuple(dict.fromkeys(reference_errors)),
        raw_errors=raw_errors,
        error_type=error_type,
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
        failed_row_count = relation.invalid_key_count + relation.duplicate_key_count
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


def _silver_failed_rules(
    audit: EtfDailySilverFileAudit,
    *,
    check_kind: str,
) -> tuple[str, ...]:
    relation = audit.relation
    if relation is None:
        return (audit.error_type or "silver_parquet_unreadable",)
    if check_kind == "contract":
        return tuple(
            dict.fromkeys(
                relation.schema_errors
                + tuple(
                    error
                    for error in audit.materialization_errors
                    if not error.startswith("basic_")
                )
            )
        )
    if check_kind == "source_filter":
        reference_metadata_errors = tuple(
            error
            for error in audit.materialization_errors
            if error.startswith("basic_")
        )
        if audit.source_filter is None:
            return tuple(
                dict.fromkeys(
                    audit.basic_reference_errors
                    + reference_metadata_errors
                    + ("source_filter_not_evaluated",)
                )
            )
        return tuple(
            dict.fromkeys(
                audit.basic_reference_errors
                + reference_metadata_errors
                + audit.source_filter.error_codes
            )
        )
    if check_kind == "source_parity":
        if audit.source_parity is None:
            return tuple(
                dict.fromkeys(
                    audit.raw_errors
                    + audit.basic_reference_errors
                    + ("source_parity_not_evaluated",)
                )
            )
        return tuple(dict.fromkeys(audit.raw_errors + audit.source_parity.error_codes))
    if check_kind == "key_integrity":
        if relation.schema_errors:
            return tuple(dict.fromkeys(relation.schema_errors + ("key_not_evaluated",)))
        return relation.key_errors
    if check_kind == "domain":
        if audit.domain is None:
            return ("domain_not_evaluated",)
        return audit.domain.error_codes
    if check_kind == "coverage":
        if audit.coverage is None:
            return tuple(
                dict.fromkeys(
                    audit.raw_errors
                    + audit.basic_reference_errors
                    + ("coverage_not_evaluated",)
                )
            )
        rules: list[str] = []
        if audit.coverage.missing_expected_code_count:
            rules.append("missing_expected_codes")
        if audit.coverage.silver_extra_code_count:
            rules.append("unexpected_silver_codes")
        return tuple(rules)
    raise ValueError(f"unsupported ETF daily Silver check kind: {check_kind!r}")


def evaluate_etf_daily_silver_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb_resource: DuckDBResource,
    spec: EtfDailySilverSpec,
    check_kind: str,
) -> dg.AssetCheckResult:
    partition_key = _partition_key(context)
    is_coverage = check_kind == "coverage"
    severity = (
        dg.AssetCheckSeverity.WARN if is_coverage else dg.AssetCheckSeverity.ERROR
    )
    if partition_key is None:
        return dg.AssetCheckResult(
            passed=False,
            severity=severity,
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
    audit = audit_etf_daily_silver_partition(
        instance=context.instance,
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb_resource,
        spec=spec,
        partition_key=partition_key,
        check_kind=check_kind,
    )
    failed_rules = _silver_failed_rules(audit, check_kind=check_kind)
    relation = audit.relation
    parity = audit.source_parity
    source_filter = audit.source_filter
    domain = audit.domain
    coverage = audit.coverage
    if is_coverage:
        passed = coverage is not None and not coverage.has_warning
        failed_row_count = (
            coverage.missing_expected_code_count + coverage.silver_extra_code_count
            if coverage is not None
            else 0
        )
    else:
        passed = not failed_rules
        failed_row_count = {
            "contract": relation.row_count if failed_rules and relation else 0,
            "source_filter": (
                source_filter.failure_count
                if source_filter is not None
                else (relation.row_count if relation is not None else 0)
            ),
            "source_parity": (
                parity.expected_minus_silver_count + parity.silver_minus_expected_count
                if parity is not None
                else 0
            ),
            "key_integrity": (
                relation.invalid_key_count + relation.duplicate_key_count
                if relation is not None
                else 0
            ),
            "domain": domain.failed_row_count if domain is not None else 0,
        }[check_kind]
    failure_samples: tuple[dict[str, object], ...] = ()
    if check_kind == "contract" and relation is not None:
        failure_samples = relation.failure_samples
    elif check_kind == "source_filter" and source_filter is not None:
        failure_samples = source_filter.failure_samples
    elif check_kind == "source_parity" and parity is not None:
        failure_samples = parity.failure_samples
    elif check_kind == "domain" and domain is not None:
        failure_samples = domain.failure_samples
    elif check_kind == "coverage" and coverage is not None:
        failure_samples = coverage.failure_samples
    input_file_paths: list[Path] = []
    if check_kind in {"source_parity", "coverage"}:
        input_file_paths.append(audit.raw_file_path)
    if (
        check_kind in {"source_filter", "source_parity", "coverage"}
        and audit.basic_reference is not None
    ):
        input_file_paths.append(Path(audit.basic_reference.silver_uri))
    required_file_paths = [audit.silver_file_path, *input_file_paths]
    return dg.AssetCheckResult(
        passed=passed,
        severity=severity,
        metadata=build_check_metadata(
            check_scope={
                "contract": CheckScope.SCHEMA,
                "source_filter": CheckScope.REFERENTIAL_INTEGRITY,
                "source_parity": CheckScope.RECONCILIATION,
                "key_integrity": CheckScope.KEY_UNIQUENESS,
                "domain": CheckScope.VALUE_SANITY,
                "coverage": CheckScope.REFERENTIAL_INTEGRITY,
            }[check_kind],
            file_path=audit.silver_file_path,
            input_file_paths=tuple(input_file_paths),
            missing_file_paths=tuple(
                path for path in required_file_paths if not path.is_file()
            ),
            checked_row_count=relation.row_count if relation is not None else 0,
            failed_row_count=failed_row_count,
            extra_metadata={
                "asset_key": spec.asset_key,
                "partition_key": partition_key,
                "reason_code": (
                    "ready"
                    if passed
                    else "coverage_warning"
                    if is_coverage and coverage is not None
                    else f"etf_daily_silver_{check_kind}_failed"
                ),
                "failed_rule_names": list(failed_rules),
                "raw_row_count": parity.raw_row_count if parity is not None else 0,
                "selected_row_count": (
                    parity.selected_row_count if parity is not None else 0
                ),
                "rejected_row_count": (
                    parity.rejected_row_count if parity is not None else 0
                ),
                "silver_row_count": relation.row_count if relation is not None else 0,
                "reject_reason_counts": (
                    dict(parity.reason_counts) if parity is not None else {}
                ),
                "domain_failure_counts": (
                    dict(domain.failure_counts) if domain is not None else {}
                ),
                "expected_code_count": (
                    coverage.expected_code_count if coverage is not None else 0
                ),
                "raw_matching_code_count": (
                    coverage.raw_matching_code_count if coverage is not None else 0
                ),
                "missing_expected_code_count": (
                    coverage.missing_expected_code_count if coverage is not None else 0
                ),
                "raw_extra_code_count": (
                    coverage.raw_extra_code_count if coverage is not None else 0
                ),
                "silver_extra_code_count": (
                    coverage.silver_extra_code_count if coverage is not None else 0
                ),
                "basic_reference_fingerprint": (
                    audit.basic_reference.reference_fingerprint
                    if audit.basic_reference is not None
                    else None
                ),
                "basic_raw_snapshot_hash": (
                    audit.basic_reference.raw_snapshot_hash
                    if audit.basic_reference is not None
                    else None
                ),
                "basic_silver_content_hash": (
                    audit.basic_reference.silver_content_hash
                    if audit.basic_reference is not None
                    else None
                ),
                "failure_samples": list(failure_samples),
                "error_type": audit.error_type,
                "conclusion": (
                    "Silver 分区通过当前检查。"
                    if passed
                    else "Silver 分区存在覆盖差异；本检查只告警，不阻断。"
                    if is_coverage and coverage is not None
                    else "Silver 分区未通过准入检查。"
                ),
                "next_action": (
                    "无需处理。"
                    if passed
                    else "查看缺失代码样本，待全历史 profile 后确认最终策略。"
                    if is_coverage and coverage is not None
                    else "查看失败规则和样本，修复输入或候选后重跑。"
                ),
            },
        ),
    )


def _build_silver_check(
    *,
    asset: dg.AssetsDefinition,
    spec: EtfDailySilverSpec,
    name: str,
    check_kind: str,
    blocking: bool,
) -> dg.AssetsDefinition:
    @dg.asset_check(
        asset=asset,
        name=name,
        partitions_def=cn_a_etf_mins_trade_days,
        blocking=blocking,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return evaluate_etf_daily_silver_check(
            context=context,
            lake_root=lake_root,
            duckdb_resource=duckdb,
            spec=spec,
            check_kind=check_kind,
        )

    return check


(
    silver_etf_daily_contract_check,
    silver_etf_daily_source_filter_check,
    silver_etf_daily_source_parity_check,
    silver_etf_daily_key_integrity_check,
    silver_etf_daily_bar_domain_check,
    silver_etf_daily_basic_coverage_check,
) = tuple(
    _build_silver_check(
        asset=silver_etf_daily,
        spec=FUND_DAILY_SILVER_SPEC,
        name=name,
        check_kind=kind,
        blocking=blocking,
    )
    for name, kind, blocking in zip(
        (*SILVER_ETF_DAILY_BLOCKING_CHECKS, SILVER_ETF_DAILY_COVERAGE_CHECK),
        (
            "contract",
            "source_filter",
            "source_parity",
            "key_integrity",
            "domain",
            "coverage",
        ),
        (True, True, True, True, True, False),
        strict=True,
    )
)

(
    silver_etf_adj_factor_contract_check,
    silver_etf_adj_factor_source_filter_check,
    silver_etf_adj_factor_source_parity_check,
    silver_etf_adj_factor_key_integrity_check,
    silver_etf_adj_factor_domain_check,
    silver_etf_adj_factor_basic_coverage_check,
) = tuple(
    _build_silver_check(
        asset=silver_etf_adj_factor,
        spec=FUND_ADJ_SILVER_SPEC,
        name=name,
        check_kind=kind,
        blocking=blocking,
    )
    for name, kind, blocking in zip(
        (
            *SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
            SILVER_ETF_ADJ_FACTOR_COVERAGE_CHECK,
        ),
        (
            "contract",
            "source_filter",
            "source_parity",
            "key_integrity",
            "domain",
            "coverage",
        ),
        (True, True, True, True, True, False),
        strict=True,
    )
)


__all__ = [
    "EtfDailyRawFileAudit",
    "EtfDailySilverFileAudit",
    "audit_etf_daily_raw_partition",
    "audit_etf_daily_silver_partition",
    "evaluate_etf_daily_raw_check",
    "evaluate_etf_daily_silver_check",
    "raw_tushare_fund_adj_key_integrity_check",
    "raw_tushare_fund_adj_partition_scope_check",
    "raw_tushare_fund_adj_source_contract_check",
    "raw_tushare_fund_daily_key_integrity_check",
    "raw_tushare_fund_daily_partition_scope_check",
    "raw_tushare_fund_daily_source_contract_check",
    "silver_etf_adj_factor_basic_coverage_check",
    "silver_etf_adj_factor_contract_check",
    "silver_etf_adj_factor_domain_check",
    "silver_etf_adj_factor_key_integrity_check",
    "silver_etf_adj_factor_source_filter_check",
    "silver_etf_adj_factor_source_parity_check",
    "silver_etf_daily_bar_domain_check",
    "silver_etf_daily_basic_coverage_check",
    "silver_etf_daily_contract_check",
    "silver_etf_daily_key_integrity_check",
    "silver_etf_daily_source_filter_check",
    "silver_etf_daily_source_parity_check",
]
