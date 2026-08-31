"""Partition-bound blocking checks for ETF minute Raw and Silver assets."""

from collections.abc import Iterator, Mapping

import dagster as dg

from orchestrator.defs.asset_guards.etf_mins_lake_readiness import (
    EtfMinsRawMaterializationEvidence,
    EtfMinsSilverMaterializationEvidence,
    audit_etf_mins_raw_file_contract,
    audit_etf_mins_raw_request_scope,
    audit_etf_mins_silver_file_contract,
    audit_etf_mins_silver_raw_equivalence,
    evaluate_etf_mins_raw_bar_domain,
    load_etf_mins_raw_materialization_evidence,
    load_etf_mins_silver_materialization_evidence,
)
from orchestrator.defs.assets.etf_mins import (
    RAW_ETF_MINS_ASSETS,
    SILVER_ETF_MINS_ASSETS,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_ASSET_FREQS,
    ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_MINS_RAW_APPROVED_POLICY_VERSION,
    ETF_MINS_SOURCE_FREQS,
    asset_freq_for_etf_mins_source_freq,
    raw_etf_mins_check_names,
    silver_etf_mins_check_names,
    source_freq_for_etf_mins_asset_freq,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata

RAW_FILE_CONTRACT_DESCRIPTION = (
    "确认 ETF 分钟 Raw 正式文件可读、11 字段类型准确，且日期、频率、非空主键和唯一键合法；"
    "失败不删除 Raw，修复文件或 materialization 绑定后重跑 checks。"
)
RAW_REQUEST_SCOPE_DESCRIPTION = (
    "用该 Raw materialization 冻结的 ETF Basic Silver 重算代码集合和 exchange 身份；"
    "身份污染或未知新增代码会阻断，missing 留给同日五频 N3 判定。"
)
RAW_BAR_DOMAIN_DESCRIPTION = (
    "同一次 DuckDB evaluation 审计同日五频价格、成交量额、OHLC、分钟网格、内部空洞和边界；"
    "批准的 WARN 通过，blocked 阻断 Raw readiness 和 Silver。"
)
SILVER_FILE_CONTRACT_DESCRIPTION = "确认 ETF 分钟 Silver 正式文件可读、11 字段类型准确，且路径日期、频率和主键合同合法。"
SILVER_RAW_EQUIVALENCE_DESCRIPTION = "确认 ETF 分钟 Silver 与其 materialization 绑定的当前 Raw 在行数、主键和 11 字段上双向完全等价。"


def _partition_key(context: dg.AssetCheckExecutionContext) -> str:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    if len(partition_keys) != 1:
        raise RuntimeError("etf_mins_check_requires_one_partition.")
    return partition_keys[0]


def _failure_result(
    *,
    scope: CheckScope,
    reason_code: str,
    summary: str,
    next_action: str,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=scope,
            failed_row_count=1,
            extra_metadata={
                "summary": summary,
                "next_action": next_action,
                "reason_code": reason_code,
                "reason_codes": [reason_code],
            },
        ),
    )


def _contract_result(
    *,
    scope: CheckScope,
    failures: tuple[tuple[str, int], ...],
    checked_row_count: int,
    file_path: object,
    ready_summary: str,
    failure_summary: str,
    failure_next_action: str,
    extra_metadata: Mapping[str, object] | None = None,
) -> dg.AssetCheckResult:
    passed = not failures
    reason_codes = tuple(name for name, _ in failures)
    failure_counts = dict(failures)
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=scope,
            file_path=file_path,  # type: ignore[arg-type]
            checked_row_count=checked_row_count,
            failed_row_count=sum(failure_counts.values()),
            extra_metadata={
                "summary": ready_summary if passed else failure_summary,
                "next_action": (
                    "无需处理，继续执行下一项 blocking check。"
                    if passed
                    else failure_next_action
                ),
                "reason_code": "ok" if passed else ",".join(reason_codes),
                "reason_codes": list(reason_codes),
                "failure_counts": failure_counts,
                **dict(extra_metadata or {}),
            },
        ),
    )


def _load_raw_evidence(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    asset: dg.AssetsDefinition,
    source_freq: str,
) -> EtfMinsRawMaterializationEvidence:
    return load_etf_mins_raw_materialization_evidence(
        instance=context.instance,
        lake_root=lake_root.root(),
        asset_key=asset.key,
        partition_key=_partition_key(context),
        source_freq=source_freq,
    )


def _build_raw_file_contract_check(
    *,
    asset: dg.AssetsDefinition,
    minutes: int,
) -> dg.AssetChecksDefinition:
    source_freq = source_freq_for_etf_mins_asset_freq(minutes)
    check_name = raw_etf_mins_check_names(minutes)[0]

    @dg.asset_check(
        asset=asset,
        name=check_name,
        partitions_def=cn_a_etf_mins_trade_days,
        blocking=True,
        description=RAW_FILE_CONTRACT_DESCRIPTION,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        try:
            evidence = _load_raw_evidence(
                context=context,
                lake_root=lake_root,
                asset=asset,
                source_freq=source_freq,
            )
            with duckdb.connect() as connection:
                failures = audit_etf_mins_raw_file_contract(
                    connection=connection,
                    evidence=evidence,
                )
        except Exception as error:  # noqa: BLE001 - checks report corrupt evidence.
            return _failure_result(
                scope=CheckScope.SCHEMA,
                reason_code=str(error) or type(error).__name__,
                summary="ETF 分钟 Raw 文件或 materialization 绑定不可验证。",
                next_action="保留 Raw，检查正式路径、metadata 和文件 hash 后重跑 checks。",
            )
        return _contract_result(
            scope=CheckScope.SCHEMA,
            failures=failures,
            checked_row_count=evidence.row_count,
            file_path=evidence.raw_path,
            ready_summary="ETF 分钟 Raw 文件、字段、日期、频率和主键合同通过。",
            failure_summary="ETF 分钟 Raw 文件合同失败。",
            failure_next_action="保留 Raw，按 failure_counts 修复合同问题后重跑 checks。",
            extra_metadata={"raw_sha256": evidence.raw_sha256},
        )

    return check


def _build_raw_request_scope_check(
    *,
    asset: dg.AssetsDefinition,
    minutes: int,
) -> dg.AssetChecksDefinition:
    source_freq = source_freq_for_etf_mins_asset_freq(minutes)
    check_name = raw_etf_mins_check_names(minutes)[1]

    @dg.asset_check(
        asset=asset,
        name=check_name,
        partitions_def=cn_a_etf_mins_trade_days,
        blocking=True,
        description=RAW_REQUEST_SCOPE_DESCRIPTION,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        try:
            evidence = _load_raw_evidence(
                context=context,
                lake_root=lake_root,
                asset=asset,
                source_freq=source_freq,
            )
            with duckdb.connect() as connection:
                validation, failure_codes = audit_etf_mins_raw_request_scope(
                    connection=connection,
                    evidence=evidence,
                )
        except Exception as error:  # noqa: BLE001 - checks report corrupt evidence.
            return _failure_result(
                scope=CheckScope.REFERENTIAL_INTEGRITY,
                reason_code=str(error) or type(error).__name__,
                summary="ETF 分钟 Raw 无法用冻结的 Basic 引用重算请求范围。",
                next_action="检查同版 Basic 文件、hash 和 Raw metadata 绑定后重跑 checks。",
            )
        failures = tuple((reason_code, 1) for reason_code in failure_codes)
        samples = tuple(
            dict.fromkeys(
                (
                    *validation.missing_samples,
                    *validation.known_non_required_samples,
                    *validation.retained_legacy_samples,
                    *validation.unexplained_new_samples,
                )
            )
        )[:ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT]
        return _contract_result(
            scope=CheckScope.REFERENTIAL_INTEGRITY,
            failures=failures,
            checked_row_count=evidence.row_count,
            file_path=evidence.raw_path,
            ready_summary="ETF 分钟 Raw 与冻结 Basic 的请求范围和代码身份一致。",
            failure_summary="ETF 分钟 Raw 的冻结 Basic 范围或代码身份校验失败。",
            failure_next_action="查看集合计数与 samples，修复 Basic/Raw 绑定或未知代码后重跑。",
            extra_metadata={
                "raw_sha256": evidence.raw_sha256,
                "basic_reference_fingerprint": (
                    evidence.basic_reference.reference_fingerprint
                ),
                "expected_count": validation.expected_count,
                "present_count": validation.present_count,
                "missing_count": validation.missing_count,
                "known_non_required_present_count": (
                    validation.known_non_required_present_count
                ),
                "retained_legacy_count": validation.retained_legacy_count,
                "unexplained_new_count": validation.unexplained_new_count,
                "samples": list(samples),
            },
        )

    return check


RAW_ETF_MINS_FILE_CONTRACT_CHECKS = tuple(
    _build_raw_file_contract_check(asset=asset, minutes=minutes)
    for asset, minutes in zip(
        RAW_ETF_MINS_ASSETS,
        ETF_MINS_ASSET_FREQS,
        strict=True,
    )
)
RAW_ETF_MINS_REQUEST_SCOPE_CHECKS = tuple(
    _build_raw_request_scope_check(asset=asset, minutes=minutes)
    for asset, minutes in zip(
        RAW_ETF_MINS_ASSETS,
        ETF_MINS_ASSET_FREQS,
        strict=True,
    )
)

(
    raw_etf_mins_1m_file_contract_check,
    raw_etf_mins_5m_file_contract_check,
    raw_etf_mins_15m_file_contract_check,
    raw_etf_mins_30m_file_contract_check,
    raw_etf_mins_60m_file_contract_check,
) = RAW_ETF_MINS_FILE_CONTRACT_CHECKS

(
    raw_etf_mins_1m_request_scope_check,
    raw_etf_mins_5m_request_scope_check,
    raw_etf_mins_15m_request_scope_check,
    raw_etf_mins_30m_request_scope_check,
    raw_etf_mins_60m_request_scope_check,
) = RAW_ETF_MINS_REQUEST_SCOPE_CHECKS

_BAR_DOMAIN_SPECS = tuple(
    dg.AssetCheckSpec(
        name=raw_etf_mins_check_names(minutes)[2],
        asset=asset,
        partitions_def=cn_a_etf_mins_trade_days,
        blocking=True,
        description=RAW_BAR_DOMAIN_DESCRIPTION,
    )
    for asset, minutes in zip(
        RAW_ETF_MINS_ASSETS,
        ETF_MINS_ASSET_FREQS,
        strict=True,
    )
)


@dg.multi_asset_check(
    name="raw_etf_mins_bar_domain_checks",
    specs=_BAR_DOMAIN_SPECS,
    can_subset=False,
    description=RAW_BAR_DOMAIN_DESCRIPTION,
)
def raw_etf_mins_bar_domain_checks(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> Iterator[dg.AssetCheckResult]:
    try:
        evidences = tuple(
            _load_raw_evidence(
                context=context,
                lake_root=lake_root,
                asset=asset,
                source_freq=source_freq,
            )
            for asset, source_freq in zip(
                RAW_ETF_MINS_ASSETS,
                ETF_MINS_SOURCE_FREQS,
                strict=True,
            )
        )
        results = evaluate_etf_mins_raw_bar_domain(
            duckdb=duckdb,
            evidences=evidences,
            approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
        )
    except Exception as error:  # noqa: BLE001 - emit all five failed evaluations.
        reason_code = str(error) or type(error).__name__
        for asset, minutes in zip(
            RAW_ETF_MINS_ASSETS,
            ETF_MINS_ASSET_FREQS,
            strict=True,
        ):
            yield dg.AssetCheckResult(
                passed=False,
                asset_key=asset.key,
                check_name=raw_etf_mins_check_names(minutes)[2],
                metadata=build_check_metadata(
                    check_scope=CheckScope.VALUE_SANITY,
                    failed_row_count=1,
                    extra_metadata={
                        "summary": "ETF 分钟同日五频 N3 无法完成。",
                        "next_action": "保留 Raw，修复五频文件或绑定后整体重跑 bar_domain。",
                        "reason_code": reason_code,
                        "reason_codes": [reason_code],
                    },
                ),
            )
        return

    for result in results:
        issue_counts = dict(result.issue_counts)
        blocking_codes = tuple(
            reason
            for reason in result.reason_codes
            if result.decision == "blocked" and issue_counts.get(reason, 0) > 0
        )
        yield dg.AssetCheckResult(
            passed=result.silver_eligible,
            asset_key=result.asset_key,
            check_name=raw_etf_mins_check_names(
                asset_freq_for_etf_mins_source_freq(result.source_freq)
            )[2],
            metadata=build_check_metadata(
                check_scope=CheckScope.VALUE_SANITY,
                checked_row_count=None,
                failed_row_count=sum(issue_counts[reason] for reason in blocking_codes),
                file_path=next(
                    evidence.raw_path
                    for evidence in evidences
                    if evidence.source_freq == result.source_freq
                ),
                extra_metadata={
                    "summary": (
                        "ETF 分钟 N3 已按批准 policy 准入。"
                        if result.silver_eligible
                        else "ETF 分钟 N3 判定 blocked，禁止进入 Silver。"
                    ),
                    "next_action": (
                        "无需处理；WARN 原因已记录，可继续 Silver。"
                        if result.silver_eligible
                        else "查看 issue_counts 与 samples，确认并处理数据事实后整体重跑。"
                    ),
                    "reason_code": (
                        "ok"
                        if not result.reason_codes
                        else ",".join(result.reason_codes)
                    ),
                    "raw_sha256": result.raw_sha256,
                    "gap_policy_version": result.gap_policy_version,
                    "gap_policy_hash": result.gap_policy_hash,
                    "bar_domain_decision": result.decision,
                    "bar_domain_reason_codes": list(result.reason_codes),
                    "issue_counts": issue_counts,
                    "samples": list(result.samples),
                },
            ),
        )


def _load_silver_evidence(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    asset: dg.AssetsDefinition,
    source_freq: str,
) -> EtfMinsSilverMaterializationEvidence:
    return load_etf_mins_silver_materialization_evidence(
        instance=context.instance,
        lake_root=lake_root.root(),
        asset_key=asset.key,
        partition_key=_partition_key(context),
        source_freq=source_freq,
    )


def _build_silver_file_contract_check(
    *,
    asset: dg.AssetsDefinition,
    minutes: int,
) -> dg.AssetChecksDefinition:
    source_freq = source_freq_for_etf_mins_asset_freq(minutes)

    @dg.asset_check(
        asset=asset,
        name=silver_etf_mins_check_names(minutes)[0],
        partitions_def=cn_a_etf_mins_trade_days,
        blocking=True,
        description=SILVER_FILE_CONTRACT_DESCRIPTION,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        try:
            evidence = _load_silver_evidence(
                context=context,
                lake_root=lake_root,
                asset=asset,
                source_freq=source_freq,
            )
            with duckdb.connect() as connection:
                failures = audit_etf_mins_silver_file_contract(
                    connection=connection,
                    evidence=evidence,
                )
        except Exception as error:  # noqa: BLE001 - checks report corrupt evidence.
            return _failure_result(
                scope=CheckScope.SCHEMA,
                reason_code=str(error) or type(error).__name__,
                summary="ETF 分钟 Silver 文件或 materialization 绑定不可验证。",
                next_action="检查正式路径、metadata 和文件 hash 后重跑 Silver/checks。",
            )
        return _contract_result(
            scope=CheckScope.SCHEMA,
            failures=failures,
            checked_row_count=evidence.row_count,
            file_path=evidence.silver_path,
            ready_summary="ETF 分钟 Silver 文件、字段、日期、频率和主键合同通过。",
            failure_summary="ETF 分钟 Silver 文件合同失败。",
            failure_next_action="保留现有文件，按 failure_counts 排查后重跑。",
            extra_metadata={"silver_sha256": evidence.silver_sha256},
        )

    return check


def _build_silver_raw_equivalence_check(
    *,
    silver_asset: dg.AssetsDefinition,
    raw_asset: dg.AssetsDefinition,
    minutes: int,
) -> dg.AssetChecksDefinition:
    source_freq = source_freq_for_etf_mins_asset_freq(minutes)

    @dg.asset_check(
        asset=silver_asset,
        name=silver_etf_mins_check_names(minutes)[1],
        partitions_def=cn_a_etf_mins_trade_days,
        blocking=True,
        description=SILVER_RAW_EQUIVALENCE_DESCRIPTION,
    )
    def check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        try:
            silver_evidence = _load_silver_evidence(
                context=context,
                lake_root=lake_root,
                asset=silver_asset,
                source_freq=source_freq,
            )
            raw_evidence = _load_raw_evidence(
                context=context,
                lake_root=lake_root,
                asset=raw_asset,
                source_freq=source_freq,
            )
            with duckdb.connect() as connection:
                failures = audit_etf_mins_silver_raw_equivalence(
                    connection=connection,
                    silver_evidence=silver_evidence,
                    raw_evidence=raw_evidence,
                )
        except Exception as error:  # noqa: BLE001 - checks report corrupt evidence.
            return _failure_result(
                scope=CheckScope.RECONCILIATION,
                reason_code=str(error) or type(error).__name__,
                summary="ETF 分钟 Silver 无法与绑定的 Raw 对账。",
                next_action="检查 Raw/Silver materialization、hash 和正式文件后重跑。",
            )
        return _contract_result(
            scope=CheckScope.RECONCILIATION,
            failures=failures,
            checked_row_count=silver_evidence.row_count,
            file_path=silver_evidence.silver_path,
            ready_summary="ETF 分钟 Silver 与绑定 Raw 的 11 字段和主键双向等价。",
            failure_summary="ETF 分钟 Silver 与绑定 Raw 不等价。",
            failure_next_action="禁止覆盖；查看双向差集计数并确认冲突来源。",
            extra_metadata={
                "raw_uri": str(raw_evidence.raw_path),
                "raw_sha256": raw_evidence.raw_sha256,
                "silver_sha256": silver_evidence.silver_sha256,
            },
        )

    return check


SILVER_ETF_MINS_FILE_CONTRACT_CHECKS = tuple(
    _build_silver_file_contract_check(asset=asset, minutes=minutes)
    for asset, minutes in zip(
        SILVER_ETF_MINS_ASSETS,
        ETF_MINS_ASSET_FREQS,
        strict=True,
    )
)
SILVER_ETF_MINS_RAW_EQUIVALENCE_CHECKS = tuple(
    _build_silver_raw_equivalence_check(
        silver_asset=silver_asset,
        raw_asset=raw_asset,
        minutes=minutes,
    )
    for silver_asset, raw_asset, minutes in zip(
        SILVER_ETF_MINS_ASSETS,
        RAW_ETF_MINS_ASSETS,
        ETF_MINS_ASSET_FREQS,
        strict=True,
    )
)

(
    silver_etf_mins_1m_file_contract_check,
    silver_etf_mins_5m_file_contract_check,
    silver_etf_mins_15m_file_contract_check,
    silver_etf_mins_30m_file_contract_check,
    silver_etf_mins_60m_file_contract_check,
) = SILVER_ETF_MINS_FILE_CONTRACT_CHECKS

(
    silver_etf_mins_1m_raw_equivalence_check,
    silver_etf_mins_5m_raw_equivalence_check,
    silver_etf_mins_15m_raw_equivalence_check,
    silver_etf_mins_30m_raw_equivalence_check,
    silver_etf_mins_60m_raw_equivalence_check,
) = SILVER_ETF_MINS_RAW_EQUIVALENCE_CHECKS

RAW_ETF_MINS_CHECK_DEFINITIONS = (
    *RAW_ETF_MINS_FILE_CONTRACT_CHECKS,
    *RAW_ETF_MINS_REQUEST_SCOPE_CHECKS,
    raw_etf_mins_bar_domain_checks,
)
SILVER_ETF_MINS_CHECK_DEFINITIONS = (
    *SILVER_ETF_MINS_FILE_CONTRACT_CHECKS,
    *SILVER_ETF_MINS_RAW_EQUIVALENCE_CHECKS,
)

__all__ = [
    "RAW_ETF_MINS_CHECK_DEFINITIONS",
    "RAW_ETF_MINS_FILE_CONTRACT_CHECKS",
    "RAW_ETF_MINS_REQUEST_SCOPE_CHECKS",
    "SILVER_ETF_MINS_CHECK_DEFINITIONS",
    "SILVER_ETF_MINS_FILE_CONTRACT_CHECKS",
    "SILVER_ETF_MINS_RAW_EQUIVALENCE_CHECKS",
    "raw_etf_mins_bar_domain_checks",
]
