"""Blocking checks for the latest materialized ETF Basic Raw snapshot."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.etf_basic import (
    EtfBasicRawSnapshotAudit,
    audit_etf_basic_raw_snapshot,
    raw_tushare_etf_basic,
)
from orchestrator.defs.paths import raw_etf_basic_snapshot_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_PAGE_LIMIT,
    ETF_BASIC_SOURCE_API,
    ETF_BASIC_SOURCE_COLUMNS,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata

SOURCE_CONTRACT_DESCRIPTION = (
    "确认最新 ETF Basic Raw 是无业务过滤的 14 字段完整源快照，文件可读、字段类型和行数一致；"
    "失败后查看数量、样本和下一步。"
)
KEY_DOMAIN_DESCRIPTION = (
    "确认最新 ETF Basic Raw 的代码主键唯一且非空，状态、代码后缀和沪深 exchange 对应关系合法；"
    "失败后查看数量、样本和下一步。"
)
CONTENT_HASH_DESCRIPTION = (
    "确认最新 ETF Basic Raw 的内容 hash 可从正式 Parquet 重新计算，并与 materialization 和路径一致；"
    "失败后查看数量、样本和下一步。"
)


@dataclass(frozen=True)
class EtfBasicRawMaterializationReference:
    path: Path | None
    source_row_count: int | None
    raw_snapshot_hash: str | None
    metadata_failures: tuple[str, ...]
    metadata_samples: tuple[dict[str, object], ...]


def _metadata_scalar(value: Any) -> Any:
    return getattr(value, "value", value)


def _latest_materialization_metadata(
    context: dg.AssetCheckExecutionContext,
) -> dict[str, Any] | None:
    event = context.instance.get_latest_materialization_event(raw_tushare_etf_basic.key)
    if event is None or event.dagster_event is None:
        return None
    materialization = event.dagster_event.event_specific_data.materialization
    return {
        key: _metadata_scalar(value) for key, value in materialization.metadata.items()
    }


def build_etf_basic_raw_materialization_reference(
    *,
    metadata: dict[str, Any] | None,
    lake_root_path: Path,
) -> EtfBasicRawMaterializationReference:
    failures: list[str] = []
    samples: list[dict[str, object]] = []
    if metadata is None:
        return EtfBasicRawMaterializationReference(
            path=None,
            source_row_count=None,
            raw_snapshot_hash=None,
            metadata_failures=("materialization_missing",),
            metadata_samples=(),
        )

    uri = metadata.get("dagster/uri")
    materialized_row_count = metadata.get("dagster/row_count")
    source_row_count = metadata.get("goldenshare/source_row_count")
    raw_snapshot_hash = metadata.get("goldenshare/raw_snapshot_hash")
    observed_columns = metadata.get("goldenshare/observed_columns")
    api_name = metadata.get("goldenshare/api_name")
    business_params = metadata.get("goldenshare/business_params")
    fields = metadata.get("goldenshare/fields")
    page_limit = metadata.get("goldenshare/page_limit")
    page_count = metadata.get("goldenshare/page_count")
    observed_at = metadata.get("goldenshare/observed_at")
    status_counts = metadata.get("goldenshare/status_counts")
    suffix_counts = metadata.get("goldenshare/suffix_counts")
    list_date_null_counts = metadata.get("goldenshare/list_date_null_counts")
    write_mode = metadata.get("goldenshare/write_mode")

    if not isinstance(uri, str) or not uri:
        failures.append("uri_missing")
    if (
        not isinstance(source_row_count, int)
        or isinstance(source_row_count, bool)
        or source_row_count <= 0
    ):
        failures.append("source_row_count_invalid")
    if (
        not isinstance(materialized_row_count, int)
        or isinstance(materialized_row_count, bool)
        or materialized_row_count <= 0
    ):
        failures.append("materialized_row_count_invalid")
    elif materialized_row_count != source_row_count:
        failures.append("materialized_source_row_count_mismatch")
    if not isinstance(raw_snapshot_hash, str) or not raw_snapshot_hash:
        failures.append("raw_snapshot_hash_missing")
    if tuple(observed_columns or ()) != ETF_BASIC_SOURCE_COLUMNS:
        failures.append("observed_columns_mismatch")
    if api_name != ETF_BASIC_SOURCE_API:
        failures.append("api_name_mismatch")
    if business_params != {}:
        failures.append("business_params_not_empty")
    if tuple(fields or ()) != ETF_BASIC_SOURCE_COLUMNS:
        failures.append("fields_mismatch")
    if page_limit != ETF_BASIC_PAGE_LIMIT:
        failures.append("page_limit_mismatch")
    if (
        not isinstance(page_count, int)
        or isinstance(page_count, bool)
        or page_count <= 0
    ):
        failures.append("page_count_invalid")
    if not isinstance(observed_at, str) or not observed_at:
        failures.append("observed_at_missing")
    if not isinstance(status_counts, dict):
        failures.append("status_counts_missing")
    if not isinstance(suffix_counts, dict):
        failures.append("suffix_counts_missing")
    if not isinstance(list_date_null_counts, dict):
        failures.append("list_date_null_counts_missing")
    if write_mode not in {"write_new", "reuse_existing"}:
        failures.append("write_mode_invalid")

    path = Path(uri) if isinstance(uri, str) and uri else None
    if isinstance(raw_snapshot_hash, str) and raw_snapshot_hash and path is not None:
        try:
            expected_path = raw_etf_basic_snapshot_path(
                lake_root_path,
                raw_snapshot_hash,
            )
        except ValueError:
            failures.append("raw_snapshot_hash_invalid")
        else:
            if path != expected_path:
                failures.append("uri_hash_path_mismatch")
                samples.append(
                    {
                        "reason_code": "uri_hash_path_mismatch",
                        "expected": str(expected_path),
                        "observed": str(path),
                    }
                )

    return EtfBasicRawMaterializationReference(
        path=path,
        source_row_count=(
            source_row_count
            if isinstance(source_row_count, int)
            and not isinstance(source_row_count, bool)
            else None
        ),
        raw_snapshot_hash=(
            raw_snapshot_hash if isinstance(raw_snapshot_hash, str) else None
        ),
        metadata_failures=tuple(failures),
        metadata_samples=tuple(samples),
    )


def _audit_reference(
    *,
    reference: EtfBasicRawMaterializationReference,
    duckdb_resource: DuckDBResource,
    verify_expected_hash: bool,
) -> EtfBasicRawSnapshotAudit | None:
    if reference.path is None:
        return None
    return audit_etf_basic_raw_snapshot(
        path=reference.path,
        duckdb_resource=duckdb_resource,
        expected_source_row_count=reference.source_row_count,
        expected_snapshot_hash=(
            reference.raw_snapshot_hash if verify_expected_hash else None
        ),
    )


def _result(
    *,
    passed: bool,
    check_scope: CheckScope,
    summary: str,
    next_action: str,
    reason_codes: tuple[str, ...],
    reference: EtfBasicRawMaterializationReference,
    audit: EtfBasicRawSnapshotAudit | None,
) -> dg.AssetCheckResult:
    samples = list(reference.metadata_samples)
    if audit is not None:
        samples.extend(audit.failure_samples)
    failure_counts = {
        reason_code: (
            audit.failure_counts.get(reason_code, 1) if audit is not None else 1
        )
        for reason_code in reason_codes
    }
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=check_scope,
            checked_row_count=(audit.row_count if audit is not None else None),
            failed_row_count=sum(failure_counts.values()),
            file_path=reference.path,
            extra_metadata={
                "summary": summary,
                "next_action": next_action,
                "reason_code": "ok" if not reason_codes else ",".join(reason_codes),
                "reason_codes": list(reason_codes),
                "failure_counts": failure_counts,
                "failure_samples": samples[:20],
                "status_counts": audit.status_counts if audit is not None else {},
                "suffix_counts": audit.suffix_counts if audit is not None else {},
                "list_date_null_counts": (
                    audit.list_date_null_counts if audit is not None else {}
                ),
            },
        ),
    )


@dg.asset_check(
    asset=raw_tushare_etf_basic,
    name="raw_tushare_etf_basic_source_contract_check",
    blocking=True,
    description=SOURCE_CONTRACT_DESCRIPTION,
)
def raw_tushare_etf_basic_source_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    reference = build_etf_basic_raw_materialization_reference(
        metadata=_latest_materialization_metadata(context),
        lake_root_path=lake_root.root(),
    )
    audit = _audit_reference(
        reference=reference,
        duckdb_resource=duckdb,
        verify_expected_hash=False,
    )
    reason_codes = (
        *reference.metadata_failures,
        *(audit.source_contract_failures if audit is not None else ()),
    )
    return _result(
        passed=not reason_codes,
        check_scope=CheckScope.SCHEMA,
        summary=(
            "ETF Basic Raw 源字段、请求范围和行数合同通过。"
            if not reason_codes
            else "ETF Basic Raw 源字段、请求范围或行数合同失败。"
        ),
        next_action=(
            "无需处理，继续执行主键和值域检查。"
            if not reason_codes
            else "查看 reason_codes 和有界样本，修复源请求、字段或文件后重跑 Raw。"
        ),
        reason_codes=reason_codes,
        reference=reference,
        audit=audit,
    )


@dg.asset_check(
    asset=raw_tushare_etf_basic,
    name="raw_tushare_etf_basic_key_domain_check",
    blocking=True,
    description=KEY_DOMAIN_DESCRIPTION,
)
def raw_tushare_etf_basic_key_domain_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    reference = build_etf_basic_raw_materialization_reference(
        metadata=_latest_materialization_metadata(context),
        lake_root_path=lake_root.root(),
    )
    audit = _audit_reference(
        reference=reference,
        duckdb_resource=duckdb,
        verify_expected_hash=False,
    )
    prerequisite_failures = (
        *reference.metadata_failures,
        *(audit.source_contract_failures if audit is not None else ()),
    )
    reason_codes = (
        *prerequisite_failures,
        *(audit.key_domain_failures if audit is not None else ()),
    )
    return _result(
        passed=not reason_codes,
        check_scope=CheckScope.KEY_UNIQUENESS,
        summary=(
            "ETF Basic Raw 主键、状态、后缀和 exchange 值域通过。"
            if not reason_codes
            else "ETF Basic Raw 主键或身份值域失败。"
        ),
        next_action=(
            "无需处理，继续执行内容 hash 检查。"
            if not reason_codes
            else "查看 reason_codes 和有界样本，修复重复代码或未知身份值后重跑 Raw。"
        ),
        reason_codes=reason_codes,
        reference=reference,
        audit=audit,
    )


@dg.asset_check(
    asset=raw_tushare_etf_basic,
    name="raw_tushare_etf_basic_content_hash_check",
    blocking=True,
    description=CONTENT_HASH_DESCRIPTION,
)
def raw_tushare_etf_basic_content_hash_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    reference = build_etf_basic_raw_materialization_reference(
        metadata=_latest_materialization_metadata(context),
        lake_root_path=lake_root.root(),
    )
    audit = _audit_reference(
        reference=reference,
        duckdb_resource=duckdb,
        verify_expected_hash=True,
    )
    reason_codes = (
        *reference.metadata_failures,
        *(audit.source_contract_failures if audit is not None else ()),
        *(audit.key_domain_failures if audit is not None else ()),
        *(audit.content_hash_failures if audit is not None else ()),
    )
    return _result(
        passed=not reason_codes,
        check_scope=CheckScope.RECONCILIATION,
        summary=(
            "ETF Basic Raw 内容 hash 已从正式 Parquet 复算并与路径、metadata 对齐。"
            if not reason_codes
            else "ETF Basic Raw 内容 hash 无法复算或与路径、metadata 不一致。"
        ),
        next_action=(
            "无需处理，该 Raw 版本可进入后续 Silver。"
            if not reason_codes
            else "保留旧正式版本，查看 reason_codes 后修复候选或 metadata 并重跑。"
        ),
        reason_codes=reason_codes,
        reference=reference,
        audit=audit,
    )
