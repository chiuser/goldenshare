"""Trusted historical Dagster materialization recovery for stock-year assets.

This offline tool restores only the UI materialization state that was removed
during Dagster event-history compaction.  It deliberately never opens Lake
files, runs DuckDB, reports checks, or invokes production jobs and sensors.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import dagster as dg

from orchestrator.defs.assets.stk_mins import GOLD_STK_MINS_QFQ_ASSETS
from orchestrator.defs.assets.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_HISTORY_START_DATE
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
)


SCHEMA_VERSION = 2
PLAN_PHASE = "P4A_trusted_control_plane_inventory"
RECONCILIATION_METHOD = "historical_verified_state_recovery_v1"
RECONCILIATION_BASIS = "prior_verified_historical_checks_deleted_during_db_cleanup"
HOT_WINDOW_SIZE = 20
WRITE_CHUNK_SIZE = 500
ACTIVE_RUN_STATUSES = ("QUEUED", "STARTING", "STARTED", "CANCELING")


class StockYearMaterializationReconciliationError(RuntimeError):
    """Raised when trusted historical state recovery must fail closed."""


def _qfq_asset_keys() -> tuple[str, ...]:
    result: list[str] = []
    for asset_definition in GOLD_STK_MINS_QFQ_ASSETS:
        keys = tuple(asset_definition.keys)
        if len(keys) != 1 or len(keys[0].path) != 1:
            raise StockYearMaterializationReconciliationError(
                f"Expected one unprefixed QFQ asset key, got {keys!r}."
            )
        result.append(keys[0].path[0])
    return tuple(result)


TARGET_ASSET_KEYS = tuple(sorted(_qfq_asset_keys() + GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES))
if len(TARGET_ASSET_KEYS) != 14 or len(set(TARGET_ASSET_KEYS)) != 14:
    raise StockYearMaterializationReconciliationError(
        f"Expected exactly 14 target assets, got {TARGET_ASSET_KEYS!r}."
    )

RECOVERABLE_UNBOUND_REPAIR_COMPLETION_ASSET_KEYS = frozenset(
    GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES
)
if not RECOVERABLE_UNBOUND_REPAIR_COMPLETION_ASSET_KEYS <= set(TARGET_ASSET_KEYS):
    raise StockYearMaterializationReconciliationError(
        "Recoverable repair completion assets must be within the P4 target asset set."
    )


@dataclass(frozen=True, slots=True)
class StockYearMaterializationCandidate:
    asset_key: str
    partition_key: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "StockYearMaterializationCandidate":
        asset_key = str(payload["asset_key"])
        partition_key = str(payload["partition_key"])
        if asset_key not in TARGET_ASSET_KEYS:
            raise StockYearMaterializationReconciliationError(
                f"Candidate asset is outside the approved P4 scope: {asset_key}."
            )
        _parse_iso_date(partition_key)
        return cls(asset_key=asset_key, partition_key=partition_key)

    def to_dict(self) -> dict[str, str]:
        return {"asset_key": self.asset_key, "partition_key": self.partition_key}


@dataclass(frozen=True, slots=True)
class StockYearMaterializationPlan:
    report_path: Path
    manifest_path: Path
    plan_fingerprint: str
    candidates: tuple[StockYearMaterializationCandidate, ...]
    report: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StockYearMaterializationApplyReport:
    plan_fingerprint: str
    batch_id: str
    backup_manifest_path: str
    backup_manifest_sha256: str
    planned_event_count: int
    reported_event_count: int
    control_counts_before: Mapping[str, int]
    control_counts_after: Mapping[str, int]
    chunk_reports: tuple[Mapping[str, object], ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_fingerprint": self.plan_fingerprint,
            "batch_id": self.batch_id,
            "backup_manifest_path": self.backup_manifest_path,
            "backup_manifest_sha256": self.backup_manifest_sha256,
            "planned_event_count": self.planned_event_count,
            "reported_event_count": self.reported_event_count,
            "control_counts_before": dict(self.control_counts_before),
            "control_counts_after": dict(self.control_counts_after),
            "chunk_reports": [dict(report) for report in self.chunk_reports],
            "elapsed_ms": self.elapsed_ms,
        }


def build_stock_year_materialization_plan(
    *,
    instance: dg.DagsterInstance,
    output_dir: Path,
) -> StockYearMaterializationPlan:
    """Build a read-only P4 plan from the Dagster control plane only."""

    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = _state_snapshot(instance)
    candidates, asset_reports = _classify_candidates(snapshot)
    fingerprint = _hash_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "target_asset_keys": TARGET_ASSET_KEYS,
            "history_start_date": STK_MINS_QFQ_HISTORY_START_DATE,
            "registered_history_keys": sorted(snapshot["history_partition_keys"]),
            "hot_window_keys": sorted(snapshot["hot_window_keys"]),
            "materialized_by_asset": {
                asset_key: sorted(snapshot["materialized_by_asset"][asset_key])
                for asset_key in TARGET_ASSET_KEYS
            },
            "protected_check_partitions_by_asset": {
                asset_key: sorted(snapshot["protected_check_partitions_by_asset"][asset_key])
                for asset_key in TARGET_ASSET_KEYS
            },
            "unbound_repair_completion_marker_partitions_by_asset": {
                asset_key: sorted(
                    snapshot["unbound_repair_completion_marker_partitions_by_asset"][asset_key]
                )
                for asset_key in TARGET_ASSET_KEYS
            },
            "safe_candidates": [candidate.to_dict() for candidate in candidates],
        }
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = output_dir / (
        "dagster_historical_materialization_reconciliation_stock_year_trusted_candidates_"
        f"{timestamp}.jsonl"
    )
    _write_jsonl(manifest_path, (candidate.to_dict() for candidate in candidates))
    report = {
        "schema_version": SCHEMA_VERSION,
        "phase": PLAN_PHASE,
        "read_only": True,
        "reconciliation_method": RECONCILIATION_METHOD,
        "reconciliation_basis": RECONCILIATION_BASIS,
        "history_start_date": STK_MINS_QFQ_HISTORY_START_DATE,
        "partition_set": cn_a_stock_mins_silver_trade_days.name,
        "target_asset_keys": list(TARGET_ASSET_KEYS),
        "registered_partitions": {
            "all_count": len(snapshot["registered_partition_keys"]),
            "history": _date_summary(snapshot["history_partition_keys"]),
            "before_history_start": _date_summary(snapshot["before_history_start_keys"]),
            "invalid_key_count": len(snapshot["invalid_partition_keys"]),
            "invalid_keys": list(snapshot["invalid_partition_keys"][:20]),
            "sorted_hash": _hash_payload(sorted(snapshot["history_partition_keys"])),
        },
        "hot_window": _date_summary(snapshot["hot_window_keys"]),
        "asset_reports": asset_reports,
        "planned_materialization_event_count": len(candidates),
        "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": _sha256_path(manifest_path),
        "candidate_manifest_hash": _hash_payload(
            [candidate.to_dict() for candidate in candidates]
        ),
        "active_run_statuses": snapshot["active_run_statuses"],
        "control_counts": snapshot["control_counts"],
        "should_stop": bool(snapshot["stop_reasons"]),
        "stop_reasons": list(snapshot["stop_reasons"]),
        "plan_fingerprint": fingerprint,
        "performance": {
            "business_row_scans": 0,
            "lake_access": False,
            "hot_window_size": HOT_WINDOW_SIZE,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }
    report_path = output_dir / (
        "dagster_historical_materialization_reconciliation_stock_year_trusted_plan_"
        f"{timestamp}.json"
    )
    _write_json(report_path, report)
    return StockYearMaterializationPlan(
        report_path=report_path,
        manifest_path=manifest_path,
        plan_fingerprint=fingerprint,
        candidates=candidates,
        report=report,
    )


def load_stock_year_materialization_plan(
    plan_report_path: Path,
) -> StockYearMaterializationPlan:
    payload = json.loads(plan_report_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise StockYearMaterializationReconciliationError("Unsupported plan schema version.")
    if payload.get("phase") != PLAN_PHASE or payload.get("read_only") is not True:
        raise StockYearMaterializationReconciliationError("Apply requires a P4A read-only plan.")
    if payload.get("should_stop"):
        raise StockYearMaterializationReconciliationError(
            f"Plan has stop reasons: {payload.get('stop_reasons', [])}."
        )
    manifest_path = Path(str(payload["candidate_manifest_path"]))
    if not manifest_path.is_file():
        raise StockYearMaterializationReconciliationError(
            f"Candidate manifest is missing: {manifest_path}."
        )
    if _sha256_path(manifest_path) != str(payload["candidate_manifest_sha256"]):
        raise StockYearMaterializationReconciliationError("Candidate manifest SHA-256 mismatch.")
    candidates = tuple(
        StockYearMaterializationCandidate.from_dict(json.loads(line))
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if len(candidates) != int(payload["planned_materialization_event_count"]):
        raise StockYearMaterializationReconciliationError(
            "Candidate manifest count does not match the plan report."
        )
    if tuple(sorted(candidates, key=_candidate_sort_key)) != candidates:
        raise StockYearMaterializationReconciliationError("Candidate manifest is not stably sorted.")
    return StockYearMaterializationPlan(
        report_path=plan_report_path,
        manifest_path=manifest_path,
        plan_fingerprint=str(payload["plan_fingerprint"]),
        candidates=candidates,
        report=payload,
    )


def apply_stock_year_materialization_plan(
    *,
    instance: dg.DagsterInstance,
    plan: StockYearMaterializationPlan,
    backup_manifest_path: Path,
    output_dir: Path,
) -> StockYearMaterializationApplyReport:
    """Append only approved materialization events after a fresh state recheck."""

    if not backup_manifest_path.is_file():
        raise StockYearMaterializationReconciliationError(
            f"Verified backup manifest is required: {backup_manifest_path}."
        )
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    fresh_plan = build_stock_year_materialization_plan(instance=instance, output_dir=output_dir)
    if fresh_plan.plan_fingerprint != plan.plan_fingerprint or fresh_plan.candidates != plan.candidates:
        raise StockYearMaterializationReconciliationError(
            "P4A plan is stale; regenerate and review a new read-only plan before apply."
        )
    _assert_no_active_runs()
    control_counts_before = _control_counts()
    batch_id = str(uuid.uuid4())
    reported_count = 0
    chunk_reports: list[Mapping[str, object]] = []
    for chunk_index, chunk in enumerate(_chunks(plan.candidates, WRITE_CHUNK_SIZE), start=1):
        _assert_chunk_is_current(instance=instance, candidates=chunk)
        for candidate in chunk:
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=dg.AssetKey(candidate.asset_key),
                    partition=candidate.partition_key,
                    metadata=build_materialization_metadata(
                        uri=_canonical_uri(candidate.asset_key),
                        extra_metadata={
                            "reconciliation_method": RECONCILIATION_METHOD,
                            "reconciliation_basis": RECONCILIATION_BASIS,
                            "reconciliation_batch_id": batch_id,
                            "reconciliation_plan_fingerprint": plan.plan_fingerprint,
                            "check_events_reported": False,
                        },
                    ),
                )
            )
            reported_count += 1
        chunk_report = {
            "chunk_index": chunk_index,
            "candidate_count": len(chunk),
            "reported_count": len(chunk),
            "first_candidate": chunk[0].to_dict(),
            "last_candidate": chunk[-1].to_dict(),
        }
        chunk_reports.append(chunk_report)
        write_stock_year_materialization_report(
            output_dir,
            f"progress_{chunk_index:03d}",
            chunk_report,
        )

    control_counts_after = _control_counts()
    _assert_control_counts_unchanged(
        before=control_counts_before,
        after=control_counts_after,
    )
    return StockYearMaterializationApplyReport(
        plan_fingerprint=plan.plan_fingerprint,
        batch_id=batch_id,
        backup_manifest_path=str(backup_manifest_path),
        backup_manifest_sha256=_sha256_path(backup_manifest_path),
        planned_event_count=len(plan.candidates),
        reported_event_count=reported_count,
        control_counts_before=control_counts_before,
        control_counts_after=control_counts_after,
        chunk_reports=tuple(chunk_reports),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def audit_stock_year_materialization_plan(
    *,
    instance: dg.DagsterInstance,
    plan: StockYearMaterializationPlan,
) -> dict[str, object]:
    missing_by_asset: dict[str, list[str]] = {}
    for asset_key in TARGET_ASSET_KEYS:
        expected = {
            candidate.partition_key
            for candidate in plan.candidates
            if candidate.asset_key == asset_key
        }
        actual = set(instance.get_materialized_partitions(dg.AssetKey(asset_key)))
        missing = sorted(expected - actual)
        if missing:
            missing_by_asset[asset_key] = missing[:20]
    return {
        "plan_fingerprint": plan.plan_fingerprint,
        "candidate_count": len(plan.candidates),
        "missing_materialization_sample_by_asset": missing_by_asset,
        "all_selected_candidates_materialized": not missing_by_asset,
        "control_counts": _control_counts(),
    }


def write_stock_year_materialization_report(
    output_dir: Path,
    stage: str,
    payload: Mapping[str, object],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / (
        "dagster_historical_materialization_reconciliation_stock_year_trusted_"
        f"{stage}_{timestamp}.json"
    )
    _write_json(path, dict(payload))
    return path


def _state_snapshot(instance: dg.DagsterInstance) -> dict[str, Any]:
    registered_partition_keys = set(
        instance.get_dynamic_partitions(cn_a_stock_mins_silver_trade_days.name)
    )
    start_date = date.fromisoformat(STK_MINS_QFQ_HISTORY_START_DATE)
    history_partition_keys: set[str] = set()
    before_history_start_keys: set[str] = set()
    invalid_partition_keys: list[str] = []
    for partition_key in registered_partition_keys:
        try:
            parsed = _parse_iso_date(partition_key)
        except StockYearMaterializationReconciliationError:
            invalid_partition_keys.append(partition_key)
            continue
        if parsed < start_date:
            before_history_start_keys.add(partition_key)
        else:
            history_partition_keys.add(partition_key)
    materialized_by_asset = {
        asset_key: set(instance.get_materialized_partitions(dg.AssetKey(asset_key)))
        for asset_key in TARGET_ASSET_KEYS
    }
    active_run_statuses = _active_run_statuses()
    stop_reasons: list[str] = []
    if invalid_partition_keys:
        stop_reasons.append("invalid_registered_partition_keys")
    if active_run_statuses:
        stop_reasons.append("active_dagster_runs")
    (
        protected_check_partitions_by_asset,
        unbound_repair_completion_marker_partitions_by_asset,
    ) = _check_partition_sets(TARGET_ASSET_KEYS)
    return {
        "registered_partition_keys": registered_partition_keys,
        "history_partition_keys": history_partition_keys,
        "before_history_start_keys": before_history_start_keys,
        "invalid_partition_keys": tuple(sorted(invalid_partition_keys)),
        "hot_window_keys": set(sorted(history_partition_keys)[-HOT_WINDOW_SIZE:]),
        "materialized_by_asset": materialized_by_asset,
        "protected_check_partitions_by_asset": protected_check_partitions_by_asset,
        "unbound_repair_completion_marker_partitions_by_asset": (
            unbound_repair_completion_marker_partitions_by_asset
        ),
        "active_run_statuses": active_run_statuses,
        "control_counts": _control_counts(),
        "stop_reasons": tuple(stop_reasons),
    }


def _classify_candidates(
    snapshot: Mapping[str, Any],
) -> tuple[tuple[StockYearMaterializationCandidate, ...], dict[str, object]]:
    candidates: list[StockYearMaterializationCandidate] = []
    reports: dict[str, object] = {}
    history_partition_keys = set(snapshot["history_partition_keys"])
    hot_window_keys = set(snapshot["hot_window_keys"])
    for asset_key in TARGET_ASSET_KEYS:
        materialized = set(snapshot["materialized_by_asset"][asset_key]) & history_partition_keys
        protected_checks = (
            set(snapshot["protected_check_partitions_by_asset"][asset_key])
            & history_partition_keys
        )
        unbound_repair_completion_markers = (
            set(snapshot["unbound_repair_completion_marker_partitions_by_asset"][asset_key])
            & history_partition_keys
        )
        check_without_materialization = protected_checks - materialized
        hot_window_excluded = (
            history_partition_keys - materialized - protected_checks
        ) & hot_window_keys
        safe_candidates = history_partition_keys - materialized - protected_checks - hot_window_keys
        candidates.extend(
            StockYearMaterializationCandidate(asset_key=asset_key, partition_key=partition_key)
            for partition_key in sorted(safe_candidates)
        )
        reports[asset_key] = {
            "registered_history_partition_count": len(history_partition_keys),
            "already_materialized": _date_summary(materialized),
            "check_without_materialization": _date_summary(check_without_materialization),
            "unbound_repair_completion_marker_only": _date_summary(
                unbound_repair_completion_markers - protected_checks
            ),
            "hot_window_excluded": _date_summary(hot_window_excluded),
            "safe_candidate": _date_summary(safe_candidates),
        }
    return tuple(sorted(candidates, key=_candidate_sort_key)), reports


def _assert_chunk_is_current(
    *,
    instance: dg.DagsterInstance,
    candidates: Sequence[StockYearMaterializationCandidate],
) -> None:
    _assert_no_active_runs()
    registered = set(instance.get_dynamic_partitions(cn_a_stock_mins_silver_trade_days.name))
    history_keys, invalid_keys = _history_partition_keys(registered)
    if invalid_keys:
        raise StockYearMaterializationReconciliationError(
            f"Registered partition keys are invalid: {invalid_keys[:20]}."
        )
    hot_window = set(sorted(history_keys)[-HOT_WINDOW_SIZE:])
    materialized_by_asset = {
        asset_key: set(instance.get_materialized_partitions(dg.AssetKey(asset_key)))
        for asset_key in {candidate.asset_key for candidate in candidates}
    }
    protected_check_pairs = _protected_check_candidate_pairs(candidates)
    for candidate in candidates:
        pair = (candidate.asset_key, candidate.partition_key)
        if candidate.partition_key not in history_keys:
            raise StockYearMaterializationReconciliationError(
                f"Candidate partition is no longer registered: {candidate.asset_key}[{candidate.partition_key}]."
            )
        if candidate.partition_key in hot_window:
            raise StockYearMaterializationReconciliationError(
                f"Candidate entered the current hot window: {candidate.asset_key}[{candidate.partition_key}]."
            )
        if candidate.partition_key in materialized_by_asset[candidate.asset_key]:
            raise StockYearMaterializationReconciliationError(
                f"Candidate now has a materialization: {candidate.asset_key}[{candidate.partition_key}]."
            )
        if pair in protected_check_pairs:
            raise StockYearMaterializationReconciliationError(
                f"Candidate now has check state: {candidate.asset_key}[{candidate.partition_key}]."
            )


def _history_partition_keys(registered: set[str]) -> tuple[set[str], list[str]]:
    start_date = date.fromisoformat(STK_MINS_QFQ_HISTORY_START_DATE)
    history_keys: set[str] = set()
    invalid_keys: list[str] = []
    for partition_key in registered:
        try:
            parsed = _parse_iso_date(partition_key)
        except StockYearMaterializationReconciliationError:
            invalid_keys.append(partition_key)
            continue
        if parsed >= start_date:
            history_keys.add(partition_key)
    return history_keys, sorted(invalid_keys)


def _check_partition_sets(
    asset_keys: Sequence[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    protected = {asset_key: set() for asset_key in asset_keys}
    unbound_repair_completion_markers = {asset_key: set() for asset_key in asset_keys}
    encoded_keys = ", ".join(
        "'" + json.dumps([asset_key]).replace("'", "''") + "'"
        for asset_key in asset_keys
    )
    rows = _psql_rows(
        """
        SELECT asset_key, partition, check_name, execution_status, materialization_event_storage_id
        FROM asset_check_executions
        WHERE partition IS NOT NULL
          AND asset_key IN ("""
        + encoded_keys
        + """
          )
        GROUP BY asset_key, partition, check_name, execution_status, materialization_event_storage_id
        ORDER BY asset_key, partition, check_name, execution_status, materialization_event_storage_id
        """
    )
    checks_by_pair: dict[tuple[str, str], list[tuple[str, str, int | None]]] = {}
    for (
        encoded_asset_key,
        partition_key,
        check_name,
        execution_status,
        materialization_storage_id,
    ) in rows:
        asset_key = _decode_target_asset_key(encoded_asset_key, protected)
        key = (asset_key, str(partition_key))
        checks_by_pair.setdefault(key, []).append(
            (
                str(check_name),
                str(execution_status),
                _optional_storage_id(materialization_storage_id),
            )
        )
    for (asset_key, partition_key), checks in checks_by_pair.items():
        if all(
            _is_unbound_repair_completion_marker(
                asset_key=asset_key,
                check_name=check_name,
                execution_status=execution_status,
                materialization_storage_id=materialization_storage_id,
            )
            for check_name, execution_status, materialization_storage_id in checks
        ):
            unbound_repair_completion_markers[asset_key].add(partition_key)
        else:
            protected[asset_key].add(partition_key)
    return protected, unbound_repair_completion_markers


def _protected_check_candidate_pairs(
    candidates: Sequence[StockYearMaterializationCandidate],
) -> set[tuple[str, str]]:
    if not candidates:
        return set()
    encoded_pairs = ", ".join(
        "(" + "'" + json.dumps([candidate.asset_key]).replace("'", "''") + "', "
        + "'" + candidate.partition_key.replace("'", "''") + "')"
        for candidate in candidates
    )
    rows = _psql_rows(
        "SELECT asset_key, partition, check_name, execution_status, materialization_event_storage_id "
        "FROM asset_check_executions "
        "WHERE (asset_key, partition) IN (" + encoded_pairs + ") "
        "GROUP BY asset_key, partition, check_name, execution_status, materialization_event_storage_id "
        "ORDER BY asset_key, partition, check_name, execution_status, materialization_event_storage_id"
    )
    checks_by_pair: dict[tuple[str, str], list[tuple[str, str, int | None]]] = {}
    allowed_asset_keys = {candidate.asset_key for candidate in candidates}
    for (
        encoded_asset_key,
        partition_key,
        check_name,
        execution_status,
        materialization_storage_id,
    ) in rows:
        asset_key = _decode_target_asset_key(encoded_asset_key, allowed_asset_keys)
        key = (asset_key, str(partition_key))
        checks_by_pair.setdefault(key, []).append(
            (
                str(check_name),
                str(execution_status),
                _optional_storage_id(materialization_storage_id),
            )
        )
    return {
        pair
        for pair, checks in checks_by_pair.items()
        if not all(
            _is_unbound_repair_completion_marker(
                asset_key=pair[0],
                check_name=check_name,
                execution_status=execution_status,
                materialization_storage_id=materialization_storage_id,
            )
            for check_name, execution_status, materialization_storage_id in checks
        )
    }


def _decode_target_asset_key(
    encoded_asset_key: object,
    allowed_asset_keys: Mapping[str, object] | set[str],
) -> str:
    decoded = json.loads(str(encoded_asset_key))
    if not isinstance(decoded, list) or len(decoded) != 1 or decoded[0] not in allowed_asset_keys:
        raise StockYearMaterializationReconciliationError(
            f"Unexpected target check asset key: {encoded_asset_key!r}."
        )
    return str(decoded[0])


def _optional_storage_id(value: object) -> int | None:
    if value is None or str(value) == "":
        return None
    return int(str(value))


def _is_unbound_repair_completion_marker(
    *,
    asset_key: str,
    check_name: str,
    execution_status: str,
    materialization_storage_id: int | None,
) -> bool:
    return (
        asset_key in RECOVERABLE_UNBOUND_REPAIR_COMPLETION_ASSET_KEYS
        and check_name == GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME
        and execution_status == "SUCCEEDED"
        and materialization_storage_id is None
    )


def _active_run_statuses() -> dict[str, int]:
    statuses = ", ".join("'" + value + "'" for value in ACTIVE_RUN_STATUSES)
    rows = _psql_rows(
        "SELECT status, count(*) FROM runs WHERE status IN ("
        + statuses
        + ") GROUP BY status ORDER BY status"
    )
    return {status: int(count) for status, count in rows}


def _assert_no_active_runs() -> None:
    statuses = _active_run_statuses()
    if statuses:
        raise StockYearMaterializationReconciliationError(
            f"Active Dagster runs block P4B apply: {statuses}."
        )


def _control_counts() -> dict[str, int]:
    queries = {
        "asset_check_executions": "SELECT count(*) FROM asset_check_executions",
        "asset_check_event_logs": (
            "SELECT count(*) FROM event_logs WHERE dagster_event_type IN "
            "('ASSET_CHECK_EVALUATION', 'ASSET_CHECK_EVALUATION_PLANNED')"
        ),
        "runs": "SELECT count(*) FROM runs",
        "run_tags": "SELECT count(*) FROM run_tags",
        "asset_event_tags": "SELECT count(*) FROM asset_event_tags",
        "dynamic_partitions": "SELECT count(*) FROM dynamic_partitions",
    }
    return {
        name: int(_psql_rows(query)[0][0])
        for name, query in queries.items()
    }


def _assert_control_counts_unchanged(
    *,
    before: Mapping[str, int],
    after: Mapping[str, int],
) -> None:
    changed = {
        key: {"before": before[key], "after": after.get(key)}
        for key in before
        if before[key] != after.get(key)
    }
    if changed:
        raise StockYearMaterializationReconciliationError(
            f"Unexpected non-materialization Dagster state change: {changed}."
        )


def _canonical_uri(asset_key: str) -> str:
    freq = asset_key.rsplit("_", maxsplit=1)[-1]
    if asset_key.startswith("gold_stk_mins_qfq_macd_kdj_"):
        return f"lake://gold/indicator/stk_mins_qfq_macd_kdj/freq={freq.removesuffix('m')}"
    if asset_key.startswith("gold_stk_mins_qfq_"):
        return f"lake://gold/quote/stk_mins_qfq/freq={freq.removesuffix('m')}"
    raise StockYearMaterializationReconciliationError(f"Unexpected target asset: {asset_key}.")


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise StockYearMaterializationReconciliationError(
            f"Partition key is not an ISO date: {value!r}."
        ) from error


def _date_summary(values: set[str], sample_size: int = 10) -> dict[str, object]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "first": ordered[0] if ordered else None,
        "last": ordered[-1] if ordered else None,
        "samples": ordered[:sample_size],
    }


def _candidate_sort_key(
    candidate: StockYearMaterializationCandidate,
) -> tuple[str, str]:
    return candidate.asset_key, candidate.partition_key


def _chunks(
    values: Sequence[StockYearMaterializationCandidate],
    size: int,
) -> Iterable[Sequence[StockYearMaterializationCandidate]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _hash_payload(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def _psql_rows(sql: str) -> list[tuple[str, ...]]:
    completed = subprocess.run(
        [
            "psql",
            "-d",
            "goldenshare_dagster",
            "-v",
            "ON_ERROR_STOP=1",
            "-qAt",
            "-F",
            "\t",
            "-c",
            f"BEGIN READ ONLY; {sql}; COMMIT;",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [tuple(line.split("\t")) for line in completed.stdout.splitlines() if line]
