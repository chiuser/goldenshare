from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.checks.index_daily_checks import (
    evaluate_raw_index_daily_file_contract,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_RAW_COLUMNS,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, raw_index_daily_path
from orchestrator.defs.prod_db.index_daily import index_code_set_hash, normalize_index_codes
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.configs import normalize_iso_trade_date
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    SourceSystem,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)


RAW_INDEX_DAILY_ASSET_KEY = dg.AssetKey("raw_index_daily")
RAW_INDEX_DAILY_CHECKS = (
    "raw_index_daily_file_contract_check",
    "raw_index_daily_code_coverage_check",
)
RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT = 20
RAW_INDEX_DAILY_MAX_EVENT_COUNT = RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT * (
    1 + len(RAW_INDEX_DAILY_CHECKS)
)
RAW_INDEX_DAILY_COVERAGE_BASIS = "by_code_source_pairs"
RAW_INDEX_DAILY_BOOTSTRAP_METHOD = "by_code_layout_conversion"
RAW_INDEX_DAILY_EVENT_BACKFILL_SCOPE = "recent_window"

_ISO_TRADE_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class IndexDailyRawByDateRunlessCheckAudit:
    check_name: str
    passed: bool
    metadata: Mapping[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "metadata": _jsonable(self.metadata),
        }


@dataclass(frozen=True)
class IndexDailyRawByDateRunlessPartitionAudit:
    partition_key: str
    raw_file_path: Path
    passed: bool
    row_count: int | None
    observed_columns: tuple[str, ...]
    actual_code_count: int
    actual_code_set_hash: str | None
    current_dg_code_count: int
    current_dg_code_set_hash: str
    source_pair_count: int | None
    target_pair_count: int | None
    source_minus_target_pairs: int | None
    target_minus_source_pairs: int | None
    current_dg_missing_code_count: int
    current_dg_extra_code_count: int
    checks: tuple[IndexDailyRawByDateRunlessCheckAudit, ...]

    @property
    def failed_check_names(self) -> tuple[str, ...]:
        return tuple(check.check_name for check in self.checks if not check.passed)

    def to_payload(self) -> dict[str, Any]:
        return {
            "partition_key": self.partition_key,
            "raw_file_path": str(self.raw_file_path),
            "passed": self.passed,
            "row_count": self.row_count,
            "observed_columns": list(self.observed_columns),
            "actual_code_count": self.actual_code_count,
            "actual_code_set_hash": self.actual_code_set_hash,
            "current_dg_code_count": self.current_dg_code_count,
            "current_dg_code_set_hash": self.current_dg_code_set_hash,
            "source_pair_count": self.source_pair_count,
            "target_pair_count": self.target_pair_count,
            "source_minus_target_pairs": self.source_minus_target_pairs,
            "target_minus_source_pairs": self.target_minus_source_pairs,
            "current_dg_missing_code_count": self.current_dg_missing_code_count,
            "current_dg_extra_code_count": self.current_dg_extra_code_count,
            "failed_check_names": list(self.failed_check_names),
            "checks": [check.to_payload() for check in self.checks],
        }


@dataclass(frozen=True)
class IndexDailyRawByDateRunlessEventPlan:
    selected_partition_keys: tuple[str, ...]
    raw_partition_count: int
    registered_trade_day_count: int
    p3_final_audit_report_path: Path
    p3_final_audit_summary: Mapping[str, Any]
    source_glob: Path
    partition_audits: tuple[IndexDailyRawByDateRunlessPartitionAudit, ...]

    @property
    def failed_partition_count(self) -> int:
        return sum(1 for audit in self.partition_audits if not audit.passed)

    @property
    def planned_event_count(self) -> int:
        passed_count = len(self.partition_audits) - self.failed_partition_count
        return passed_count * (1 + len(RAW_INDEX_DAILY_CHECKS))

    @property
    def should_stop(self) -> bool:
        return (
            self.failed_partition_count > 0
            or self.planned_event_count > RAW_INDEX_DAILY_MAX_EVENT_COUNT
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "selected_partition_keys": list(self.selected_partition_keys),
            "raw_partition_count": self.raw_partition_count,
            "registered_trade_day_count": self.registered_trade_day_count,
            "p3_final_audit_report_path": str(self.p3_final_audit_report_path),
            "p3_final_audit_summary": _jsonable(self.p3_final_audit_summary),
            "source_glob": str(self.source_glob),
            "failed_partition_count": self.failed_partition_count,
            "planned_event_count": self.planned_event_count,
            "max_event_count": RAW_INDEX_DAILY_MAX_EVENT_COUNT,
            "should_stop": self.should_stop,
            "partition_audits": [
                audit.to_payload() for audit in self.partition_audits
            ],
        }


@dataclass(frozen=True)
class IndexDailyRawByDateRunlessEventReport:
    plan: IndexDailyRawByDateRunlessEventPlan
    dry_run: bool
    reported_partition_keys: tuple[str, ...]
    skipped_ready_partition_keys: tuple[str, ...]
    blocked_existing_partition_keys: tuple[str, ...]
    planned_new_event_count: int
    reported_event_count: int

    @property
    def should_stop(self) -> bool:
        return self.plan.should_stop or bool(self.blocked_existing_partition_keys)

    def to_payload(self) -> dict[str, Any]:
        return {
            "mode": "dry_run" if self.dry_run else "apply",
            "target_asset_key": RAW_INDEX_DAILY_ASSET_KEY.to_user_string(),
            "target_check_names": list(RAW_INDEX_DAILY_CHECKS),
            "dry_run": self.dry_run,
            "reported_partition_keys": list(self.reported_partition_keys),
            "skipped_ready_partition_keys": list(self.skipped_ready_partition_keys),
            "blocked_existing_partition_keys": list(
                self.blocked_existing_partition_keys
            ),
            "planned_new_event_count": self.planned_new_event_count,
            "reported_event_count": self.reported_event_count,
            "should_stop": self.should_stop,
            "plan": self.plan.to_payload(),
        }


@dataclass(frozen=True)
class IndexDailyRawByDateRunlessFinalAudit:
    selected_partition_keys: tuple[str, ...]
    ready_partition_keys: tuple[str, ...]
    not_ready_partition_keys: tuple[str, ...]
    forbidden_partition_statuses: Mapping[str, Mapping[str, Any]]
    should_stop: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "target_asset_key": RAW_INDEX_DAILY_ASSET_KEY.to_user_string(),
            "target_check_names": list(RAW_INDEX_DAILY_CHECKS),
            "selected_partition_keys": list(self.selected_partition_keys),
            "ready_partition_keys": list(self.ready_partition_keys),
            "not_ready_partition_keys": list(self.not_ready_partition_keys),
            "forbidden_partition_statuses": _jsonable(
                self.forbidden_partition_statuses
            ),
            "should_stop": self.should_stop,
        }


def discover_raw_index_daily_partition_keys(lake_root: Path) -> tuple[str, ...]:
    target_root = lake_root / "raw" / "index_daily"
    if not target_root.exists():
        return ()
    partition_keys: list[str] = []
    for parquet_path in target_root.glob("trade_date=*/part-000.parquet"):
        partition_dir = parquet_path.parent.name
        if not partition_dir.startswith("trade_date="):
            continue
        partition_key = partition_dir.removeprefix("trade_date=")
        if _ISO_TRADE_DATE_PATTERN.match(partition_key):
            partition_keys.append(partition_key)
    return tuple(sorted(set(partition_keys)))


def raw_index_daily_by_code_source_glob(lake_root: Path) -> Path:
    return (
        lake_root
        / "raw"
        / "tushare"
        / "index_daily_by_code"
        / "ts_code=*"
        / "part-000.parquet"
    )


def plan_raw_index_daily_recent_window_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb: DuckDBResource,
    p3_final_audit_report_path: Path,
    partition_keys: Sequence[str] | None = None,
    window_limit: int = RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT,
) -> IndexDailyRawByDateRunlessEventPlan:
    _validate_window_limit(window_limit)
    raw_partition_keys = discover_raw_index_daily_partition_keys(lake_root)
    p3_report = _load_and_validate_p3_final_audit_report(
        p3_final_audit_report_path,
        lake_root=lake_root,
        raw_partition_keys=raw_partition_keys,
    )
    selected_partition_keys = _select_partition_keys(
        raw_partition_keys,
        partition_keys=partition_keys,
        window_limit=window_limit,
    )
    registered_trade_days = set(
        instance.get_dynamic_partitions(cn_a_index_trade_days.name)
    )
    unregistered_partition_keys = tuple(
        partition_key
        for partition_key in selected_partition_keys
        if partition_key not in registered_trade_days
    )
    if unregistered_partition_keys:
        raise ValueError(
            "raw_index_daily runless event partitions are not registered in "
            f"{cn_a_index_trade_days.name}: {unregistered_partition_keys[:10]}"
        )
    registered_index_codes = tuple(
        sorted(instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )
    if not registered_index_codes:
        raise ValueError(f"{cn_a_index_ts_codes.name} has no registered index codes.")

    source_glob = raw_index_daily_by_code_source_glob(lake_root)
    partition_audits = tuple(
        audit_raw_index_daily_runless_partition(
            lake_root=lake_root,
            duckdb=duckdb,
            partition_key=partition_key,
            source_glob=source_glob,
            registered_index_codes=registered_index_codes,
            p3_final_audit_report_path=p3_final_audit_report_path,
        )
        for partition_key in selected_partition_keys
    )
    return IndexDailyRawByDateRunlessEventPlan(
        selected_partition_keys=selected_partition_keys,
        raw_partition_count=len(raw_partition_keys),
        registered_trade_day_count=len(registered_trade_days),
        p3_final_audit_report_path=p3_final_audit_report_path,
        p3_final_audit_summary=p3_report,
        source_glob=source_glob,
        partition_audits=partition_audits,
    )


def report_raw_index_daily_recent_window_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb: DuckDBResource,
    p3_final_audit_report_path: Path,
    partition_keys: Sequence[str] | None = None,
    window_limit: int = RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT,
    dry_run: bool = True,
    skip_existing_ready: bool = True,
) -> IndexDailyRawByDateRunlessEventReport:
    plan = plan_raw_index_daily_recent_window_events(
        instance=instance,
        lake_root=lake_root,
        duckdb=duckdb,
        p3_final_audit_report_path=p3_final_audit_report_path,
        partition_keys=partition_keys,
        window_limit=window_limit,
    )
    readiness_spec = AssetReadinessSpec(RAW_INDEX_DAILY_ASSET_KEY, RAW_INDEX_DAILY_CHECKS)
    skipped_ready_partition_keys = []
    blocked_existing_partition_keys = []
    pending_partition_audits = []
    for audit in plan.partition_audits:
        status = asset_readiness_status(
            instance,
            readiness_spec,
            partition_key=audit.partition_key,
        )
        if skip_existing_ready and status.ready:
            skipped_ready_partition_keys.append(audit.partition_key)
            continue
        if status.materialized and not status.ready:
            blocked_existing_partition_keys.append(audit.partition_key)
            continue
        pending_partition_audits.append(audit)

    planned_new_event_count = sum(
        1 + len(RAW_INDEX_DAILY_CHECKS)
        for audit in pending_partition_audits
        if audit.passed
    )
    report = IndexDailyRawByDateRunlessEventReport(
        plan=plan,
        dry_run=dry_run,
        reported_partition_keys=(),
        skipped_ready_partition_keys=tuple(skipped_ready_partition_keys),
        blocked_existing_partition_keys=tuple(blocked_existing_partition_keys),
        planned_new_event_count=planned_new_event_count,
        reported_event_count=0,
    )
    if dry_run:
        return report
    _raise_if_report_should_stop(report)

    reported_partition_keys = []
    reported_event_count = 0
    for audit in pending_partition_audits:
        if not audit.passed:
            continue
        reported_event_count += _report_partition_events(instance, audit)
        reported_partition_keys.append(audit.partition_key)

    return IndexDailyRawByDateRunlessEventReport(
        plan=plan,
        dry_run=False,
        reported_partition_keys=tuple(reported_partition_keys),
        skipped_ready_partition_keys=tuple(skipped_ready_partition_keys),
        blocked_existing_partition_keys=tuple(blocked_existing_partition_keys),
        planned_new_event_count=planned_new_event_count,
        reported_event_count=reported_event_count,
    )


def audit_raw_index_daily_recent_window_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb: DuckDBResource,
    p3_final_audit_report_path: Path,
    partition_keys: Sequence[str] | None = None,
    window_limit: int = RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT,
    forbidden_partition_keys: Sequence[str] = (),
) -> IndexDailyRawByDateRunlessFinalAudit:
    plan = plan_raw_index_daily_recent_window_events(
        instance=instance,
        lake_root=lake_root,
        duckdb=duckdb,
        p3_final_audit_report_path=p3_final_audit_report_path,
        partition_keys=partition_keys,
        window_limit=window_limit,
    )
    readiness_spec = AssetReadinessSpec(RAW_INDEX_DAILY_ASSET_KEY, RAW_INDEX_DAILY_CHECKS)
    ready_partition_keys = []
    not_ready_partition_keys = []
    for partition_key in plan.selected_partition_keys:
        status = asset_readiness_status(
            instance,
            readiness_spec,
            partition_key=partition_key,
        )
        if status.ready:
            ready_partition_keys.append(partition_key)
        else:
            not_ready_partition_keys.append(partition_key)

    forbidden_statuses: dict[str, Mapping[str, Any]] = {}
    for partition_key in tuple(
        normalize_iso_trade_date(key) for key in forbidden_partition_keys
    ):
        forbidden_statuses[partition_key] = _forbidden_partition_status(
            instance,
            partition_key,
        )

    should_stop = bool(not_ready_partition_keys) or any(
        status["materialization_count"] or status["check_event_count"]
        for status in forbidden_statuses.values()
    )
    return IndexDailyRawByDateRunlessFinalAudit(
        selected_partition_keys=plan.selected_partition_keys,
        ready_partition_keys=tuple(ready_partition_keys),
        not_ready_partition_keys=tuple(not_ready_partition_keys),
        forbidden_partition_statuses=forbidden_statuses,
        should_stop=should_stop,
    )


def audit_raw_index_daily_runless_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_key: str,
    source_glob: Path,
    registered_index_codes: Sequence[str],
    p3_final_audit_report_path: Path,
) -> IndexDailyRawByDateRunlessPartitionAudit:
    normalized_partition_key = normalize_iso_trade_date(partition_key)
    raw_file_path = raw_index_daily_path(lake_root, normalized_partition_key)
    file_contract_result = evaluate_raw_index_daily_file_contract(
        (normalized_partition_key,),
        lake_root,
        duckdb,
    )
    current_dg_codes = normalize_index_codes(registered_index_codes)
    current_dg_code_set = set(current_dg_codes)
    expected_trade_date = normalized_partition_key.replace("-", "")
    row_count: int | None = None
    observed_columns: tuple[str, ...] = ()
    actual_codes: tuple[str, ...] = ()
    source_pair_count: int | None = None
    target_pair_count: int | None = None
    source_minus_target_pairs: int | None = None
    target_minus_source_pairs: int | None = None
    source_minus_target_samples: list[dict[str, str]] = []
    target_minus_source_samples: list[dict[str, str]] = []

    if raw_file_path.exists():
        with connect_configured_duckdb() as connection:
            row_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {read_parquet(raw_file_path, hive_partitioning=False)}"
                ).fetchone()[0]
            )
            observed_columns = tuple(
                row[0]
                for row in connection.execute(
                    describe_parquet_query(raw_file_path, hive_partitioning=False)
                ).fetchall()
            )
            actual_codes = tuple(
                row[0]
                for row in connection.execute(
                    f"""
                    SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
                    FROM {read_parquet(raw_file_path, hive_partitioning=False)}
                    WHERE ts_code IS NOT NULL
                      AND trim(CAST(ts_code AS VARCHAR)) != ''
                    ORDER BY ts_code
                    """
                ).fetchall()
            )
            pair_result = _source_target_pair_diff(
                connection=connection,
                source_glob=source_glob,
                target_path=raw_file_path,
                expected_trade_date=expected_trade_date,
            )
            source_pair_count = pair_result["source_pair_count"]
            target_pair_count = pair_result["target_pair_count"]
            source_minus_target_pairs = pair_result["source_minus_target_pairs"]
            target_minus_source_pairs = pair_result["target_minus_source_pairs"]
            source_minus_target_samples = pair_result["source_minus_target_samples"]
            target_minus_source_samples = pair_result["target_minus_source_samples"]

    actual_code_set = set(actual_codes)
    current_dg_missing_codes = tuple(sorted(current_dg_code_set - actual_code_set))
    current_dg_extra_codes = tuple(sorted(actual_code_set - current_dg_code_set))
    actual_code_set_hash = index_code_set_hash(actual_codes) if actual_codes else None
    current_dg_code_set_hash = index_code_set_hash(current_dg_codes)
    file_check = IndexDailyRawByDateRunlessCheckAudit(
        check_name=RAW_INDEX_DAILY_CHECKS[0],
        passed=bool(file_contract_result.passed),
        metadata=file_contract_result.metadata,
    )
    pair_diff_count = (source_minus_target_pairs or 0) + (
        target_minus_source_pairs or 0
    )
    coverage_failed_count = (
        pair_diff_count
        + len(current_dg_missing_codes)
        + len(current_dg_extra_codes)
    )
    coverage_check = IndexDailyRawByDateRunlessCheckAudit(
        check_name=RAW_INDEX_DAILY_CHECKS[1],
        passed=coverage_failed_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=row_count,
            failed_row_count=coverage_failed_count,
            file_path=raw_file_path,
            input_file_paths=(source_glob,),
            extra_metadata={
                "partition_key": normalized_partition_key,
                "coverage_basis": RAW_INDEX_DAILY_COVERAGE_BASIS,
                "bootstrap_method": RAW_INDEX_DAILY_BOOTSTRAP_METHOD,
                "event_backfill_scope": RAW_INDEX_DAILY_EVENT_BACKFILL_SCOPE,
                "p3_final_audit_report_path": str(p3_final_audit_report_path),
                "source_pair_count": source_pair_count,
                "target_pair_count": target_pair_count,
                "source_minus_target_pairs": source_minus_target_pairs,
                "target_minus_source_pairs": target_minus_source_pairs,
                "source_minus_target_samples": source_minus_target_samples,
                "target_minus_source_samples": target_minus_source_samples,
                "current_dg_code_count": len(current_dg_codes),
                "current_dg_code_set_hash": current_dg_code_set_hash,
                "actual_code_count": len(actual_codes),
                "actual_code_set_hash": actual_code_set_hash,
                "current_dg_missing_code_count": len(current_dg_missing_codes),
                "current_dg_extra_code_count": len(current_dg_extra_codes),
                "current_dg_missing_code_samples": list(current_dg_missing_codes[:10]),
                "current_dg_extra_code_samples": list(current_dg_extra_codes[:10]),
            },
        ),
    )
    checks = (file_check, coverage_check)
    return IndexDailyRawByDateRunlessPartitionAudit(
        partition_key=normalized_partition_key,
        raw_file_path=raw_file_path,
        passed=all(check.passed for check in checks),
        row_count=row_count,
        observed_columns=observed_columns,
        actual_code_count=len(actual_codes),
        actual_code_set_hash=actual_code_set_hash,
        current_dg_code_count=len(current_dg_codes),
        current_dg_code_set_hash=current_dg_code_set_hash,
        source_pair_count=source_pair_count,
        target_pair_count=target_pair_count,
        source_minus_target_pairs=source_minus_target_pairs,
        target_minus_source_pairs=target_minus_source_pairs,
        current_dg_missing_code_count=len(current_dg_missing_codes),
        current_dg_extra_code_count=len(current_dg_extra_codes),
        checks=checks,
    )


def write_report_json(payload: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )


def _report_partition_events(
    instance: dg.DagsterInstance,
    audit: IndexDailyRawByDateRunlessPartitionAudit,
) -> int:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=RAW_INDEX_DAILY_ASSET_KEY,
            partition=audit.partition_key,
            metadata=build_materialization_metadata(
                uri=audit.raw_file_path,
                row_count=audit.row_count,
                observed_columns=audit.observed_columns,
                extra_metadata={
                    "partition_key": audit.partition_key,
                    "source_system": SourceSystem.PROD_CORE_DB.value,
                    "bootstrap_method": RAW_INDEX_DAILY_BOOTSTRAP_METHOD,
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": RAW_INDEX_DAILY_EVENT_BACKFILL_SCOPE,
                    "coverage_basis": RAW_INDEX_DAILY_COVERAGE_BASIS,
                    "p3_final_audit_report_path": str(
                        audit.checks[1].metadata[
                            "goldenshare/p3_final_audit_report_path"
                        ]
                    ),
                    "actual_code_count": audit.actual_code_count,
                    "actual_code_set_hash": audit.actual_code_set_hash,
                    "current_dg_code_count": audit.current_dg_code_count,
                    "current_dg_code_set_hash": audit.current_dg_code_set_hash,
                },
            ),
        )
    )
    materialization = _latest_materialization(
        instance,
        RAW_INDEX_DAILY_ASSET_KEY,
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
                asset_key=RAW_INDEX_DAILY_ASSET_KEY,
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
        dg.AssetRecordsFilter(asset_key=asset_key, asset_partitions=[partition_key]),
        limit=1,
    )
    if not result.records:
        raise RuntimeError(f"Expected materialization after runless report: {asset_key}")
    return result.records[0]


def _load_and_validate_p3_final_audit_report(
    p3_final_audit_report_path: Path,
    *,
    lake_root: Path,
    raw_partition_keys: tuple[str, ...],
) -> Mapping[str, Any]:
    if not p3_final_audit_report_path.exists():
        raise ValueError(f"P3 final audit report does not exist: {p3_final_audit_report_path}")
    payload = json.loads(p3_final_audit_report_path.read_text())
    failures = payload.get("failures")
    if failures:
        raise ValueError(f"P3 final audit report has failures: {failures}")
    if payload.get("forbidden_partition_exists"):
        raise ValueError("P3 final audit report says forbidden partition exists.")
    expected_file_count = int(payload.get("target_file_count", -1))
    if expected_file_count != len(raw_partition_keys):
        raise ValueError(
            "P3 final audit target_file_count does not match current raw/index_daily "
            f"files: report={expected_file_count}, current={len(raw_partition_keys)}"
        )
    target_dir_count = int(payload.get("target_partition_dir_count", -1))
    if target_dir_count != len(raw_partition_keys):
        raise ValueError(
            "P3 final audit target_partition_dir_count does not match current "
            f"partitions: report={target_dir_count}, current={len(raw_partition_keys)}"
        )
    if raw_partition_keys:
        target_min = str(payload.get("target_min_trade_date"))
        target_max = str(payload.get("target_max_trade_date"))
        current_min = raw_partition_keys[0].replace("-", "")
        current_max = raw_partition_keys[-1].replace("-", "")
        if target_min != current_min or target_max != current_max:
            raise ValueError(
                "P3 final audit date range does not match current raw/index_daily "
                f"files: report={target_min}..{target_max}, "
                f"current={current_min}..{current_max}"
            )
    expected_target_root = str(lake_root / "raw" / "index_daily")
    if str(payload.get("target_root")) != expected_target_root:
        raise ValueError(
            "P3 final audit target_root does not match lake root: "
            f"report={payload.get('target_root')}, expected={expected_target_root}"
        )
    zero_fields = (
        "source_minus_target_pairs",
        "source_minus_target_rows",
        "target_minus_source_pairs",
        "target_minus_source_rows",
        "target_duplicate_pairs",
        "target_excluded_rows",
        "target_null_key_rows",
    )
    non_zero_fields = {
        field: payload.get(field)
        for field in zero_fields
        if int(payload.get(field, -1)) != 0
    }
    if non_zero_fields:
        raise ValueError(f"P3 final audit has non-zero diff fields: {non_zero_fields}")
    return {
        "target_file_count": payload.get("target_file_count"),
        "target_rows": payload.get("target_rows"),
        "target_distinct_pairs": payload.get("target_distinct_pairs"),
        "target_min_trade_date": payload.get("target_min_trade_date"),
        "target_max_trade_date": payload.get("target_max_trade_date"),
        "source_minus_target_pairs": payload.get("source_minus_target_pairs"),
        "target_minus_source_pairs": payload.get("target_minus_source_pairs"),
    }


def _select_partition_keys(
    raw_partition_keys: tuple[str, ...],
    *,
    partition_keys: Sequence[str] | None,
    window_limit: int,
) -> tuple[str, ...]:
    if partition_keys is None:
        if len(raw_partition_keys) < window_limit:
            raise ValueError(
                "raw_index_daily recent-window runless plan requires at least "
                f"{window_limit} partitions, found {len(raw_partition_keys)}."
            )
        return raw_partition_keys[-window_limit:]
    selected_partition_keys = tuple(
        sorted({normalize_iso_trade_date(partition_key) for partition_key in partition_keys})
    )
    missing_partition_keys = tuple(
        partition_key
        for partition_key in selected_partition_keys
        if partition_key not in raw_partition_keys
    )
    if missing_partition_keys:
        raise ValueError(
            f"Selected raw_index_daily partitions do not have files: {missing_partition_keys}"
        )
    if len(selected_partition_keys) > RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT:
        raise ValueError(
            "Selected raw_index_daily runless partition count exceeds recent window "
            f"limit {RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT}: {len(selected_partition_keys)}"
        )
    return selected_partition_keys


def _validate_window_limit(window_limit: int) -> None:
    if window_limit <= 0:
        raise ValueError("window_limit must be positive.")
    if window_limit > RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT:
        raise ValueError(
            "window_limit must not exceed raw_index_daily recent-window limit "
            f"{RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT}: {window_limit}"
        )


def _source_target_pair_diff(
    *,
    connection,
    source_glob: Path,
    target_path: Path,
    expected_trade_date: str,
) -> dict[str, Any]:
    source_pairs_sql = f"""
    SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code,
           CAST(trade_date AS VARCHAR) AS trade_date
    FROM {read_parquet(source_glob, hive_partitioning=False, union_by_name=True)}
    WHERE CAST(trade_date AS VARCHAR) = {duckdb_string(expected_trade_date)}
    """
    target_pairs_sql = f"""
    SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code,
           CAST(trade_date AS VARCHAR) AS trade_date
    FROM {read_parquet(target_path, hive_partitioning=False)}
    WHERE CAST(trade_date AS VARCHAR) = {duckdb_string(expected_trade_date)}
    """
    counts = connection.execute(
        f"""
        WITH source_pairs AS ({source_pairs_sql}),
             target_pairs AS ({target_pairs_sql}),
             source_minus_target AS (
               SELECT * FROM source_pairs
               EXCEPT
               SELECT * FROM target_pairs
             ),
             target_minus_source AS (
               SELECT * FROM target_pairs
               EXCEPT
               SELECT * FROM source_pairs
             )
        SELECT
          (SELECT count(*) FROM source_pairs) AS source_pair_count,
          (SELECT count(*) FROM target_pairs) AS target_pair_count,
          (SELECT count(*) FROM source_minus_target) AS source_minus_target_pairs,
          (SELECT count(*) FROM target_minus_source) AS target_minus_source_pairs
        """
    ).fetchone()
    source_minus_rows = connection.execute(
        f"""
        WITH source_pairs AS ({source_pairs_sql}),
             target_pairs AS ({target_pairs_sql})
        SELECT ts_code, trade_date
        FROM (
          SELECT * FROM source_pairs
          EXCEPT
          SELECT * FROM target_pairs
        ) diff
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    target_minus_rows = connection.execute(
        f"""
        WITH source_pairs AS ({source_pairs_sql}),
             target_pairs AS ({target_pairs_sql})
        SELECT ts_code, trade_date
        FROM (
          SELECT * FROM target_pairs
          EXCEPT
          SELECT * FROM source_pairs
        ) diff
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    return {
        "source_pair_count": int(counts[0]),
        "target_pair_count": int(counts[1]),
        "source_minus_target_pairs": int(counts[2]),
        "target_minus_source_pairs": int(counts[3]),
        "source_minus_target_samples": _pair_samples(source_minus_rows),
        "target_minus_source_samples": _pair_samples(target_minus_rows),
    }


def _pair_samples(rows: Sequence[Sequence[Any]]) -> list[dict[str, str]]:
    return [
        {"ts_code": str(row[0]), "trade_date": str(row[1])}
        for row in rows
    ]


def _raise_if_report_should_stop(
    report: IndexDailyRawByDateRunlessEventReport,
) -> None:
    if report.plan.failed_partition_count:
        failures = {
            audit.partition_key: audit.failed_check_names
            for audit in report.plan.partition_audits
            if audit.failed_check_names
        }
        raise ValueError(f"raw_index_daily runless audit failed: {failures}")
    if report.plan.planned_event_count > RAW_INDEX_DAILY_MAX_EVENT_COUNT:
        raise ValueError(
            "raw_index_daily runless planned events exceed max event count: "
            f"{report.plan.planned_event_count} > {RAW_INDEX_DAILY_MAX_EVENT_COUNT}"
        )
    if report.blocked_existing_partition_keys:
        raise ValueError(
            "raw_index_daily runless target partitions already have non-ready "
            "materialization/check state: "
            f"{report.blocked_existing_partition_keys}"
        )


def _forbidden_partition_status(
    instance: dg.DagsterInstance,
    partition_key: str,
) -> Mapping[str, Any]:
    materializations = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=RAW_INDEX_DAILY_ASSET_KEY,
            asset_partitions=[partition_key],
        ),
        limit=1,
    ).records
    check_counts = {
        check_name: _asset_check_event_count_for_partition(
            instance,
            check_name,
            partition_key,
        )
        for check_name in RAW_INDEX_DAILY_CHECKS
    }
    return {
        "materialization_count": len(materializations),
        "check_event_count": sum(check_counts.values()),
        "check_event_counts": check_counts,
    }


def _asset_check_event_count_for_partition(
    instance: dg.DagsterInstance,
    check_name: str,
    partition_key: str,
) -> int:
    check_key = dg.AssetCheckKey(RAW_INDEX_DAILY_ASSET_KEY, check_name)
    records = instance.event_log_storage.get_asset_check_execution_history(
        check_key,
        limit=1000,
    )
    count = 0
    for record in records:
        event = getattr(record, "event", None)
        dagster_event = getattr(event, "dagster_event", None) if event else None
        event_partition = (
            getattr(event, "partition_key", None)
            or getattr(dagster_event, "partition", None)
        )
        if event_partition == partition_key:
            count += 1
    return count


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "value"):
        return _jsonable(value.value)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value
