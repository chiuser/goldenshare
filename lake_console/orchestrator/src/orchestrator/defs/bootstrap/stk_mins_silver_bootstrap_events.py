from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.stk_mins_migration import _check_success_count
from orchestrator.defs.bootstrap.stk_mins_silver_history import (
    STK_MINS_SILVER_HISTORY_START_DATE,
    all_silver_partition_keys,
    discover_silver_stk_mins_partitions,
)
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import count_parquet_query, describe_parquet_query
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, silver_stk_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)


SILVER_STK_MINS_ASSET_KEYS = {
    freq: dg.AssetKey(f"silver_stk_mins_{freq}m") for freq in STK_MINS_FREQS
}
SILVER_STK_MINS_CHECKS = stk_mins_checks.SILVER_STK_MINS_CHECK_NAMES


@dataclass(frozen=True)
class StkMinsSilverBootstrapCheckAudit:
    check_name: str
    passed: bool
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class StkMinsSilverBootstrapPartitionAudit:
    freq: int
    partition_key: str
    silver_file_path: Path
    passed: bool
    row_count: int | None
    observed_columns: tuple[str, ...]
    checks: tuple[StkMinsSilverBootstrapCheckAudit, ...]

    @property
    def failed_check_names(self) -> tuple[str, ...]:
        return tuple(check.check_name for check in self.checks if not check.passed)


@dataclass(frozen=True)
class StkMinsSilverBootstrapEventPlan:
    selected_partition_keys: tuple[str, ...]
    silver_partition_counts: Mapping[int, int]
    registered_partition_count: int
    unregistered_selected_partition_keys: tuple[str, ...]
    missing_silver_asset_partitions: tuple[tuple[int, str], ...]
    partition_audits: tuple[StkMinsSilverBootstrapPartitionAudit, ...]

    @property
    def failed_partition_count(self) -> int:
        return sum(1 for audit in self.partition_audits if not audit.passed)

    @property
    def planned_event_count(self) -> int:
        passed_count = len(self.partition_audits) - self.failed_partition_count
        return passed_count * (1 + len(SILVER_STK_MINS_CHECKS))


@dataclass(frozen=True)
class StkMinsSilverBootstrapEventReport:
    plan: StkMinsSilverBootstrapEventPlan
    dry_run: bool
    reported_asset_partitions: tuple[tuple[int, str], ...]
    skipped_materialized_asset_partitions: tuple[tuple[int, str], ...]
    reported_event_count: int


@dataclass(frozen=True)
class StockMinsSilverPartitionRegistrationReport:
    requested_partition_keys: tuple[str, ...]
    existing_partition_keys: tuple[str, ...]
    registered_partition_keys: tuple[str, ...]
    dry_run: bool


@dataclass(frozen=True)
class StkMinsSilverFinalAuditReport:
    selected_partition_count: int
    silver_partition_counts: Mapping[int, int]
    registered_partition_count: int
    materialized_partition_counts: Mapping[int, int]
    check_success_counts: Mapping[str, int]
    sample_readiness: Mapping[str, bool]


def plan_stk_mins_silver_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_SILVER_HISTORY_START_DATE,
    end_date: str | None = None,
) -> StkMinsSilverBootstrapEventPlan:
    silver_by_freq = discover_silver_stk_mins_partitions(lake_root)
    selected_keys = (
        tuple(sorted(set(partition_keys)))
        if partition_keys is not None
        else all_silver_partition_keys(
            lake_root,
            start_date=start_date,
            end_date=end_date,
        )
    )
    registered_keys = set(
        instance.get_dynamic_partitions(cn_a_stock_mins_silver_trade_days.name)
    )
    unregistered_keys = tuple(
        key for key in selected_keys if key not in registered_keys
    )
    missing_silver = tuple(
        (freq, partition_key)
        for freq in STK_MINS_FREQS
        for partition_key in selected_keys
        if partition_key not in set(silver_by_freq[freq])
    )
    if unregistered_keys or missing_silver:
        raise ValueError(
            "stk_mins silver event plan is not aligned: "
            f"unregistered={unregistered_keys[:10]}, "
            f"missing_silver={missing_silver[:10]}"
        )

    audits = tuple(
        audit_stk_mins_silver_bootstrap_partition(
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
            partition_key=partition_key,
        )
        for freq in STK_MINS_FREQS
        for partition_key in selected_keys
    )
    return StkMinsSilverBootstrapEventPlan(
        selected_partition_keys=selected_keys,
        silver_partition_counts={
            freq: len(partitions) for freq, partitions in silver_by_freq.items()
        },
        registered_partition_count=len(registered_keys),
        unregistered_selected_partition_keys=unregistered_keys,
        missing_silver_asset_partitions=missing_silver,
        partition_audits=audits,
    )


def register_stock_mins_silver_partitions(
    *,
    instance: dg.DagsterInstance,
    partition_keys: Sequence[str],
    dry_run: bool = False,
) -> StockMinsSilverPartitionRegistrationReport:
    requested_keys = tuple(sorted(set(partition_keys)))
    existing_keys = set(
        instance.get_dynamic_partitions(cn_a_stock_mins_silver_trade_days.name)
    )
    missing_keys = tuple(key for key in requested_keys if key not in existing_keys)
    if missing_keys and not dry_run:
        instance.add_dynamic_partitions(
            cn_a_stock_mins_silver_trade_days.name,
            list(missing_keys),
        )
    return StockMinsSilverPartitionRegistrationReport(
        requested_partition_keys=requested_keys,
        existing_partition_keys=tuple(key for key in requested_keys if key in existing_keys),
        registered_partition_keys=missing_keys,
        dry_run=dry_run,
    )


def report_stk_mins_silver_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    dry_run: bool = True,
    skip_existing_materialized: bool = True,
    start_date: str = STK_MINS_SILVER_HISTORY_START_DATE,
    end_date: str | None = None,
) -> StkMinsSilverBootstrapEventReport:
    plan = plan_stk_mins_silver_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        duckdb=duckdb,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
    )
    failed_audits = tuple(audit for audit in plan.partition_audits if not audit.passed)
    if failed_audits:
        samples = {
            f"{audit.freq}:{audit.partition_key}": audit.failed_check_names
            for audit in failed_audits[:10]
        }
        raise ValueError(f"stk_mins silver bootstrap audit failed: {samples}")

    if dry_run:
        return StkMinsSilverBootstrapEventReport(
            plan=plan,
            dry_run=True,
            reported_asset_partitions=(),
            skipped_materialized_asset_partitions=(),
            reported_event_count=0,
        )

    materialized_sets = {
        freq: set(instance.get_materialized_partitions(asset_key))
        for freq, asset_key in SILVER_STK_MINS_ASSET_KEYS.items()
    }
    reported: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []
    event_count = 0
    for audit in plan.partition_audits:
        if (
            skip_existing_materialized
            and audit.partition_key in materialized_sets[audit.freq]
        ):
            skipped.append((audit.freq, audit.partition_key))
            continue
        event_count += _report_stk_mins_silver_partition_events(instance, audit)
        reported.append((audit.freq, audit.partition_key))

    return StkMinsSilverBootstrapEventReport(
        plan=plan,
        dry_run=False,
        reported_asset_partitions=tuple(reported),
        skipped_materialized_asset_partitions=tuple(skipped),
        reported_event_count=event_count,
    )


def audit_stk_mins_silver_bootstrap_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    freq: int,
    partition_key: str,
) -> StkMinsSilverBootstrapPartitionAudit:
    silver_path = silver_stk_mins_path(lake_root, freq, partition_key)
    observed_columns: tuple[str, ...] = ()
    row_count: int | None = None
    if silver_path.exists():
        with duckdb.connect() as connection:
            row_count = int(
                connection.execute(
                    count_parquet_query(silver_path, hive_partitioning=False)
                ).fetchone()[0]
            )
            observed_columns = tuple(
                row[0]
                for row in connection.execute(
                    describe_parquet_query(silver_path, hive_partitioning=False)
                ).fetchall()
            )

    checks: list[StkMinsSilverBootstrapCheckAudit] = []
    check_names = tuple(SILVER_STK_MINS_CHECKS)
    for index, check_name in enumerate(check_names):
        if index > 1 and any(not check.passed for check in checks[:2]):
            checks.append(_skipped_check(check_name, silver_path, freq, partition_key))
            continue
        check_result = _evaluate_silver_check(
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
            partition_key=partition_key,
            check_name=check_name,
        )
        checks.append(
            StkMinsSilverBootstrapCheckAudit(
                check_name=check_name,
                passed=bool(check_result.passed),
                metadata=check_result.metadata or {},
            )
        )
    return StkMinsSilverBootstrapPartitionAudit(
        freq=freq,
        partition_key=partition_key,
        silver_file_path=silver_path,
        passed=all(check.passed for check in checks),
        row_count=row_count,
        observed_columns=observed_columns,
        checks=tuple(checks),
    )


def audit_stk_mins_silver_final_state(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    start_date: str = STK_MINS_SILVER_HISTORY_START_DATE,
    end_date: str | None = None,
) -> StkMinsSilverFinalAuditReport:
    selected_keys = all_silver_partition_keys(
        lake_root,
        start_date=start_date,
        end_date=end_date,
    )
    silver_by_freq = discover_silver_stk_mins_partitions(lake_root)
    registered_count = len(
        instance.get_dynamic_partitions(cn_a_stock_mins_silver_trade_days.name)
    )
    materialized_counts = {
        freq: len(instance.get_materialized_partitions(asset_key))
        for freq, asset_key in SILVER_STK_MINS_ASSET_KEYS.items()
    }
    check_counts: dict[str, int] = {}
    for freq, asset_key in SILVER_STK_MINS_ASSET_KEYS.items():
        for check_name in SILVER_STK_MINS_CHECKS:
            key = f"{asset_key.to_user_string()}:{check_name}"
            check_counts[key] = _check_success_count(
                instance,
                dg.AssetCheckKey(asset_key, check_name),
            )
    sample_readiness: dict[str, bool] = {}
    for partition_key in _sample_partition_keys(selected_keys):
        for freq, asset_key in SILVER_STK_MINS_ASSET_KEYS.items():
            status = asset_readiness_status(
                instance,
                AssetReadinessSpec(asset_key, SILVER_STK_MINS_CHECKS),
                partition_key=partition_key,
            )
            sample_readiness[f"{freq}:{partition_key}"] = status.ready
    return StkMinsSilverFinalAuditReport(
        selected_partition_count=len(selected_keys),
        silver_partition_counts={
            freq: len(partitions) for freq, partitions in silver_by_freq.items()
        },
        registered_partition_count=registered_count,
        materialized_partition_counts=materialized_counts,
        check_success_counts=check_counts,
        sample_readiness=sample_readiness,
    )


class _LakeRootShim:
    def __init__(self, root: Path) -> None:
        self._root = root

    def root(self) -> Path:
        return self._root


class _PartitionContext:
    def __init__(self, partition_key: str) -> None:
        self.partition_key = partition_key


_SILVER_CHECK_EVALUATORS = {
    stk_mins_checks.SILVER_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK: (
        stk_mins_checks._silver_file_exists_and_row_count_positive
    ),
    stk_mins_checks.SILVER_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK: (
        stk_mins_checks._silver_schema_matches_contract
    ),
    stk_mins_checks.SILVER_STK_MINS_FREQ_AND_PARTITION_MATCH_CHECK: (
        stk_mins_checks._silver_freq_and_partition_match
    ),
    stk_mins_checks.SILVER_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK: (
        stk_mins_checks._silver_unique_ts_code_trade_time
    ),
    stk_mins_checks.SILVER_STK_MINS_PRICE_SANITY_CHECK: (
        stk_mins_checks._silver_price_sanity
    ),
    stk_mins_checks.SILVER_STK_MINS_VOLUME_AMOUNT_SANITY_CHECK: (
        stk_mins_checks._silver_volume_amount_sanity
    ),
    stk_mins_checks.SILVER_STK_MINS_EXCHANGE_MATCHES_SUFFIX_CHECK: (
        stk_mins_checks._silver_exchange_matches_suffix
    ),
    stk_mins_checks.SILVER_STK_MINS_CODES_EXIST_IN_STOCK_DAILY_CHECK: (
        stk_mins_checks._silver_codes_exist_in_stock_daily
    ),
    stk_mins_checks.SILVER_STK_MINS_NO_FULL_DAY_SUSPEND_STRUCTURAL_ROWS_CHECK: (
        stk_mins_checks._silver_no_full_day_suspend_structural_rows
    ),
    stk_mins_checks.SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK: (
        stk_mins_checks._silver_name_timeline_covered
    ),
}


def _evaluate_silver_check(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    freq: int,
    partition_key: str,
    check_name: str,
) -> dg.AssetCheckResult:
    evaluator = _SILVER_CHECK_EVALUATORS[check_name]
    return evaluator(
        context=_PartitionContext(partition_key),
        lake_root=_LakeRootShim(lake_root),
        duckdb=duckdb,
        freq=freq,
    )


def _skipped_check(
    check_name: str,
    silver_path: Path,
    freq: int,
    partition_key: str,
) -> StkMinsSilverBootstrapCheckAudit:
    return StkMinsSilverBootstrapCheckAudit(
        check_name=check_name,
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=silver_path,
            extra_metadata={
                "freq": freq,
                "partition_key": partition_key,
                "not_evaluated_reason": "file_or_schema_check_failed",
            },
        ),
    )


def _report_stk_mins_silver_partition_events(
    instance: dg.DagsterInstance,
    audit: StkMinsSilverBootstrapPartitionAudit,
) -> int:
    asset_key = SILVER_STK_MINS_ASSET_KEYS[audit.freq]
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=asset_key,
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.silver_file_path,
                row_count=audit.row_count,
                observed_columns=audit.observed_columns,
                extra_metadata={
                    "source_method": "stk_mins_silver_history_generation",
                    "bootstrap_event_backfill": True,
                    "freq": audit.freq,
                    "partition_key": audit.partition_key,
                },
            ),
        )
    )
    materialization = _latest_materialization(instance, asset_key, audit.partition_key)
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    event_count = 1
    for check in audit.checks:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=asset_key,
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


def _latest_materialization(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    partition_key: str,
):
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key,
            asset_partitions=[partition_key],
        ),
        limit=1,
    )
    if not result.records:
        raise RuntimeError(f"Expected materialization after runless report: {asset_key}")
    return result.records[0]


def _sample_partition_keys(partition_keys: Sequence[str]) -> tuple[str, ...]:
    if not partition_keys:
        return ()
    ordered = tuple(partition_keys)
    return tuple(dict.fromkeys((ordered[0], ordered[len(ordered) // 2], ordered[-1])))
