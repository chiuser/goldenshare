from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.wealth_market_turnover_history import (
    WealthMarketTurnoverHistoryPartitionAudit,
    audit_wealth_market_turnover_history,
    discover_wealth_market_turnover_target_partitions,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.wealth_market_turnover_contract import (
    GOLD_WEALTH_MARKET_TURNOVER_COLUMNS,
    WEALTH_MARKET_TURNOVER_CHECK_NAME,
)


GOLD_WEALTH_MARKET_TURNOVER_ASSET_KEY = dg.AssetKey("gold_wealth_market_turnover")
WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE = 20


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverRunlessEventPlan:
    selected_partition_keys: tuple[str, ...]
    failed_partition_count: int
    planned_event_count: int
    existing_materialized_partition_keys: tuple[str, ...]
    partition_audits: tuple[WealthMarketTurnoverHistoryPartitionAudit, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "selected_partition_keys": list(self.selected_partition_keys),
            "selected_partition_count": len(self.selected_partition_keys),
            "failed_partition_count": self.failed_partition_count,
            "planned_event_count": self.planned_event_count,
            "existing_materialized_partition_keys": list(
                self.existing_materialized_partition_keys
            ),
            "sample_partition_audits": [
                audit.to_dict() for audit in self.partition_audits[:20]
            ],
        }


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverRunlessEventReport:
    plan: WealthMarketTurnoverRunlessEventPlan
    dry_run: bool
    reported_partition_keys: tuple[str, ...]
    skipped_materialized_partition_keys: tuple[str, ...]
    reported_event_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "reported_partition_keys": list(self.reported_partition_keys),
            "skipped_materialized_partition_keys": list(
                self.skipped_materialized_partition_keys
            ),
            "reported_event_count": self.reported_event_count,
            "plan": self.plan.to_dict(),
        }


def recent_wealth_market_turnover_partitions(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    *,
    window_size: int = WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE,
) -> tuple[str, ...]:
    partitions = discover_wealth_market_turnover_target_partitions(lake_root)
    if len(partitions) < window_size:
        raise ValueError(
            "wealth market turnover runless window is incomplete: "
            f"available={len(partitions)}, required={window_size}."
        )
    return partitions[-window_size:]


def plan_wealth_market_turnover_runless_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    history_audit_report_path: str | None = None,
) -> WealthMarketTurnoverRunlessEventPlan:
    selected_keys = (
        tuple(sorted(set(partition_keys)))
        if partition_keys is not None
        else recent_wealth_market_turnover_partitions(lake_root)
    )
    if not selected_keys:
        raise ValueError("At least one wealth market turnover runless partition is required.")
    if len(selected_keys) > WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE:
        raise ValueError(
            "wealth market turnover runless event plan exceeds recent 20 window."
        )

    audit_report = audit_wealth_market_turnover_history(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        partition_keys=selected_keys,
    )
    failed_count = audit_report.failed_partition_count
    materialized = set(
        instance.get_materialized_partitions(GOLD_WEALTH_MARKET_TURNOVER_ASSET_KEY)
    )
    passed_count = len(selected_keys) - failed_count
    return WealthMarketTurnoverRunlessEventPlan(
        selected_partition_keys=selected_keys,
        failed_partition_count=failed_count,
        planned_event_count=passed_count * 2,
        existing_materialized_partition_keys=tuple(
            key for key in selected_keys if key in materialized
        ),
        partition_audits=audit_report.partition_audits,
    )


def report_wealth_market_turnover_runless_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    history_audit_report_path: str | None = None,
    dry_run: bool = True,
    skip_existing_materialized: bool = True,
) -> WealthMarketTurnoverRunlessEventReport:
    plan = plan_wealth_market_turnover_runless_events(
        instance=instance,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        partition_keys=partition_keys,
        history_audit_report_path=history_audit_report_path,
    )
    if plan.failed_partition_count:
        failed = {
            audit.partition_key: audit.reason_code
            for audit in plan.partition_audits
            if not audit.passed
        }
        raise ValueError(f"wealth market turnover runless audit failed: {failed}")

    if dry_run:
        return WealthMarketTurnoverRunlessEventReport(
            plan=plan,
            dry_run=True,
            reported_partition_keys=(),
            skipped_materialized_partition_keys=(),
            reported_event_count=0,
        )

    materialized = set(
        instance.get_materialized_partitions(GOLD_WEALTH_MARKET_TURNOVER_ASSET_KEY)
    )
    reported: list[str] = []
    skipped: list[str] = []
    event_count = 0
    audits_by_key = {audit.partition_key: audit for audit in plan.partition_audits}
    for partition_key in plan.selected_partition_keys:
        if skip_existing_materialized and partition_key in materialized:
            skipped.append(partition_key)
            continue
        event_count += _report_partition_events(
            instance=instance,
            audit=audits_by_key[partition_key],
            history_audit_report_path=history_audit_report_path,
        )
        reported.append(partition_key)

    return WealthMarketTurnoverRunlessEventReport(
        plan=plan,
        dry_run=False,
        reported_partition_keys=tuple(reported),
        skipped_materialized_partition_keys=tuple(skipped),
        reported_event_count=event_count,
    )


def _report_partition_events(
    *,
    instance: dg.DagsterInstance,
    audit: WealthMarketTurnoverHistoryPartitionAudit,
    history_audit_report_path: str | None,
) -> int:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=GOLD_WEALTH_MARKET_TURNOVER_ASSET_KEY,
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.target_path,
                row_count=audit.checked_row_count,
                observed_columns=GOLD_WEALTH_MARKET_TURNOVER_COLUMNS,
                extra_metadata={
                    "source_method": "wealth_market_turnover_history_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_trade_days",
                    "history_audit_report_path": history_audit_report_path,
                    "partition_key": audit.partition_key,
                    "freqs": list(STK_MINS_FREQS),
                },
            ),
        )
    )
    materialization = _latest_materialization(
        instance,
        GOLD_WEALTH_MARKET_TURNOVER_ASSET_KEY,
        audit.partition_key,
    )
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=GOLD_WEALTH_MARKET_TURNOVER_ASSET_KEY,
            check_name=WEALTH_MARKET_TURNOVER_CHECK_NAME,
            passed=True,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                file_path=audit.target_path,
                checked_row_count=audit.checked_row_count,
                extra_metadata={
                    "source_method": "wealth_market_turnover_history_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_trade_days",
                    "history_audit_report_path": history_audit_report_path,
                    "partition_key": audit.partition_key,
                    "freqs": list(STK_MINS_FREQS),
                },
            ),
            blocking=True,
            partition=audit.partition_key,
            target_materialization_data=target,
        )
    )
    return 2


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
        raise RuntimeError(
            f"Expected materialization after runless report: {asset_key}"
        )
    return result.records[0]
