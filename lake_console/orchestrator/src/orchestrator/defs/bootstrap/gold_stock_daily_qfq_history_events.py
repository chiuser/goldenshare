from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.gold_stock_daily_qfq_history import (
    discover_gold_stock_daily_qfq_partitions,
    load_gold_stock_daily_qfq_expected_trade_dates,
)
from orchestrator.defs.checks.stock_daily_qfq_checks import (
    GOLD_STOCK_DAILY_QFQ_CHECK_NAMES,
    _column_names,
    _contract_failure_samples,
    _contract_rule_counts,
    _coverage_counts,
    _qfq_comparison_counts,
    _qfq_failure_samples,
    _row_count,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.sensors.readiness import (
    GOLD_STOCK_DAILY_QFQ_ASSET_KEY,
    GOLD_STOCK_DAILY_QFQ_CHECKS,
    GOLD_STOCK_DAILY_QFQ_READINESS_SPECS,
    asset_readiness_status,
)
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_COLUMNS,
    load_stock_daily_qfq_previous_lookup_trade_dates,
)


GOLD_STOCK_DAILY_QFQ_RUNLESS_CHECK_WINDOW_SIZE = 20
GOLD_STOCK_DAILY_QFQ_RUNLESS_CHECK_EVENT_MAX_PARTITIONS = 21
GOLD_STOCK_DAILY_QFQ_HISTORY_EVENT_SAMPLE_LIMIT = 20


@dataclass(frozen=True, slots=True)
class GoldStockDailyQfqHistoryCheckAudit:
    check_name: str
    passed: bool
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, object]:
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class GoldStockDailyQfqHistoryPartitionAudit:
    partition_key: str
    qfq_file_path: Path
    passed: bool
    row_count: int | None
    observed_columns: tuple[str, ...]
    checks: tuple[GoldStockDailyQfqHistoryCheckAudit, ...]

    @property
    def failed_check_names(self) -> tuple[str, ...]:
        return tuple(check.check_name for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "qfq_file_path": str(self.qfq_file_path),
            "passed": self.passed,
            "row_count": self.row_count,
            "observed_columns": list(self.observed_columns),
            "failed_check_names": list(self.failed_check_names),
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True, slots=True)
class GoldStockDailyQfqHistoryRunlessEventPlan:
    materialization_partition_keys: tuple[str, ...]
    check_partition_keys: tuple[str, ...]
    existing_materialized_partition_keys: tuple[str, ...]
    existing_ready_check_partition_keys: tuple[str, ...]
    partition_audits: tuple[GoldStockDailyQfqHistoryPartitionAudit, ...]

    @property
    def failed_check_partition_count(self) -> int:
        return sum(1 for audit in self.partition_audits if not audit.passed)

    @property
    def planned_materialization_event_count(self) -> int:
        return len(
            set(self.materialization_partition_keys)
            - set(self.existing_materialized_partition_keys)
        )

    @property
    def planned_check_event_count(self) -> int:
        return (
            len(
                set(self.check_partition_keys)
                - set(self.existing_ready_check_partition_keys)
            )
            * len(GOLD_STOCK_DAILY_QFQ_CHECK_NAMES)
        )

    @property
    def planned_event_count(self) -> int:
        return self.planned_materialization_event_count + self.planned_check_event_count

    def to_dict(self) -> dict[str, object]:
        return {
            "materialization_partition_keys": list(self.materialization_partition_keys),
            "materialization_partition_count": len(self.materialization_partition_keys),
            "check_partition_keys": list(self.check_partition_keys),
            "check_partition_count": len(self.check_partition_keys),
            "existing_materialized_partition_keys": list(
                self.existing_materialized_partition_keys
            ),
            "existing_ready_check_partition_keys": list(
                self.existing_ready_check_partition_keys
            ),
            "failed_check_partition_count": self.failed_check_partition_count,
            "planned_materialization_event_count": (
                self.planned_materialization_event_count
            ),
            "planned_check_event_count": self.planned_check_event_count,
            "planned_event_count": self.planned_event_count,
            "sample_partition_audits": [
                audit.to_dict()
                for audit in self.partition_audits[
                    :GOLD_STOCK_DAILY_QFQ_HISTORY_EVENT_SAMPLE_LIMIT
                ]
            ],
        }


@dataclass(frozen=True, slots=True)
class GoldStockDailyQfqHistoryRunlessEventReport:
    plan: GoldStockDailyQfqHistoryRunlessEventPlan
    dry_run: bool
    reported_materialization_partition_keys: tuple[str, ...]
    reported_check_partition_keys: tuple[str, ...]
    skipped_materialized_partition_keys: tuple[str, ...]
    skipped_ready_check_partition_keys: tuple[str, ...]
    reported_event_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "reported_materialization_partition_keys": list(
                self.reported_materialization_partition_keys
            ),
            "reported_check_partition_keys": list(self.reported_check_partition_keys),
            "skipped_materialized_partition_keys": list(
                self.skipped_materialized_partition_keys
            ),
            "skipped_ready_check_partition_keys": list(
                self.skipped_ready_check_partition_keys
            ),
            "reported_event_count": self.reported_event_count,
            "plan": self.plan.to_dict(),
        }


def recent_gold_stock_daily_qfq_check_partitions(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    start_date: str = "2014-01-01",
    end_date: str | None = None,
    window_size: int = GOLD_STOCK_DAILY_QFQ_RUNLESS_CHECK_WINDOW_SIZE,
) -> tuple[str, ...]:
    target_partitions = tuple(discover_gold_stock_daily_qfq_partitions(lake_root))
    if not target_partitions:
        return ()
    expected_trade_dates = load_gold_stock_daily_qfq_expected_trade_dates(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        start_date=start_date,
        end_date=end_date,
    )
    latest_target = target_partitions[-1]
    target_partition_set = set(target_partitions)
    generated_expected = tuple(
        trade_date
        for trade_date in expected_trade_dates
        if trade_date <= latest_target and trade_date in target_partition_set
    )
    if not generated_expected:
        return (latest_target,)
    recent_expected = tuple(generated_expected[-window_size:])
    return tuple(dict.fromkeys((*recent_expected, latest_target)))


def plan_gold_stock_daily_qfq_runless_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    materialization_partition_keys: Sequence[str] | None = None,
    check_partition_keys: Sequence[str] | None = None,
    start_date: str = "2014-01-01",
    end_date: str | None = None,
) -> GoldStockDailyQfqHistoryRunlessEventPlan:
    materialization_keys = tuple(
        sorted(
            set(
                materialization_partition_keys
                if materialization_partition_keys is not None
                else discover_gold_stock_daily_qfq_partitions(lake_root)
            )
        )
    )
    check_keys = tuple(
        sorted(
            set(
                check_partition_keys
                if check_partition_keys is not None
                else recent_gold_stock_daily_qfq_check_partitions(
                    lake_root=lake_root,
                    duckdb_resource=duckdb_resource,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        )
    )
    if len(check_keys) > GOLD_STOCK_DAILY_QFQ_RUNLESS_CHECK_EVENT_MAX_PARTITIONS:
        raise ValueError(
            "gold stock daily qfq runless check event backfill is limited to "
            "recent 20 trade days plus latest partition."
        )

    existing_materialized = set(
        instance.get_materialized_partitions(GOLD_STOCK_DAILY_QFQ_ASSET_KEY)
    )
    existing_ready = tuple(
        partition_key
        for partition_key in check_keys
        if asset_readiness_status(
            instance,
            GOLD_STOCK_DAILY_QFQ_READINESS_SPECS[0],
            partition_key=partition_key,
        ).ready
    )
    audits = tuple(
        audit_gold_stock_daily_qfq_history_partition(
            lake_root=lake_root,
            duckdb_resource=duckdb_resource,
            partition_key=partition_key,
        )
        for partition_key in check_keys
    )
    return GoldStockDailyQfqHistoryRunlessEventPlan(
        materialization_partition_keys=materialization_keys,
        check_partition_keys=check_keys,
        existing_materialized_partition_keys=tuple(
            key for key in materialization_keys if key in existing_materialized
        ),
        existing_ready_check_partition_keys=existing_ready,
        partition_audits=audits,
    )


def report_gold_stock_daily_qfq_runless_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    materialization_partition_keys: Sequence[str] | None = None,
    check_partition_keys: Sequence[str] | None = None,
    history_audit_report_path: str | None = None,
    dry_run: bool = True,
    skip_existing_materialized: bool = True,
    skip_existing_ready_checks: bool = True,
) -> GoldStockDailyQfqHistoryRunlessEventReport:
    plan = plan_gold_stock_daily_qfq_runless_events(
        instance=instance,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        materialization_partition_keys=materialization_partition_keys,
        check_partition_keys=check_partition_keys,
    )
    failed_audits = tuple(audit for audit in plan.partition_audits if not audit.passed)
    if failed_audits and not dry_run:
        samples = {
            audit.partition_key: audit.failed_check_names for audit in failed_audits[:10]
        }
        raise ValueError(f"gold stock daily qfq runless audit failed: {samples}")

    if dry_run:
        return GoldStockDailyQfqHistoryRunlessEventReport(
            plan=plan,
            dry_run=True,
            reported_materialization_partition_keys=(),
            reported_check_partition_keys=(),
            skipped_materialized_partition_keys=(),
            skipped_ready_check_partition_keys=(),
            reported_event_count=0,
        )

    materialized = set(
        instance.get_materialized_partitions(GOLD_STOCK_DAILY_QFQ_ASSET_KEY)
    )
    audits_by_key = {audit.partition_key: audit for audit in plan.partition_audits}
    reported_materializations: list[str] = []
    reported_checks: list[str] = []
    skipped_materialized: list[str] = []
    skipped_ready_checks: list[str] = []
    event_count = 0

    for partition_key in plan.materialization_partition_keys:
        if skip_existing_materialized and partition_key in materialized:
            skipped_materialized.append(partition_key)
            continue
        event_count += _report_materialization_event(
            instance=instance,
            lake_root=lake_root,
            duckdb_resource=duckdb_resource,
            partition_key=partition_key,
            history_audit_report_path=history_audit_report_path,
        )
        materialized.add(partition_key)
        reported_materializations.append(partition_key)

    for partition_key in plan.check_partition_keys:
        if skip_existing_ready_checks and partition_key in set(
            plan.existing_ready_check_partition_keys
        ):
            skipped_ready_checks.append(partition_key)
            continue
        if partition_key not in materialized:
            event_count += _report_materialization_event(
                instance=instance,
                lake_root=lake_root,
                duckdb_resource=duckdb_resource,
                partition_key=partition_key,
                history_audit_report_path=history_audit_report_path,
            )
            materialized.add(partition_key)
            reported_materializations.append(partition_key)
        event_count += _report_check_events(
            instance=instance,
            audit=audits_by_key[partition_key],
            history_audit_report_path=history_audit_report_path,
        )
        reported_checks.append(partition_key)

    return GoldStockDailyQfqHistoryRunlessEventReport(
        plan=plan,
        dry_run=False,
        reported_materialization_partition_keys=tuple(reported_materializations),
        reported_check_partition_keys=tuple(reported_checks),
        skipped_materialized_partition_keys=tuple(skipped_materialized),
        skipped_ready_check_partition_keys=tuple(skipped_ready_checks),
        reported_event_count=event_count,
    )


def audit_gold_stock_daily_qfq_history_partition(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
) -> GoldStockDailyQfqHistoryPartitionAudit:
    qfq_path = gold_stock_daily_qfq_path(lake_root, partition_key)
    if not qfq_path.exists():
        checks = (
            _missing_file_check(
                check_name=GOLD_STOCK_DAILY_QFQ_CHECK_NAMES[0],
                partition_key=partition_key,
                path=qfq_path,
                check_scope=CheckScope.FILE_EXISTS,
            ),
            _missing_file_check(
                check_name=GOLD_STOCK_DAILY_QFQ_CHECK_NAMES[1],
                partition_key=partition_key,
                path=qfq_path,
                check_scope=CheckScope.RECONCILIATION,
            ),
        )
        return GoldStockDailyQfqHistoryPartitionAudit(
            partition_key=partition_key,
            qfq_file_path=qfq_path,
            passed=False,
            row_count=None,
            observed_columns=(),
            checks=checks,
        )

    with duckdb_resource.connect() as connection:
        observed_columns = tuple(_column_names(connection, qfq_path))
        row_count = _row_count(connection, qfq_path)
        contract_check = _contract_check_audit(
            connection=connection,
            qfq_path=qfq_path,
            partition_key=partition_key,
            row_count=row_count,
            observed_columns=observed_columns,
        )
        semantics_check = _semantics_check_audit(
            connection=connection,
            lake_root=lake_root,
            qfq_path=qfq_path,
            partition_key=partition_key,
            contract_passed=contract_check.passed,
        )
    checks = (contract_check, semantics_check)
    return GoldStockDailyQfqHistoryPartitionAudit(
        partition_key=partition_key,
        qfq_file_path=qfq_path,
        passed=all(check.passed for check in checks),
        row_count=row_count,
        observed_columns=observed_columns,
        checks=checks,
    )


def _contract_check_audit(
    *,
    connection,
    qfq_path: Path,
    partition_key: str,
    row_count: int,
    observed_columns: Sequence[str],
) -> GoldStockDailyQfqHistoryCheckAudit:
    expected_columns = tuple(GOLD_STOCK_DAILY_QFQ_COLUMNS)
    failed_rule_names = []
    rule_counts = {
        "partition_date_mismatch_count": 0,
        "null_key_count": 0,
        "duplicate_key_count": 0,
    }
    samples: list[dict[str, Any]] = []
    if row_count <= 0:
        failed_rule_names.append("row_count_positive")
    if tuple(observed_columns) != expected_columns:
        failed_rule_names.append("schema_matches_contract")
    else:
        rule_counts = _contract_rule_counts(connection, qfq_path, partition_key)
        if rule_counts["partition_date_mismatch_count"]:
            failed_rule_names.append("partition_date_matches")
        if rule_counts["null_key_count"]:
            failed_rule_names.append("key_columns_non_null")
        if rule_counts["duplicate_key_count"]:
            failed_rule_names.append("unique_ts_code_trade_date")
        samples = _contract_failure_samples(connection, qfq_path, partition_key)
    metadata = build_check_metadata(
        check_scope=CheckScope.SCHEMA,
        checked_row_count=row_count,
        failed_row_count=(
            rule_counts["partition_date_mismatch_count"]
            + rule_counts["null_key_count"]
            + rule_counts["duplicate_key_count"]
        ),
        file_path=qfq_path,
        extra_metadata={
            "source_method": "gold_stock_daily_qfq_history_bootstrap",
            "bootstrap_event_backfill": True,
            "event_backfill_scope": "recent_20_plus_latest",
            "partition_key": partition_key,
            "observed_columns": list(observed_columns),
            "expected_columns": list(expected_columns),
            "failed_rule_names": failed_rule_names,
            **rule_counts,
            "sample_rows": samples,
        },
    )
    return GoldStockDailyQfqHistoryCheckAudit(
        check_name=GOLD_STOCK_DAILY_QFQ_CHECK_NAMES[0],
        passed=not failed_rule_names,
        metadata=metadata,
    )


def _semantics_check_audit(
    *,
    connection,
    lake_root: Path,
    qfq_path: Path,
    partition_key: str,
    contract_passed: bool,
) -> GoldStockDailyQfqHistoryCheckAudit:
    stock_daily_path = silver_stock_daily_path(lake_root, partition_key)
    adj_factor_path = silver_adj_factor_path(lake_root, partition_key)
    missing_paths = [
        path for path in (qfq_path, stock_daily_path, adj_factor_path) if not path.exists()
    ]
    if missing_paths or not contract_passed:
        metadata = build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            file_path=qfq_path,
            input_file_paths=[stock_daily_path, adj_factor_path],
            missing_file_paths=missing_paths,
            extra_metadata={
                "source_method": "gold_stock_daily_qfq_history_bootstrap",
                "bootstrap_event_backfill": True,
                "event_backfill_scope": "recent_20_plus_latest",
                "partition_key": partition_key,
                "failed_rule_names": (
                    ["missing_input_files"] if missing_paths else ["contract_failed"]
                ),
            },
        )
        return GoldStockDailyQfqHistoryCheckAudit(
            check_name=GOLD_STOCK_DAILY_QFQ_CHECK_NAMES[1],
            passed=False,
            metadata=metadata,
        )

    previous_lookup_trade_dates = load_stock_daily_qfq_previous_lookup_trade_dates(
        connection=connection,
        lake_root=lake_root,
        trade_date=partition_key,
    )
    previous_stock_daily_paths = tuple(
        path
        for path in (
            silver_stock_daily_path(lake_root, trade_date)
            for trade_date in previous_lookup_trade_dates
        )
        if path.exists()
    )
    previous_adj_factor_paths = tuple(
        path
        for path in (
            silver_adj_factor_path(lake_root, trade_date)
            for trade_date in previous_lookup_trade_dates
        )
        if path.exists()
    )
    coverage = _coverage_counts(
        connection=connection,
        stock_daily_path=stock_daily_path,
        adj_factor_path=adj_factor_path,
        previous_stock_daily_paths=previous_stock_daily_paths,
        previous_adj_factor_paths=previous_adj_factor_paths,
        trade_date=partition_key,
    )
    comparison = _qfq_comparison_counts(
        connection=connection,
        qfq_path=qfq_path,
        stock_daily_path=stock_daily_path,
        adj_factor_path=adj_factor_path,
        previous_stock_daily_paths=previous_stock_daily_paths,
        previous_adj_factor_paths=previous_adj_factor_paths,
        trade_date=partition_key,
    )
    failed_rule_names = []
    if coverage["source_row_count"] <= 0:
        failed_rule_names.append("source_row_count_positive")
    if coverage["missing_trade_factor_count"]:
        failed_rule_names.append("trade_adj_factor_covered")
    if coverage["missing_as_of_factor_count"]:
        failed_rule_names.append("as_of_adj_factor_covered")
    if coverage["missing_previous_factor_count"]:
        failed_rule_names.append("previous_adj_factor_covered")
    if comparison["target_row_count"] != coverage["source_row_count"]:
        failed_rule_names.append("target_row_count_matches_source")
    if comparison["missing_target_row_count"] or comparison["unexpected_target_row_count"]:
        failed_rule_names.append("target_keys_match_expected")
    if comparison["formula_mismatch_count"]:
        failed_rule_names.append("qfq_formula_matches_source_and_factor")
    if comparison["price_domain_failed_count"]:
        failed_rule_names.append("price_domain_valid")
    samples = _qfq_failure_samples(
        connection=connection,
        qfq_path=qfq_path,
        stock_daily_path=stock_daily_path,
        adj_factor_path=adj_factor_path,
        previous_stock_daily_paths=previous_stock_daily_paths,
        previous_adj_factor_paths=previous_adj_factor_paths,
        trade_date=partition_key,
    )
    metadata = build_check_metadata(
        check_scope=CheckScope.RECONCILIATION,
        checked_row_count=comparison["target_row_count"],
        failed_row_count=(
            comparison["missing_target_row_count"]
            + comparison["unexpected_target_row_count"]
            + comparison["formula_mismatch_count"]
            + comparison["price_domain_failed_count"]
            + coverage["missing_trade_factor_count"]
            + coverage["missing_as_of_factor_count"]
            + coverage["missing_previous_factor_count"]
        ),
        file_path=qfq_path,
        input_file_paths=[stock_daily_path, adj_factor_path],
        extra_metadata={
            "source_method": "gold_stock_daily_qfq_history_bootstrap",
            "bootstrap_event_backfill": True,
            "event_backfill_scope": "recent_20_plus_latest",
            "partition_key": partition_key,
            "previous_lookup_trade_date_count": len(previous_lookup_trade_dates),
            "previous_stock_daily_file_count": len(previous_stock_daily_paths),
            "previous_adj_factor_file_count": len(previous_adj_factor_paths),
            "failed_rule_names": failed_rule_names,
            **coverage,
            **comparison,
            "sample_rows": samples,
        },
    )
    return GoldStockDailyQfqHistoryCheckAudit(
        check_name=GOLD_STOCK_DAILY_QFQ_CHECK_NAMES[1],
        passed=not failed_rule_names,
        metadata=metadata,
    )


def _missing_file_check(
    *,
    check_name: str,
    partition_key: str,
    path: Path,
    check_scope: CheckScope,
) -> GoldStockDailyQfqHistoryCheckAudit:
    return GoldStockDailyQfqHistoryCheckAudit(
        check_name=check_name,
        passed=False,
        metadata=build_check_metadata(
            check_scope=check_scope,
            file_path=path,
            missing_file_paths=[path],
            extra_metadata={
                "source_method": "gold_stock_daily_qfq_history_bootstrap",
                "bootstrap_event_backfill": True,
                "event_backfill_scope": "recent_20_plus_latest",
                "partition_key": partition_key,
                "failed_rule_names": ["file_exists"],
            },
        ),
    )


def _report_materialization_event(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    history_audit_report_path: str | None,
) -> int:
    path = gold_stock_daily_qfq_path(lake_root, partition_key)
    if not path.exists():
        raise FileNotFoundError(f"Missing gold_stock_daily_qfq file: {path}")
    with duckdb_resource.connect() as connection:
        row_count = _row_count(connection, path)
        observed_columns = tuple(_column_names(connection, path))
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=GOLD_STOCK_DAILY_QFQ_ASSET_KEY,
            partition=partition_key,
            metadata=build_materialization_metadata(
                uri=path,
                row_count=row_count,
                observed_columns=observed_columns,
                extra_metadata={
                    "source_method": "gold_stock_daily_qfq_history_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_history",
                    "history_audit_report_path": history_audit_report_path,
                    "partition_key": partition_key,
                },
            ),
        )
    )
    return 1


def _report_check_events(
    *,
    instance: dg.DagsterInstance,
    audit: GoldStockDailyQfqHistoryPartitionAudit,
    history_audit_report_path: str | None,
) -> int:
    if not audit.passed:
        raise ValueError(
            "Cannot report gold_stock_daily_qfq check events for failed audit: "
            f"{audit.partition_key}:{audit.failed_check_names}"
        )
    materialization = _latest_materialization(
        instance,
        GOLD_STOCK_DAILY_QFQ_ASSET_KEY,
        audit.partition_key,
    )
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    event_count = 0
    for check in audit.checks:
        metadata = dict(check.metadata)
        if history_audit_report_path is not None:
            metadata["goldenshare/history_audit_report_path"] = (
                history_audit_report_path
            )
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=GOLD_STOCK_DAILY_QFQ_ASSET_KEY,
                check_name=check.check_name,
                passed=True,
                metadata=metadata,
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
