from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.stk_mins_history_check_events import (
    count_succeeded_asset_check_executions,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_bootstrap_events import (
    _latest_materialization,
    _sample_partition_keys,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_macd_kdj_history import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_EVENT_COUNT_PER_FREQ_PARTITION,
    StkMinsQfqMacdKdjHistoryPlan,
    audit_stk_mins_qfq_macd_kdj_files,
    count_indicator_rows_for_partition,
    plan_stk_mins_qfq_macd_kdj_history,
)
from orchestrator.defs.checks import stk_mins_qfq_macd_kdj_checks as macd_kdj_checks
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_FREQS
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)

GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_KEYS = {
    freq: dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_{freq}m")
    for freq in STK_MINS_QFQ_FREQS
}
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_KEYS = {
    freq: dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_state_{freq}m")
    for freq in STK_MINS_QFQ_FREQS
}
GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS = (
    macd_kdj_checks.GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES
)
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECKS = (
    macd_kdj_checks.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES
)
GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS = tuple(
    column.name for column in GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA
)
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMNS = tuple(
    column.name for column in GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA
)


@dataclass(frozen=True)
class StkMinsQfqMacdKdjBootstrapCheckAudit:
    check_name: str
    passed: bool
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class StkMinsQfqMacdKdjBootstrapAssetAudit:
    freq: int
    partition_key: str
    asset_key: dg.AssetKey
    output_uri: Path
    row_count: int
    observed_columns: tuple[str, ...]
    checks: tuple[StkMinsQfqMacdKdjBootstrapCheckAudit, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_check_names(self) -> tuple[str, ...]:
        return tuple(check.check_name for check in self.checks if not check.passed)


@dataclass(frozen=True)
class StkMinsQfqMacdKdjBaselineEventPlan:
    selected_partition_keys: tuple[str, ...]
    selected_freqs: tuple[int, ...]
    selected_years: tuple[str, ...]
    history_plan: StkMinsQfqMacdKdjHistoryPlan
    materialized_partition_counts: Mapping[str, int]
    check_success_counts: Mapping[str, int]

    @property
    def freq_partition_count(self) -> int:
        return len(self.selected_partition_keys) * len(self.selected_freqs)

    @property
    def planned_event_count(self) -> int:
        return (
            self.freq_partition_count
            * GOLD_STK_MINS_QFQ_MACD_KDJ_EVENT_COUNT_PER_FREQ_PARTITION
        )


@dataclass(frozen=True)
class StkMinsQfqMacdKdjBaselineEventReport:
    plan: StkMinsQfqMacdKdjBaselineEventPlan
    dry_run: bool
    asset_audits: tuple[StkMinsQfqMacdKdjBootstrapAssetAudit, ...]
    reported_asset_partitions: tuple[tuple[str, str], ...]
    skipped_ready_asset_partitions: tuple[tuple[str, str], ...]
    reported_event_count: int

    @property
    def failed_asset_partition_count(self) -> int:
        return sum(1 for audit in self.asset_audits if not audit.passed)


@dataclass(frozen=True)
class StkMinsQfqMacdKdjFinalAuditReport:
    selected_partition_count: int
    selected_freqs: tuple[int, ...]
    selected_years: tuple[str, ...]
    file_audit_passed: bool
    planned_target_file_count: int
    existing_target_file_count: int
    materialized_partition_counts: Mapping[str, int]
    check_success_counts: Mapping[str, int]
    check_success_counts_skipped: bool
    sample_readiness: Mapping[str, bool]


def plan_stk_mins_qfq_macd_kdj_baseline_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    duckdb_resource: DuckDBResource | None = None,
    include_check_success_counts: bool = True,
) -> StkMinsQfqMacdKdjBaselineEventPlan:
    history_plan = plan_stk_mins_qfq_macd_kdj_history(
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb_resource,
    )
    materialized_counts: dict[str, int] = {}
    for freq in history_plan.selected_freqs:
        selected_keys = set(history_plan.selected_partition_keys)
        indicator_key = GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_KEYS[freq]
        state_key = GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_KEYS[freq]
        materialized_counts[indicator_key.to_user_string()] = len(
            selected_keys.intersection(instance.get_materialized_partitions(indicator_key))
        )
        materialized_counts[state_key.to_user_string()] = len(
            selected_keys.intersection(instance.get_materialized_partitions(state_key))
        )

    check_counts: dict[str, int] = {}
    if include_check_success_counts:
        for freq in history_plan.selected_freqs:
            _collect_check_success_counts(
                instance,
                check_counts,
                GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_KEYS[freq],
                GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS,
            )
            _collect_check_success_counts(
                instance,
                check_counts,
                GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_KEYS[freq],
                GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECKS,
            )
    return StkMinsQfqMacdKdjBaselineEventPlan(
        selected_partition_keys=history_plan.selected_partition_keys,
        selected_freqs=history_plan.selected_freqs,
        selected_years=history_plan.selected_years,
        history_plan=history_plan,
        materialized_partition_counts=materialized_counts,
        check_success_counts=check_counts,
    )


def report_stk_mins_qfq_macd_kdj_baseline_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb: DuckDBResource,
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    dry_run: bool = False,
    skip_existing_ready: bool = False,
) -> StkMinsQfqMacdKdjBaselineEventReport:
    plan = plan_stk_mins_qfq_macd_kdj_baseline_events(
        instance=instance,
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb,
        include_check_success_counts=False,
    )
    file_audit = audit_stk_mins_qfq_macd_kdj_files(
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb,
    )
    if not file_audit.passed:
        raise RuntimeError(f"Gold qfq MACD/KDJ file audit failed: {file_audit}.")

    audits: list[StkMinsQfqMacdKdjBootstrapAssetAudit] = []
    reported: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    event_count = 0
    for freq in plan.selected_freqs:
        for partition_key in plan.selected_partition_keys:
            indicator_key = GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_KEYS[freq]
            state_key = GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_KEYS[freq]
            if skip_existing_ready and _asset_ready(
                instance,
                indicator_key,
                GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS,
                partition_key,
            ) and _asset_ready(
                instance,
                state_key,
                GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECKS,
                partition_key,
            ):
                skipped.append((indicator_key.to_user_string(), partition_key))
                skipped.append((state_key.to_user_string(), partition_key))
                continue
            indicator_audit = _audit_indicator_asset_partition(
                lake_root=lake_root,
                freq=freq,
                partition_key=partition_key,
            )
            state_audit = _audit_state_asset_partition(
                lake_root=lake_root,
                freq=freq,
                partition_key=partition_key,
            )
            audits.extend((indicator_audit, state_audit))
            failed = tuple(audit for audit in (indicator_audit, state_audit) if not audit.passed)
            if failed:
                details = {
                    audit.asset_key.to_user_string(): audit.failed_check_names
                    for audit in failed
                }
                raise RuntimeError(
                    "Gold qfq MACD/KDJ baseline event audit failed: "
                    f"freq={freq}, partition={partition_key}, failed={details}."
                )
            if not dry_run:
                for audit in (indicator_audit, state_audit):
                    event_count += _report_asset_partition_events(instance, audit)
                    reported.append((audit.asset_key.to_user_string(), partition_key))
    return StkMinsQfqMacdKdjBaselineEventReport(
        plan=plan,
        dry_run=dry_run,
        asset_audits=tuple(audits),
        reported_asset_partitions=tuple(reported),
        skipped_ready_asset_partitions=tuple(skipped),
        reported_event_count=0 if dry_run else event_count,
    )


def audit_stk_mins_qfq_macd_kdj_final_state(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    duckdb_resource: DuckDBResource | None = None,
    include_check_success_counts: bool = True,
) -> StkMinsQfqMacdKdjFinalAuditReport:
    plan = plan_stk_mins_qfq_macd_kdj_baseline_events(
        instance=instance,
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb_resource,
        include_check_success_counts=include_check_success_counts,
    )
    file_audit = audit_stk_mins_qfq_macd_kdj_files(
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb_resource,
    )
    sample_readiness: dict[str, bool] = {}
    for partition_key in _sample_partition_keys(plan.selected_partition_keys):
        for freq in plan.selected_freqs:
            indicator_key = GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_KEYS[freq]
            state_key = GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_KEYS[freq]
            sample_readiness[f"{indicator_key.to_user_string()}:{partition_key}"] = (
                _asset_ready(
                    instance,
                    indicator_key,
                    GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS,
                    partition_key,
                )
            )
            sample_readiness[f"{state_key.to_user_string()}:{partition_key}"] = (
                _asset_ready(
                    instance,
                    state_key,
                    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECKS,
                    partition_key,
                )
            )
    return StkMinsQfqMacdKdjFinalAuditReport(
        selected_partition_count=len(plan.selected_partition_keys),
        selected_freqs=plan.selected_freqs,
        selected_years=plan.selected_years,
        file_audit_passed=file_audit.passed,
        planned_target_file_count=plan.history_plan.planned_target_file_count,
        existing_target_file_count=plan.history_plan.existing_target_file_count,
        materialized_partition_counts=plan.materialized_partition_counts,
        check_success_counts=plan.check_success_counts,
        check_success_counts_skipped=not include_check_success_counts,
        sample_readiness=sample_readiness,
    )


def _audit_indicator_asset_partition(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
) -> StkMinsQfqMacdKdjBootstrapAssetAudit:
    row_count, paths = count_indicator_rows_for_partition(
        lake_root=lake_root,
        freq=freq,
        partition_key=partition_key,
    )
    output_uri = gold_stk_mins_qfq_macd_kdj_path(
        lake_root,
        freq,
        "{ts_code}",
        partition_key[:4],
    ).parents[2]
    check_results = (
        (
            macd_kdj_checks.GOLD_STK_MINS_QFQ_MACD_KDJ_CONTRACT_CHECK,
            macd_kdj_checks._indicator_file_exists_and_schema_result(
                lake_root=lake_root,
                freq=freq,
                partition_key=partition_key,
            ),
        ),
        (
            macd_kdj_checks.GOLD_STK_MINS_QFQ_MACD_KDJ_SOURCE_COVERAGE_CHECK,
            macd_kdj_checks._indicator_source_coverage_result(
                lake_root=lake_root,
                freq=freq,
                partition_key=partition_key,
            ),
        ),
    )
    return StkMinsQfqMacdKdjBootstrapAssetAudit(
        freq=freq,
        partition_key=partition_key,
        asset_key=GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_KEYS[freq],
        output_uri=output_uri,
        row_count=row_count,
        observed_columns=GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS if paths else (),
        checks=_check_audits(check_results),
    )


def _audit_state_asset_partition(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
) -> StkMinsQfqMacdKdjBootstrapAssetAudit:
    state_path = gold_stk_mins_qfq_macd_kdj_state_path(lake_root, freq, partition_key)
    row_count = _state_row_count(state_path) if state_path.exists() else 0
    check_results = (
        (
            macd_kdj_checks.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_FILE_EXISTS_AND_SCHEMA_CHECK,
            macd_kdj_checks._state_file_exists_and_schema_result(
                lake_root=lake_root,
                freq=freq,
                partition_key=partition_key,
            ),
        ),
        (
            macd_kdj_checks.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_LATEST_COVERAGE_CHECK,
            macd_kdj_checks._state_latest_coverage_result(
                lake_root=lake_root,
                freq=freq,
                partition_key=partition_key,
            ),
        ),
    )
    return StkMinsQfqMacdKdjBootstrapAssetAudit(
        freq=freq,
        partition_key=partition_key,
        asset_key=GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_KEYS[freq],
        output_uri=state_path,
        row_count=row_count,
        observed_columns=GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMNS if state_path.exists() else (),
        checks=_check_audits(check_results),
    )


def _check_audits(
    check_results: Sequence[tuple[str, dg.AssetCheckResult]],
) -> tuple[StkMinsQfqMacdKdjBootstrapCheckAudit, ...]:
    return tuple(
        StkMinsQfqMacdKdjBootstrapCheckAudit(
            check_name=check_name,
            passed=bool(result.passed),
            metadata=result.metadata or {},
        )
        for check_name, result in check_results
    )


def _report_asset_partition_events(
    instance: dg.DagsterInstance,
    audit: StkMinsQfqMacdKdjBootstrapAssetAudit,
) -> int:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=audit.asset_key,
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.output_uri,
                row_count=audit.row_count,
                observed_columns=audit.observed_columns,
                extra_metadata={
                    "source_method": "stk_mins_qfq_macd_kdj_history_generation",
                    "baseline_event_tracking": True,
                    "freq": audit.freq,
                    "partition_key": audit.partition_key,
                },
            ),
        )
    )
    materialization = _latest_materialization(
        instance,
        audit.asset_key,
        audit.partition_key,
    )
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    event_count = 1
    for check in audit.checks:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=audit.asset_key,
                check_name=check.check_name,
                passed=check.passed,
                metadata=check.metadata,
                blocking=True,
                partition=audit.partition_key,
                target_materialization_data=target,
            )
        )
        event_count += 1
    return event_count


def _asset_ready(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    check_names: Sequence[str],
    partition_key: str,
) -> bool:
    return asset_readiness_status(
        instance,
        AssetReadinessSpec(asset_key, tuple(check_names)),
        partition_key=partition_key,
    ).ready


def _state_row_count(path: Path) -> int:
    with connect_configured_duckdb() as connection:
        return int(
            connection.execute(
                f"SELECT count(*) FROM {read_parquet(path, hive_partitioning=False)}"
            ).fetchone()[0]
        )


def _collect_check_success_counts(
    instance: dg.DagsterInstance,
    result: dict[str, int],
    asset_key: dg.AssetKey,
    check_names: Sequence[str],
) -> None:
    for check_name in check_names:
        key = f"{asset_key.to_user_string()}:{check_name}"
        result[key] = count_succeeded_asset_check_executions(
            instance,
            dg.AssetCheckKey(asset_key, check_name),
        )
