"""Exact single-partition event reconciliation for stock trend-channel assets."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.event_api import PartitionKeyFilter

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    asset_check_record_evaluation,
    asset_check_record_event_storage_id,
    asset_check_record_metadata,
    asset_check_record_succeeded,
    latest_partition_check_records,
    metadata_int,
    metadata_str,
)
from orchestrator.defs.asset_guards.stock_daily_trend_channel_repair import (
    RESULT_REPAIR_COMPLETION_CHECK_NAME,
    STATE_REPAIR_COMPLETION_CHECK_NAME,
    gold_stock_daily_trend_channel_repair_completion_status,
)
from orchestrator.defs.checks.stock_daily_trend_channel_checks import (
    _load_previous_expected_trade_date,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.jobs.gold_stock_daily_qfq_factor_repair import (
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_JOB_NAME,
)
from orchestrator.defs.jobs.gold_stock_daily_trend_channel_repair import (
    GOLD_STOCK_DAILY_TREND_CHANNEL_REPAIR_JOB_NAME,
)
from orchestrator.defs.partitions import cn_a_stock_daily_trend_channel_trade_days
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_state_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash,
)
from orchestrator.defs.stock_daily_trend_channel import (
    DAILY_SOURCE_ROW_HARD_LIMIT,
    FORMULA_VERSION,
    StockDailyTrendChannelAudit,
    StockDailyTrendChannelCoverageAudit,
    audit_stock_daily_trend_channel_result,
    audit_stock_daily_trend_channel_state,
    audit_stock_daily_trend_channel_state_coverage,
)

RESULT_ASSET_KEY = "gold_stock_daily_trend_channel"
STATE_ASSET_KEY = "gold_stock_daily_trend_channel_state"
RESULT_CONTRACT_CHECK = "gold_stock_daily_trend_channel_contract_check"
STATE_CONTRACT_CHECK = "gold_stock_daily_trend_channel_state_contract_check"
INPUT_COVERAGE_CHECK = "gold_stock_daily_trend_channel_input_coverage_check"
INCIDENT_JOB_NAME = "gold_stock_daily_trend_channel_update_job"
PLAN_SCHEMA_VERSION = 1
MAX_MATERIALIZATION_WRITES = 2
MAX_CHECK_WRITES = 3
MAX_EVENT_WRITES = 5
MAX_TARGET_EVENT_RECORDS = 20
MAX_STAGE_SECONDS = 30.0
RECONCILIATION_SOURCE_METHOD = "stock_daily_trend_channel_event_reconciliation"
RECONCILIATION_REASON = (
    "missing_partition_events_after_daily_post_write_metadata_failure"
)
DEFAULT_REPORT_ROOT = Path("/private/tmp")
NEIGHBOR_PARTITION_DATES = ("2026-09-03", "2026-09-04")

_ACTIVE_RUN_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)
_ACTIVE_JOB_NAMES = (
    INCIDENT_JOB_NAME,
    GOLD_STOCK_DAILY_TREND_CHANNEL_REPAIR_JOB_NAME,
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_JOB_NAME,
)


class StockDailyTrendChannelEventReconciliationError(RuntimeError):
    """Raised before an event outside the reviewed reconciliation contract."""


@dataclass(frozen=True, slots=True)
class ReconciliationFileFact:
    role: str
    path: str
    size_bytes: int
    sha256: str
    row_count: int
    observed_columns: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "row_count": self.row_count,
            "observed_columns": list(self.observed_columns),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ReconciliationFileFact:
        return cls(
            role=_required_str(payload, "role"),
            path=_required_str(payload, "path"),
            size_bytes=_required_int(payload, "size_bytes"),
            sha256=_required_str(payload, "sha256"),
            row_count=_required_int(payload, "row_count"),
            observed_columns=_required_str_tuple(payload, "observed_columns"),
        )


@dataclass(frozen=True, slots=True)
class IncidentRunFact:
    run_id: str
    job_name: str
    status: str
    partition: str
    error_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "job_name": self.job_name,
            "status": self.status,
            "partition": self.partition,
            "error_fingerprint": self.error_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> IncidentRunFact:
        return cls(
            run_id=_required_str(payload, "run_id"),
            job_name=_required_str(payload, "job_name"),
            status=_required_str(payload, "status"),
            partition=_required_str(payload, "partition"),
            error_fingerprint=_required_str(payload, "error_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class ProducerRunFact:
    run_id: str
    job_name: str
    status: str
    qfq_factor_repair_trade_date: str
    repair_start_trade_date: str
    repair_end_trade_date: str
    selected_partition_count: int
    repair_required_code_count: int
    repair_required_codes_hash: str
    source_upstream_batch_id: str
    formula_version: str
    completion_event_storage_ids: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "job_name": self.job_name,
            "status": self.status,
            "qfq_factor_repair_trade_date": self.qfq_factor_repair_trade_date,
            "repair_start_trade_date": self.repair_start_trade_date,
            "repair_end_trade_date": self.repair_end_trade_date,
            "selected_partition_count": self.selected_partition_count,
            "repair_required_code_count": self.repair_required_code_count,
            "repair_required_codes_hash": self.repair_required_codes_hash,
            "source_upstream_batch_id": self.source_upstream_batch_id,
            "formula_version": self.formula_version,
            "completion_event_storage_ids": list(
                self.completion_event_storage_ids
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ProducerRunFact:
        event_ids = payload.get("completion_event_storage_ids")
        if not isinstance(event_ids, list) or not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in event_ids
        ):
            raise StockDailyTrendChannelEventReconciliationError(
                "completion_event_storage_ids must be an integer list"
            )
        return cls(
            run_id=_required_str(payload, "run_id"),
            job_name=_required_str(payload, "job_name"),
            status=_required_str(payload, "status"),
            qfq_factor_repair_trade_date=_required_str(
                payload, "qfq_factor_repair_trade_date"
            ),
            repair_start_trade_date=_required_str(
                payload, "repair_start_trade_date"
            ),
            repair_end_trade_date=_required_str(payload, "repair_end_trade_date"),
            selected_partition_count=_required_int(
                payload, "selected_partition_count"
            ),
            repair_required_code_count=_required_int(
                payload, "repair_required_code_count"
            ),
            repair_required_codes_hash=_required_str(
                payload, "repair_required_codes_hash"
            ),
            source_upstream_batch_id=_required_str(
                payload, "source_upstream_batch_id"
            ),
            formula_version=_required_str(payload, "formula_version"),
            completion_event_storage_ids=tuple(event_ids),
        )


@dataclass(frozen=True, slots=True)
class ReconciliationAuditFact:
    name: str
    passed: bool
    checked_row_count: int
    failed_row_count: int
    failure_rule_counts: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "checked_row_count": self.checked_row_count,
            "failed_row_count": self.failed_row_count,
            "failure_rule_counts": dict(self.failure_rule_counts),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ReconciliationAuditFact:
        raw_counts = payload.get("failure_rule_counts")
        if not isinstance(raw_counts, Mapping):
            raise StockDailyTrendChannelEventReconciliationError(
                "failure_rule_counts must be an object"
            )
        counts: list[tuple[str, int]] = []
        for key, value in raw_counts.items():
            if not isinstance(value, int) or isinstance(value, bool):
                raise StockDailyTrendChannelEventReconciliationError(
                    "failure_rule_counts values must be integers"
                )
            counts.append((str(key), value))
        passed = payload.get("passed")
        if not isinstance(passed, bool):
            raise StockDailyTrendChannelEventReconciliationError(
                "audit passed must be a boolean"
            )
        return cls(
            name=_required_str(payload, "name"),
            passed=passed,
            checked_row_count=_required_int(payload, "checked_row_count"),
            failed_row_count=_required_int(payload, "failed_row_count"),
            failure_rule_counts=tuple(sorted(counts)),
        )


@dataclass(frozen=True, slots=True)
class ExistingEventFact:
    event_key: str
    storage_id: int
    status: str
    passed: bool | None = None
    target_storage_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event_key": self.event_key,
            "storage_id": self.storage_id,
            "status": self.status,
            "passed": self.passed,
            "target_storage_id": self.target_storage_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ExistingEventFact:
        passed = payload.get("passed")
        target = payload.get("target_storage_id")
        if passed is not None and not isinstance(passed, bool):
            raise StockDailyTrendChannelEventReconciliationError(
                "event passed must be boolean or null"
            )
        if target is not None and (
            not isinstance(target, int) or isinstance(target, bool)
        ):
            raise StockDailyTrendChannelEventReconciliationError(
                "target_storage_id must be integer or null"
            )
        return cls(
            event_key=_required_str(payload, "event_key"),
            storage_id=_required_int(payload, "storage_id"),
            status=_required_str(payload, "status"),
            passed=passed,
            target_storage_id=target,
        )


@dataclass(frozen=True, slots=True)
class NeighborEventFact:
    event_key: str
    storage_id: int

    def to_dict(self) -> dict[str, object]:
        return {"event_key": self.event_key, "storage_id": self.storage_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> NeighborEventFact:
        return cls(
            event_key=_required_str(payload, "event_key"),
            storage_id=_required_int(payload, "storage_id"),
        )


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelEventReconciliationPlan:
    plan_id: str
    plan_hash: str
    generated_at: str
    partition_date: str
    formula_version: str
    lake_root: str
    incident_run: IncidentRunFact
    current_file_producer_run: ProducerRunFact
    result_file: ReconciliationFileFact
    state_file: ReconciliationFileFact
    input_files: tuple[ReconciliationFileFact, ...]
    audits: tuple[ReconciliationAuditFact, ...]
    registered_partition: bool
    existing_materializations: tuple[ExistingEventFact, ...]
    existing_check_executions: tuple[ExistingEventFact, ...]
    neighbor_event_guard: tuple[NeighborEventFact, ...]
    expected_materialization_writes: int
    expected_check_writes: int
    maximum_event_writes: int
    active_run_count: int
    blockers: tuple[str, ...]
    should_stop: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "generated_at": self.generated_at,
            "partition_date": self.partition_date,
            "formula_version": self.formula_version,
            "lake_root": self.lake_root,
            "incident_run": self.incident_run.to_dict(),
            "current_file_producer_run": self.current_file_producer_run.to_dict(),
            "result_file": self.result_file.to_dict(),
            "state_file": self.state_file.to_dict(),
            "inputs": [value.to_dict() for value in self.input_files],
            "audits": [value.to_dict() for value in self.audits],
            "registered_partition": self.registered_partition,
            "existing_materializations": [
                value.to_dict() for value in self.existing_materializations
            ],
            "existing_check_executions": [
                value.to_dict() for value in self.existing_check_executions
            ],
            "neighbor_event_guard": [
                value.to_dict() for value in self.neighbor_event_guard
            ],
            "expected_materialization_writes": (
                self.expected_materialization_writes
            ),
            "expected_check_writes": self.expected_check_writes,
            "maximum_event_writes": self.maximum_event_writes,
            "active_run_count": self.active_run_count,
            "blockers": list(self.blockers),
            "should_stop": self.should_stop,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> StockDailyTrendChannelEventReconciliationPlan:
        if payload.get("schema_version") != PLAN_SCHEMA_VERSION:
            raise StockDailyTrendChannelEventReconciliationError(
                "unsupported reconciliation plan schema"
            )
        return cls(
            plan_id=_required_str(payload, "plan_id"),
            plan_hash=_required_str(payload, "plan_hash"),
            generated_at=_required_str(payload, "generated_at"),
            partition_date=_required_str(payload, "partition_date"),
            formula_version=_required_str(payload, "formula_version"),
            lake_root=_required_str(payload, "lake_root"),
            incident_run=IncidentRunFact.from_dict(
                _required_mapping(payload, "incident_run")
            ),
            current_file_producer_run=ProducerRunFact.from_dict(
                _required_mapping(payload, "current_file_producer_run")
            ),
            result_file=ReconciliationFileFact.from_dict(
                _required_mapping(payload, "result_file")
            ),
            state_file=ReconciliationFileFact.from_dict(
                _required_mapping(payload, "state_file")
            ),
            input_files=tuple(
                ReconciliationFileFact.from_dict(value)
                for value in _required_mapping_list(payload, "inputs")
            ),
            audits=tuple(
                ReconciliationAuditFact.from_dict(value)
                for value in _required_mapping_list(payload, "audits")
            ),
            registered_partition=_required_bool(payload, "registered_partition"),
            existing_materializations=tuple(
                ExistingEventFact.from_dict(value)
                for value in _required_mapping_list(
                    payload, "existing_materializations"
                )
            ),
            existing_check_executions=tuple(
                ExistingEventFact.from_dict(value)
                for value in _required_mapping_list(
                    payload, "existing_check_executions"
                )
            ),
            neighbor_event_guard=tuple(
                NeighborEventFact.from_dict(value)
                for value in _required_mapping_list(payload, "neighbor_event_guard")
            ),
            expected_materialization_writes=_required_int(
                payload, "expected_materialization_writes"
            ),
            expected_check_writes=_required_int(payload, "expected_check_writes"),
            maximum_event_writes=_required_int(payload, "maximum_event_writes"),
            active_run_count=_required_int(payload, "active_run_count"),
            blockers=_required_str_tuple(payload, "blockers"),
            should_stop=_required_bool(payload, "should_stop"),
        )


@dataclass(frozen=True, slots=True)
class _PhysicalSnapshot:
    result_file: ReconciliationFileFact
    state_file: ReconciliationFileFact
    input_files: tuple[ReconciliationFileFact, ...]
    result_audit: StockDailyTrendChannelAudit
    state_audit: StockDailyTrendChannelAudit
    coverage_audit: StockDailyTrendChannelCoverageAudit

    @property
    def audit_facts(self) -> tuple[ReconciliationAuditFact, ...]:
        return (
            _ordinary_audit_fact("result_contract", self.result_audit),
            _ordinary_audit_fact("state_contract", self.state_audit),
            _coverage_audit_fact(self.coverage_audit),
        )


@dataclass(frozen=True, slots=True)
class _CheckSpec:
    asset_key: str
    check_name: str
    target_file_role: str

    @property
    def event_key(self) -> str:
        return f"{self.asset_key}|{self.check_name}"


def build_stock_daily_trend_channel_event_reconciliation_plan(
    *,
    instance: Any,
    partition_date: str,
    incident_run_id: str,
    current_file_producer_run_id: str,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    generated_at: datetime | None = None,
) -> StockDailyTrendChannelEventReconciliationPlan:
    """Build a zero-write plan for one already-registered partition."""

    started_at = time.perf_counter()
    normalized_date = _normalize_date(partition_date)
    root = lake_root.root().resolve()
    incident = _incident_run_fact(
        instance, run_id=incident_run_id, partition_date=normalized_date
    )
    producer = _producer_run_fact(
        instance,
        run_id=current_file_producer_run_id,
        partition_date=normalized_date,
    )
    physical = _physical_snapshot(
        root=root,
        partition_date=normalized_date,
        duckdb=duckdb,
    )
    if not all(value.passed for value in physical.audit_facts):
        raise StockDailyTrendChannelEventReconciliationError(
            "one or more stock trend-channel audits failed"
        )

    registered = normalized_date in {
        str(value)
        for value in instance.get_dynamic_partitions(
            cn_a_stock_daily_trend_channel_trade_days.name
        )
    }
    existing_materializations, materialization_records = (
        _target_materialization_facts(instance, normalized_date)
    )
    existing_checks, check_records = _target_check_facts(instance, normalized_date)
    neighbor_guard, neighbor_blockers = _neighbor_event_guard(instance)
    active_run_ids = _active_run_ids(instance)
    blockers = list(neighbor_blockers)
    if not registered:
        blockers.append("target partition is not registered")
    if materialization_records:
        blockers.append("target has an existing materialization outside this plan")
    if any(_check_record_passed(value) for value in check_records):
        blockers.append("target has an existing successful check outside this plan")
    if active_run_ids:
        blockers.append(
            "active source-changing runs: " + ",".join(sorted(active_run_ids))
        )

    draft = StockDailyTrendChannelEventReconciliationPlan(
        plan_id="",
        plan_hash="",
        generated_at=(generated_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
        partition_date=normalized_date,
        formula_version=FORMULA_VERSION,
        lake_root=str(root),
        incident_run=incident,
        current_file_producer_run=producer,
        result_file=physical.result_file,
        state_file=physical.state_file,
        input_files=physical.input_files,
        audits=physical.audit_facts,
        registered_partition=registered,
        existing_materializations=existing_materializations,
        existing_check_executions=existing_checks,
        neighbor_event_guard=neighbor_guard,
        expected_materialization_writes=MAX_MATERIALIZATION_WRITES,
        expected_check_writes=MAX_CHECK_WRITES,
        maximum_event_writes=MAX_EVENT_WRITES,
        active_run_count=len(active_run_ids),
        blockers=tuple(sorted(set(blockers))),
        should_stop=bool(blockers),
    )
    plan_hash = _plan_hash(draft.to_dict())
    plan = replace(
        draft,
        plan_hash=plan_hash,
        plan_id=(
            f"stock-trend-event-reconciliation-{normalized_date}-"
            f"{plan_hash[:12]}"
        ),
    )
    _assert_plan_bounds(plan)
    _assert_stage_budget(started_at)
    return plan


def load_stock_daily_trend_channel_event_reconciliation_plan(
    path: Path,
    *,
    expected_plan_id: str,
    expected_plan_hash: str,
    report_root: Path = DEFAULT_REPORT_ROOT,
) -> StockDailyTrendChannelEventReconciliationPlan:
    """Load and re-hash one frozen plan report."""

    normalized = _validated_report_path(path, report_root=report_root)
    payload = _load_json(normalized)
    plan = StockDailyTrendChannelEventReconciliationPlan.from_dict(payload)
    calculated_hash = _plan_hash(plan.to_dict())
    if (
        plan.plan_id != expected_plan_id
        or plan.plan_hash != expected_plan_hash
        or calculated_hash != expected_plan_hash
    ):
        raise StockDailyTrendChannelEventReconciliationError(
            "reconciliation plan identity does not match"
        )
    expected_id = (
        f"stock-trend-event-reconciliation-{plan.partition_date}-"
        f"{plan.plan_hash[:12]}"
    )
    if plan.plan_id != expected_id:
        raise StockDailyTrendChannelEventReconciliationError(
            "reconciliation plan id is not derived from its hash"
        )
    _assert_plan_bounds(plan)
    return plan


def apply_stock_daily_trend_channel_materialization_reconciliation(
    *,
    instance: Any,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    confirm_event_write: bool = False,
) -> dict[str, object]:
    """Append at most two exact materializations, state before result."""

    if not confirm_event_write:
        raise StockDailyTrendChannelEventReconciliationError(
            "materialization apply requires confirm_event_write=True"
        )
    started_at = time.perf_counter()
    physical = _revalidate_plan(
        instance=instance,
        plan=plan,
        lake_root=lake_root,
        duckdb=duckdb,
    )
    before, blockers = _matching_materializations(instance, plan)
    if blockers:
        raise StockDailyTrendChannelEventReconciliationError("; ".join(blockers))
    attempted: list[str] = []
    skipped: list[str] = []
    written: list[dict[str, object]] = []
    files = {
        STATE_ASSET_KEY: physical.state_file,
        RESULT_ASSET_KEY: physical.result_file,
    }
    for asset_key in (STATE_ASSET_KEY, RESULT_ASSET_KEY):
        event_key = f"{asset_key}|{plan.partition_date}"
        if asset_key in before:
            skipped.append(event_key)
            continue
        attempted.append(event_key)
        _assert_pre_event_gates(instance, plan, files[asset_key])
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=dg.AssetKey(asset_key),
                partition=plan.partition_date,
                metadata=_materialization_metadata(
                    plan=plan,
                    physical=physical,
                    file=files[asset_key],
                ),
            )
        )
        current, current_blockers = _matching_materializations(instance, plan)
        if current_blockers or asset_key not in current:
            raise StockDailyTrendChannelEventReconciliationError(
                "new materialization could not be verified"
            )
        record = current[asset_key]
        written.append(
            {"event_key": event_key, "storage_id": int(record.storage_id)}
        )
        before = current
        if len(written) > MAX_MATERIALIZATION_WRITES:
            raise StockDailyTrendChannelEventReconciliationError(
                "materialization event bound exceeded"
            )
        _assert_stage_budget(started_at)

    after, after_blockers = _matching_materializations(instance, plan)
    if after_blockers:
        raise StockDailyTrendChannelEventReconciliationError(
            "; ".join(after_blockers)
        )
    return _stage_report(
        stage="apply-materializations",
        plan=plan,
        attempted=attempted,
        skipped=skipped,
        written=written,
        before_count=len(after) - len(written),
        after_count=len(after),
        started_at=started_at,
    )


def audit_stock_daily_trend_channel_materialization_reconciliation(
    *,
    instance: Any,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dict[str, object]:
    """Require both latest materializations to match the frozen plan."""

    started_at = time.perf_counter()
    _revalidate_plan(
        instance=instance,
        plan=plan,
        lake_root=lake_root,
        duckdb=duckdb,
    )
    matches, blockers = _matching_materializations(instance, plan)
    if blockers or set(matches) != {RESULT_ASSET_KEY, STATE_ASSET_KEY}:
        raise StockDailyTrendChannelEventReconciliationError(
            "; ".join(blockers or ("materialization reconciliation is incomplete",))
        )
    storage_ids = {
        asset_key: int(record.storage_id)
        for asset_key, record in sorted(matches.items())
    }
    _assert_stage_budget(started_at)
    return {
        "schema_version": 1,
        "stage": "audit-materializations",
        "status": "passed",
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "partition_date": plan.partition_date,
        "materialization_storage_ids": storage_ids,
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
    }


def apply_stock_daily_trend_channel_check_reconciliation(
    *,
    instance: Any,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    confirm_event_write: bool = False,
) -> dict[str, object]:
    """Append at most three successful, materialization-bound evaluations."""

    if not confirm_event_write:
        raise StockDailyTrendChannelEventReconciliationError(
            "check apply requires confirm_event_write=True"
        )
    started_at = time.perf_counter()
    physical = _revalidate_plan(
        instance=instance,
        plan=plan,
        lake_root=lake_root,
        duckdb=duckdb,
    )
    materializations, materialization_blockers = _matching_materializations(
        instance, plan
    )
    if materialization_blockers or set(materializations) != {
        RESULT_ASSET_KEY,
        STATE_ASSET_KEY,
    }:
        raise StockDailyTrendChannelEventReconciliationError(
            "both reconciled materializations are required before checks"
        )
    before, blockers = _matching_checks(instance, plan, materializations)
    if blockers:
        raise StockDailyTrendChannelEventReconciliationError("; ".join(blockers))

    attempted: list[str] = []
    skipped: list[str] = []
    written: list[dict[str, object]] = []
    for spec in _check_specs():
        event_key = f"{spec.event_key}|{plan.partition_date}"
        if spec.check_name in before:
            skipped.append(event_key)
            continue
        attempted.append(event_key)
        target_record = materializations[spec.asset_key]
        target_file = (
            physical.state_file
            if spec.target_file_role == "state"
            else physical.result_file
        )
        _assert_pre_event_gates(instance, plan, target_file)
        metadata = _check_metadata(
            spec=spec,
            plan=plan,
            physical=physical,
        )
        target = AssetCheckEvaluationTargetMaterializationData(
            storage_id=int(target_record.storage_id),
            run_id=str(target_record.run_id),
            timestamp=float(target_record.timestamp),
        )
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(spec.asset_key),
                check_name=spec.check_name,
                passed=True,
                blocking=True,
                partition=plan.partition_date,
                target_materialization_data=target,
                metadata=metadata,
            )
        )
        current, current_blockers = _matching_checks(
            instance, plan, materializations
        )
        if current_blockers or spec.check_name not in current:
            raise StockDailyTrendChannelEventReconciliationError(
                "new check evaluation could not be verified"
            )
        record = current[spec.check_name]
        written.append(
            {"event_key": event_key, "storage_id": int(record.id)}
        )
        before = current
        if len(written) > MAX_CHECK_WRITES:
            raise StockDailyTrendChannelEventReconciliationError(
                "check event bound exceeded"
            )
        _assert_stage_budget(started_at)

    after, after_blockers = _matching_checks(instance, plan, materializations)
    if after_blockers:
        raise StockDailyTrendChannelEventReconciliationError(
            "; ".join(after_blockers)
        )
    return _stage_report(
        stage="apply-checks",
        plan=plan,
        attempted=attempted,
        skipped=skipped,
        written=written,
        before_count=len(after) - len(written),
        after_count=len(after),
        started_at=started_at,
    )


def audit_stock_daily_trend_channel_event_reconciliation(
    *,
    instance: Any,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dict[str, object]:
    """Require all five exact events and unchanged neighboring event heads."""

    started_at = time.perf_counter()
    _revalidate_plan(
        instance=instance,
        plan=plan,
        lake_root=lake_root,
        duckdb=duckdb,
    )
    materializations, materialization_blockers = _matching_materializations(
        instance, plan
    )
    if materialization_blockers or set(materializations) != {
        RESULT_ASSET_KEY,
        STATE_ASSET_KEY,
    }:
        raise StockDailyTrendChannelEventReconciliationError(
            "final audit found incomplete materializations"
        )
    checks, check_blockers = _matching_checks(instance, plan, materializations)
    expected_checks = {value.check_name for value in _check_specs()}
    if check_blockers or set(checks) != expected_checks:
        raise StockDailyTrendChannelEventReconciliationError(
            "final audit found incomplete or conflicting checks"
        )
    for spec in _check_specs():
        records = _check_records(
            instance,
            asset_key=spec.asset_key,
            check_name=spec.check_name,
            partition_date=plan.partition_date,
        )
        if not records or int(records[0].id) != int(checks[spec.check_name].id):
            raise StockDailyTrendChannelEventReconciliationError(
                f"latest check is not the reconciled success: {spec.check_name}"
            )
    _assert_stage_budget(started_at)
    return {
        "schema_version": 1,
        "stage": "final-audit",
        "status": "passed",
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "partition_date": plan.partition_date,
        "materialization_storage_ids": {
            key: int(value.storage_id)
            for key, value in sorted(materializations.items())
        },
        "check_storage_ids": {
            key: int(value.id) for key, value in sorted(checks.items())
        },
        "event_count": MAX_EVENT_WRITES,
        "neighbor_event_guard": [
            value.to_dict() for value in plan.neighbor_event_guard
        ],
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
    }


def write_stock_daily_trend_channel_event_reconciliation_report(
    report: StockDailyTrendChannelEventReconciliationPlan | Mapping[str, object],
    output_path: Path,
    *,
    report_root: Path = DEFAULT_REPORT_ROOT,
) -> Path:
    """Atomically write a review report outside the formal Lake."""

    normalized = _validated_report_path(output_path, report_root=report_root)
    payload = report.to_dict() if isinstance(report, StockDailyTrendChannelEventReconciliationPlan) else dict(report)
    normalized.parent.mkdir(parents=True, exist_ok=True)
    pending = normalized.with_name(f".{normalized.name}.pending-{uuid.uuid4().hex}")
    pending.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(pending, normalized)
    return normalized


def _revalidate_plan(
    *,
    instance: Any,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> _PhysicalSnapshot:
    _assert_plan_bounds(plan)
    if plan.should_stop:
        raise StockDailyTrendChannelEventReconciliationError(
            "frozen plan is blocked: " + "; ".join(plan.blockers)
        )
    root = lake_root.root().resolve()
    if str(root) != plan.lake_root:
        raise StockDailyTrendChannelEventReconciliationError(
            "Lake root differs from the frozen plan"
        )
    if plan.partition_date not in {
        str(value)
        for value in instance.get_dynamic_partitions(
            cn_a_stock_daily_trend_channel_trade_days.name
        )
    }:
        raise StockDailyTrendChannelEventReconciliationError(
            "target partition is no longer registered"
        )
    incident = _incident_run_fact(
        instance,
        run_id=plan.incident_run.run_id,
        partition_date=plan.partition_date,
    )
    producer = _producer_run_fact(
        instance,
        run_id=plan.current_file_producer_run.run_id,
        partition_date=plan.partition_date,
    )
    if incident != plan.incident_run or producer != plan.current_file_producer_run:
        raise StockDailyTrendChannelEventReconciliationError(
            "run provenance differs from the frozen plan"
        )
    active = _active_run_ids(instance)
    if active:
        raise StockDailyTrendChannelEventReconciliationError(
            "active source-changing runs: " + ",".join(active)
        )
    _assert_all_file_fingerprints(plan)
    physical = _physical_snapshot(
        root=root,
        partition_date=plan.partition_date,
        duckdb=duckdb,
    )
    if (
        physical.result_file != plan.result_file
        or physical.state_file != plan.state_file
        or physical.input_files != plan.input_files
        or physical.audit_facts != plan.audits
        or not all(value.passed for value in physical.audit_facts)
    ):
        raise StockDailyTrendChannelEventReconciliationError(
            "physical files or audit results differ from the frozen plan"
        )
    neighbor_guard, neighbor_blockers = _neighbor_event_guard(instance)
    if neighbor_blockers or neighbor_guard != plan.neighbor_event_guard:
        raise StockDailyTrendChannelEventReconciliationError(
            "neighbor event guard changed after plan"
        )
    materializations, materialization_blockers = _matching_materializations(
        instance, plan
    )
    if materialization_blockers:
        raise StockDailyTrendChannelEventReconciliationError(
            "; ".join(materialization_blockers)
        )
    _, check_blockers = _matching_checks(instance, plan, materializations)
    if check_blockers:
        raise StockDailyTrendChannelEventReconciliationError(
            "; ".join(check_blockers)
        )
    return physical


def _incident_run_fact(
    instance: Any, *, run_id: str, partition_date: str
) -> IncidentRunFact:
    run = instance.get_run_by_id(run_id)
    if run is None:
        raise StockDailyTrendChannelEventReconciliationError(
            f"incident run does not exist: {run_id}"
        )
    partition = str(run.tags.get("dagster/partition") or "")
    if (
        run.job_name != INCIDENT_JOB_NAME
        or run.status != dg.DagsterRunStatus.FAILURE
        or partition != partition_date
    ):
        raise StockDailyTrendChannelEventReconciliationError(
            "incident run identity does not match the target failure"
        )
    failure_logs = instance.get_records_for_run(
        run_id,
        of_type=dg.DagsterEventType.RUN_FAILURE,
        limit=10,
    )
    if failure_logs.has_more:
        raise StockDailyTrendChannelEventReconciliationError(
            "incident run failure history exceeds the bounded audit limit"
        )
    error_text = " ".join(
        value
        for record in failure_logs.records
        for entry in (record.event_log_entry,)
        for value in _event_log_text_values(entry)
        if value
    )
    normalized_error = " ".join(error_text.split())
    lowered = normalized_error.lower()
    if "stock_basic_path" not in lowered or "metadata" not in lowered:
        raise StockDailyTrendChannelEventReconciliationError(
            "incident run does not contain the expected metadata error fingerprint"
        )
    return IncidentRunFact(
        run_id=run_id,
        job_name=run.job_name,
        status=run.status.value,
        partition=partition,
        error_fingerprint=hashlib.sha256(
            normalized_error.encode("utf-8")
        ).hexdigest(),
    )


def _producer_run_fact(
    instance: Any, *, run_id: str, partition_date: str
) -> ProducerRunFact:
    run = instance.get_run_by_id(run_id)
    if run is None:
        raise StockDailyTrendChannelEventReconciliationError(
            f"current file producer run does not exist: {run_id}"
        )
    if (
        run.job_name != GOLD_STOCK_DAILY_TREND_CHANNEL_REPAIR_JOB_NAME
        or run.status != dg.DagsterRunStatus.SUCCESS
    ):
        raise StockDailyTrendChannelEventReconciliationError(
            "current file producer is not the successful trend repair job"
        )
    config = _repair_run_config(run.run_config)
    qfq_date = _required_str(config, "qfq_factor_repair_trade_date")
    repair_start = _normalize_date(_required_str(config, "repair_start_trade_date"))
    repair_end = _normalize_date(_required_str(config, "repair_end_trade_date"))
    if not repair_start <= partition_date <= repair_end:
        raise StockDailyTrendChannelEventReconciliationError(
            "current file producer repair scope does not include the target"
        )
    raw_codes = config.get("stock_codes")
    if not isinstance(raw_codes, list) or not raw_codes or not all(
        isinstance(value, str) and value.strip() for value in raw_codes
    ):
        raise StockDailyTrendChannelEventReconciliationError(
            "repair stock_codes must be a non-empty string list"
        )
    codes = tuple(str(value).strip().upper() for value in raw_codes)
    codes_hash = _required_str(config, "repair_required_codes_hash")
    if gold_stock_daily_qfq_factor_repair_codes_hash(codes) != codes_hash:
        raise StockDailyTrendChannelEventReconciliationError(
            "repair stock code hash does not match config"
        )
    upstream_batch = _required_str(config, "source_upstream_batch_id")
    completion_records = _repair_completion_records(instance, qfq_date)
    metadata_rows = tuple(
        asset_check_record_metadata(asset_check_record_evaluation(record))
        for record in completion_records
    )
    selected_counts = {metadata_int(row, "selected_partition_count") for row in metadata_rows}
    if len(selected_counts) != 1 or None in selected_counts:
        raise StockDailyTrendChannelEventReconciliationError(
            "repair completion selected partition count is inconsistent"
        )
    selected_count = int(next(iter(selected_counts)))
    status = gold_stock_daily_trend_channel_repair_completion_status(
        instance,
        qfq_factor_repair_trade_date=qfq_date,
        repair_start_trade_date=repair_start,
        repair_end_trade_date=repair_end,
        selected_partition_count=selected_count,
        repair_required_code_count=len(codes),
        repair_required_codes_hash=codes_hash,
        source_upstream_batch_id=upstream_batch,
        formula_version=FORMULA_VERSION,
    )
    if not status.ready:
        raise StockDailyTrendChannelEventReconciliationError(
            "repair completion checks are not exact and green: " + status.reason
        )
    if any(metadata_str(row, "producer_run_id") != run_id for row in metadata_rows):
        raise StockDailyTrendChannelEventReconciliationError(
            "repair completion producer_run_id does not match the current file producer"
        )
    if any(metadata_str(row, "formula_version") != FORMULA_VERSION for row in metadata_rows):
        raise StockDailyTrendChannelEventReconciliationError(
            "repair completion formula version does not match"
        )
    return ProducerRunFact(
        run_id=run_id,
        job_name=run.job_name,
        status=run.status.value,
        qfq_factor_repair_trade_date=qfq_date,
        repair_start_trade_date=repair_start,
        repair_end_trade_date=repair_end,
        selected_partition_count=selected_count,
        repair_required_code_count=len(codes),
        repair_required_codes_hash=codes_hash,
        source_upstream_batch_id=upstream_batch,
        formula_version=FORMULA_VERSION,
        completion_event_storage_ids=tuple(sorted(status.event_storage_ids)),
    )


def _repair_completion_records(instance: Any, partition_date: str) -> tuple[object, ...]:
    specs = (
        (dg.AssetKey(RESULT_ASSET_KEY), RESULT_REPAIR_COMPLETION_CHECK_NAME),
        (dg.AssetKey(STATE_ASSET_KEY), STATE_REPAIR_COMPLETION_CHECK_NAME),
    )
    records: list[object] = []
    for asset_key, check_name in specs:
        key = dg.AssetCheckKey(asset_key, check_name)
        record = latest_partition_check_records(
            instance,
            (asset_key,),
            check_name,
            partition_key=partition_date,
        ).get(key)
        if record is None or not asset_check_record_succeeded(record):
            raise StockDailyTrendChannelEventReconciliationError(
                "repair completion check is missing or not successful"
            )
        storage_id = asset_check_record_event_storage_id(
            instance, key, record, partition_key=partition_date
        )
        if storage_id is None:
            raise StockDailyTrendChannelEventReconciliationError(
                "repair completion check storage id is unavailable"
            )
        records.append(record)
    return tuple(records)


def _repair_run_config(run_config: object) -> Mapping[str, object]:
    if not isinstance(run_config, Mapping):
        raise StockDailyTrendChannelEventReconciliationError(
            "repair run config is missing"
        )
    ops = run_config.get("ops")
    if not isinstance(ops, Mapping):
        raise StockDailyTrendChannelEventReconciliationError(
            "repair run ops config is missing"
        )
    op = ops.get("gold_stock_daily_trend_channel_repair_op")
    if not isinstance(op, Mapping) or not isinstance(op.get("config"), Mapping):
        raise StockDailyTrendChannelEventReconciliationError(
            "trend repair op config is missing"
        )
    return op["config"]


def _physical_snapshot(
    *, root: Path, partition_date: str, duckdb: DuckDBResource
) -> _PhysicalSnapshot:
    result_path = gold_stock_daily_trend_channel_path(root, partition_date)
    state_path = gold_stock_daily_trend_channel_state_path(root, partition_date)
    qfq_path = gold_stock_daily_qfq_path(root, partition_date)
    lifecycle_path = silver_stock_lifecycle_path(root)
    calendar_path = silver_trade_calendar_path(root)
    for path in (result_path, state_path, qfq_path, lifecycle_path, calendar_path):
        _assert_path_in_root(path, root=root)
        if not path.is_file():
            raise StockDailyTrendChannelEventReconciliationError(
                f"required reconciliation file is missing: {path}"
            )
    with duckdb.connect() as connection:
        previous_date = _load_previous_expected_trade_date(
            connection=connection,
            calendar_path=calendar_path,
            trade_date=partition_date,
        )
        if previous_date is None:
            raise StockDailyTrendChannelEventReconciliationError(
                "target reconciliation partition must have a previous SSE trade date"
            )
        previous_state_path = gold_stock_daily_trend_channel_state_path(
            root, previous_date
        )
        _assert_path_in_root(previous_state_path, root=root)
        if not previous_state_path.is_file():
            raise StockDailyTrendChannelEventReconciliationError(
                f"previous state file is missing: {previous_state_path}"
            )
        result_audit = audit_stock_daily_trend_channel_result(
            connection=connection,
            result_path=result_path,
            qfq_source_path=qfq_path,
            trade_date=partition_date,
        )
        state_audit = audit_stock_daily_trend_channel_state(
            connection=connection,
            state_path=state_path,
            stock_lifecycle_path=lifecycle_path,
            trade_date=partition_date,
        )
        coverage_audit = audit_stock_daily_trend_channel_state_coverage(
            connection=connection,
            state_path=state_path,
            qfq_source_path=qfq_path,
            stock_lifecycle_path=lifecycle_path,
            previous_state_path=previous_state_path,
            trade_date=partition_date,
        )
        files = tuple(
            _file_fact(connection, role=role, path=path)
            for role, path in (
                ("result", result_path),
                ("state", state_path),
                ("qfq", qfq_path),
                ("previous_state", previous_state_path),
                ("lifecycle", lifecycle_path),
                ("calendar", calendar_path),
            )
        )
    by_role = {value.role: value for value in files}
    for role in ("result", "state", "qfq", "previous_state", "lifecycle"):
        if by_role[role].row_count > DAILY_SOURCE_ROW_HARD_LIMIT:
            raise StockDailyTrendChannelEventReconciliationError(
                f"{role} row count exceeds the daily reconciliation bound"
            )
    return _PhysicalSnapshot(
        result_file=by_role["result"],
        state_file=by_role["state"],
        input_files=tuple(
            by_role[role]
            for role in ("qfq", "previous_state", "lifecycle", "calendar")
        ),
        result_audit=result_audit,
        state_audit=state_audit,
        coverage_audit=coverage_audit,
    )


def _file_fact(connection: Any, *, role: str, path: Path) -> ReconciliationFileFact:
    relation = read_parquet(path, hive_partitioning=False)
    row_count = int(connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0])
    observed_columns = tuple(
        str(row[0]) for row in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    )
    return ReconciliationFileFact(
        role=role,
        path=str(path.resolve()),
        size_bytes=path.stat().st_size,
        sha256=_file_sha256(path),
        row_count=row_count,
        observed_columns=observed_columns,
    )


def _ordinary_audit_fact(
    name: str, audit: StockDailyTrendChannelAudit
) -> ReconciliationAuditFact:
    return ReconciliationAuditFact(
        name=name,
        passed=audit.passed,
        checked_row_count=audit.checked_row_count,
        failed_row_count=audit.failed_row_count,
        failure_rule_counts=tuple(sorted(audit.failure_rule_counts.items())),
    )


def _coverage_audit_fact(
    audit: StockDailyTrendChannelCoverageAudit,
) -> ReconciliationAuditFact:
    return ReconciliationAuditFact(
        name="input_coverage",
        passed=audit.passed,
        checked_row_count=audit.checked_row_count,
        failed_row_count=audit.failed_row_count,
        failure_rule_counts=tuple(sorted(audit.failure_rule_counts.items())),
    )


def _target_materialization_facts(
    instance: Any, partition_date: str
) -> tuple[tuple[ExistingEventFact, ...], tuple[object, ...]]:
    records = tuple(
        record
        for asset_key in (STATE_ASSET_KEY, RESULT_ASSET_KEY)
        for record in _materialization_records(
            instance, asset_key=asset_key, partition_date=partition_date
        )
    )
    facts = tuple(
        ExistingEventFact(
            event_key=f"{record.asset_key.to_user_string()}|{partition_date}",
            storage_id=int(record.storage_id),
            status="MATERIALIZED",
        )
        for record in records
    )
    return facts, records


def _target_check_facts(
    instance: Any, partition_date: str
) -> tuple[tuple[ExistingEventFact, ...], tuple[object, ...]]:
    records = tuple(
        record
        for spec in _check_specs()
        for record in _check_records(
            instance,
            asset_key=spec.asset_key,
            check_name=spec.check_name,
            partition_date=partition_date,
        )
    )
    facts: list[ExistingEventFact] = []
    for record in records:
        evaluation = _check_evaluation(record)
        target = getattr(evaluation, "target_materialization_data", None)
        facts.append(
            ExistingEventFact(
                event_key=(
                    f"{record.key.asset_key.to_user_string()}|{record.key.name}|"
                    f"{partition_date}"
                ),
                storage_id=int(record.id),
                status=_status_value(record.status),
                passed=getattr(evaluation, "passed", None),
                target_storage_id=(
                    int(target.storage_id) if target is not None else None
                ),
            )
        )
    return tuple(facts), records


def _neighbor_event_guard(
    instance: Any,
) -> tuple[tuple[NeighborEventFact, ...], tuple[str, ...]]:
    facts: list[NeighborEventFact] = []
    blockers: list[str] = []
    for partition_date in NEIGHBOR_PARTITION_DATES:
        materializations: dict[str, object] = {}
        for asset_key in (STATE_ASSET_KEY, RESULT_ASSET_KEY):
            records = _materialization_records(
                instance, asset_key=asset_key, partition_date=partition_date
            )
            if not records:
                blockers.append(f"neighbor materialization missing: {asset_key}:{partition_date}")
                continue
            record = records[0]
            materializations[asset_key] = record
            facts.append(
                NeighborEventFact(
                    event_key=f"{asset_key}|{partition_date}",
                    storage_id=int(record.storage_id),
                )
            )
        for spec in _check_specs():
            records = _check_records(
                instance,
                asset_key=spec.asset_key,
                check_name=spec.check_name,
                partition_date=partition_date,
            )
            if not records:
                blockers.append(f"neighbor check missing: {spec.check_name}:{partition_date}")
                continue
            record = records[0]
            evaluation = _check_evaluation(record)
            target = getattr(evaluation, "target_materialization_data", None)
            target_materialization = materializations.get(spec.asset_key)
            if (
                not _check_record_is_success(record)
                or getattr(evaluation, "passed", None) is not True
                or getattr(evaluation, "blocking", None) is not True
                or target is None
                or target_materialization is None
                or int(target.storage_id) != int(target_materialization.storage_id)
            ):
                blockers.append(f"neighbor check is not green and bound: {spec.check_name}:{partition_date}")
                continue
            facts.append(
                NeighborEventFact(
                    event_key=f"{spec.event_key}|{partition_date}",
                    storage_id=int(record.id),
                )
            )
    return tuple(sorted(facts, key=lambda value: value.event_key)), tuple(blockers)


def _matching_materializations(
    instance: Any, plan: StockDailyTrendChannelEventReconciliationPlan
) -> tuple[dict[str, object], tuple[str, ...]]:
    matches: dict[str, object] = {}
    blockers: list[str] = []
    for asset_key, file in (
        (STATE_ASSET_KEY, plan.state_file),
        (RESULT_ASSET_KEY, plan.result_file),
    ):
        records = _materialization_records(
            instance, asset_key=asset_key, partition_date=plan.partition_date
        )
        own = [record for record in records if _materialization_matches(record, plan, file)]
        unknown = [record for record in records if record not in own]
        if unknown:
            blockers.append(f"unknown materialization exists: {asset_key}:{plan.partition_date}")
        if len(own) > 1:
            blockers.append(f"duplicate plan materializations exist: {asset_key}:{plan.partition_date}")
        if own:
            matches[asset_key] = own[0]
    return matches, tuple(blockers)


def _matching_checks(
    instance: Any,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    materializations: Mapping[str, object],
) -> tuple[dict[str, object], tuple[str, ...]]:
    matches: dict[str, object] = {}
    blockers: list[str] = []
    files = {"state": plan.state_file, "result": plan.result_file}
    for spec in _check_specs():
        records = _check_records(
            instance,
            asset_key=spec.asset_key,
            check_name=spec.check_name,
            partition_date=plan.partition_date,
        )
        target_record = materializations.get(spec.asset_key)
        own = [
            record
            for record in records
            if target_record is not None
            and _check_matches(
                record,
                plan=plan,
                file=files[spec.target_file_role],
                target_storage_id=int(target_record.storage_id),
            )
        ]
        unknown_success = [
            record
            for record in records
            if _check_record_passed(record) and record not in own
        ]
        if unknown_success:
            blockers.append(f"unknown successful check exists: {spec.check_name}:{plan.partition_date}")
        if len(own) > 1:
            blockers.append(f"duplicate plan checks exist: {spec.check_name}:{plan.partition_date}")
        if own:
            matches[spec.check_name] = own[0]
            if records[0] is not own[0]:
                blockers.append(
                    f"latest check is not this plan's success: {spec.check_name}:"
                    f"{plan.partition_date}"
                )
    return matches, tuple(blockers)


def _materialization_records(
    instance: Any, *, asset_key: str, partition_date: str
) -> tuple[object, ...]:
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key),
            asset_partitions=[partition_date],
        ),
        limit=MAX_TARGET_EVENT_RECORDS,
    )
    if result.has_more:
        raise StockDailyTrendChannelEventReconciliationError(
            f"materialization history exceeds bound: {asset_key}:{partition_date}"
        )
    return tuple(result.records)


def _check_records(
    instance: Any, *, asset_key: str, check_name: str, partition_date: str
) -> tuple[object, ...]:
    records = instance.event_log_storage.get_asset_check_execution_history(
        dg.AssetCheckKey(dg.AssetKey(asset_key), check_name),
        limit=MAX_TARGET_EVENT_RECORDS,
        partition_filter=PartitionKeyFilter(key=partition_date),
    )
    if len(records) >= MAX_TARGET_EVENT_RECORDS:
        raise StockDailyTrendChannelEventReconciliationError(
            f"check history reaches the safety bound: {check_name}:{partition_date}"
        )
    return tuple(records)


def _materialization_matches(
    record: object,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    file: ReconciliationFileFact,
) -> bool:
    materialization = getattr(record, "asset_materialization", None)
    metadata = getattr(materialization, "metadata", {})
    return (
        str(getattr(record, "partition_key", "")) == plan.partition_date
        and _metadata_value(metadata, "dagster/uri") == file.path
        and _metadata_value(metadata, "dagster/row_count") == file.row_count
        and tuple(_metadata_value(metadata, "goldenshare/observed_columns") or ())
        == file.observed_columns
        and _reconciliation_metadata_matches(metadata, plan=plan, file=file)
    )


def _check_matches(
    record: object,
    *,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    file: ReconciliationFileFact,
    target_storage_id: int,
) -> bool:
    evaluation = _check_evaluation(record)
    metadata = getattr(evaluation, "metadata", {})
    target = getattr(evaluation, "target_materialization_data", None)
    return (
        _check_record_is_success(record)
        and getattr(evaluation, "passed", None) is True
        and getattr(evaluation, "blocking", None) is True
        and getattr(evaluation, "partition", None) == plan.partition_date
        and target is not None
        and int(target.storage_id) == target_storage_id
        and _reconciliation_metadata_matches(metadata, plan=plan, file=file)
    )


def _reconciliation_metadata_matches(
    metadata: Mapping[str, object],
    *,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    file: ReconciliationFileFact,
) -> bool:
    expected = {
        "goldenshare/source_method": RECONCILIATION_SOURCE_METHOD,
        "goldenshare/reconciliation_reason": RECONCILIATION_REASON,
        "goldenshare/incident_run_id": plan.incident_run.run_id,
        "goldenshare/current_file_producer_run_id": (
            plan.current_file_producer_run.run_id
        ),
        "goldenshare/plan_id": plan.plan_id,
        "goldenshare/plan_hash": plan.plan_hash,
        "goldenshare/file_sha256": file.sha256,
    }
    return all(_metadata_value(metadata, key) == value for key, value in expected.items())


def _materialization_metadata(
    *,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    physical: _PhysicalSnapshot,
    file: ReconciliationFileFact,
) -> dict[str, object]:
    inputs = {value.role: value for value in physical.input_files}
    return build_materialization_metadata(
        uri=file.path,
        row_count=file.row_count,
        observed_columns=file.observed_columns,
        extra_metadata={
            "partition_key": plan.partition_date,
            "formula_version": plan.formula_version,
            "file_bytes": file.size_bytes,
            "file_sha256": file.sha256,
            "source_qfq_file_path": inputs["qfq"].path,
            "previous_state_file_path": inputs["previous_state"].path,
            "stock_lifecycle_file_path": inputs["lifecycle"].path,
            "source_method": RECONCILIATION_SOURCE_METHOD,
            "reconciliation_reason": RECONCILIATION_REASON,
            "incident_run_id": plan.incident_run.run_id,
            "current_file_producer_run_id": plan.current_file_producer_run.run_id,
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
        },
    )


def _check_metadata(
    *,
    spec: _CheckSpec,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    physical: _PhysicalSnapshot,
) -> dict[str, object]:
    inputs = {value.role: value for value in physical.input_files}
    common = {
        "source_method": RECONCILIATION_SOURCE_METHOD,
        "reconciliation_reason": RECONCILIATION_REASON,
        "incident_run_id": plan.incident_run.run_id,
        "current_file_producer_run_id": plan.current_file_producer_run.run_id,
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "file_sha256": (
            physical.state_file.sha256
            if spec.target_file_role == "state"
            else physical.result_file.sha256
        ),
    }
    if spec.check_name == STATE_CONTRACT_CHECK:
        return _ordinary_check_metadata(
            audit=physical.state_audit,
            file_path=Path(physical.state_file.path),
            input_paths=(Path(inputs["lifecycle"].path),),
            success_summary="股票日线趋势通道 state contract check 通过。",
            success_next_action="无需处理，下一 expected 交易日可以承接该状态。",
            extra_metadata=common,
        )
    if spec.check_name == RESULT_CONTRACT_CHECK:
        return _ordinary_check_metadata(
            audit=physical.result_audit,
            file_path=Path(physical.result_file.path),
            input_paths=(Path(inputs["qfq"].path),),
            success_summary="股票日线趋势通道 result contract check 通过。",
            success_next_action="无需处理，等待下游消费。",
            extra_metadata=common,
        )
    coverage = physical.coverage_audit
    coverage_extra = {
        **common,
        "audited_state_file_sha256": physical.state_file.sha256,
        "summary": "股票日线趋势通道 input coverage check 通过。",
        "next_action": "无需处理，observed、carry 和 uninitialized 对账一致。",
        "failure_rule_counts": dict(coverage.failure_rule_counts),
        "failure_samples": _metadata_failure_samples(coverage.failure_samples),
        "source_row_count": coverage.qfq_observed_count,
        "output_row_count": coverage.checked_row_count,
        "formula_version": FORMULA_VERSION,
        "expected_lifecycle_count": coverage.expected_lifecycle_count,
        "qfq_observed_count": coverage.qfq_observed_count,
        "previous_initialized_count": coverage.previous_initialized_count,
        "expected_carry_count": coverage.expected_carry_count,
        "actual_observed_state_count": coverage.actual_observed_state_count,
        "actual_carry_state_count": coverage.actual_carry_state_count,
        "uninitialized_count": coverage.uninitialized_count,
        "missing_state_count": coverage.missing_state_count,
        "unexpected_state_count": coverage.unexpected_state_count,
    }
    return build_check_metadata(
        check_scope=CheckScope.RECONCILIATION,
        checked_row_count=coverage.checked_row_count,
        failed_row_count=coverage.failed_row_count,
        file_path=physical.state_file.path,
        input_file_paths=(
            inputs["qfq"].path,
            inputs["lifecycle"].path,
            inputs["previous_state"].path,
        ),
        extra_metadata=coverage_extra,
    )


def _ordinary_check_metadata(
    *,
    audit: StockDailyTrendChannelAudit,
    file_path: Path,
    input_paths: tuple[Path, ...],
    success_summary: str,
    success_next_action: str,
    extra_metadata: Mapping[str, object],
) -> dict[str, object]:
    if not audit.passed:
        raise StockDailyTrendChannelEventReconciliationError(
            "failed audit cannot produce a successful check event"
        )
    return build_check_metadata(
        check_scope=CheckScope.SCHEMA,
        checked_row_count=audit.checked_row_count,
        failed_row_count=audit.failed_row_count,
        file_path=file_path,
        input_file_paths=input_paths,
        extra_metadata={
            **extra_metadata,
            "summary": success_summary,
            "next_action": success_next_action,
            "failure_rule_counts": dict(audit.failure_rule_counts),
            "failure_samples": _metadata_failure_samples(audit.failure_samples),
            "source_row_count": audit.source_row_count,
            "output_row_count": audit.output_row_count,
            "formula_version": FORMULA_VERSION,
            "observed_columns": list(audit.observed_columns),
        },
    )


def _metadata_failure_samples(
    samples: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        str(rule_name): [dict(sample) for sample in rule_samples]
        for rule_name, rule_samples in samples.items()
    }


def _check_specs() -> tuple[_CheckSpec, ...]:
    return (
        _CheckSpec(STATE_ASSET_KEY, STATE_CONTRACT_CHECK, "state"),
        _CheckSpec(RESULT_ASSET_KEY, RESULT_CONTRACT_CHECK, "result"),
        _CheckSpec(RESULT_ASSET_KEY, INPUT_COVERAGE_CHECK, "result"),
    )


def _active_run_ids(instance: Any) -> tuple[str, ...]:
    run_ids = {
        run.run_id
        for job_name in _ACTIVE_JOB_NAMES
        for run in instance.get_runs(
            filters=dg.RunsFilter(
                job_name=job_name,
                statuses=list(_ACTIVE_RUN_STATUSES),
            ),
            limit=1,
        )
    }
    return tuple(sorted(run_ids))


def _assert_pre_event_gates(
    instance: Any,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    file: ReconciliationFileFact,
) -> None:
    active = _active_run_ids(instance)
    if active:
        raise StockDailyTrendChannelEventReconciliationError(
            "active source-changing run appeared before event write"
        )
    path = Path(file.path)
    if (
        not path.is_file()
        or path.stat().st_size != file.size_bytes
        or _file_sha256(path) != file.sha256
    ):
        raise StockDailyTrendChannelEventReconciliationError(
            f"target file changed before event write: {path}"
        )
    current_guard, blockers = _neighbor_event_guard(instance)
    if blockers or current_guard != plan.neighbor_event_guard:
        raise StockDailyTrendChannelEventReconciliationError(
            "neighbor event guard changed before event write"
        )


def _assert_all_file_fingerprints(
    plan: StockDailyTrendChannelEventReconciliationPlan,
) -> None:
    for file in (plan.result_file, plan.state_file, *plan.input_files):
        path = Path(file.path)
        if (
            not path.is_file()
            or path.stat().st_size != file.size_bytes
            or _file_sha256(path) != file.sha256
        ):
            raise StockDailyTrendChannelEventReconciliationError(
                f"physical files changed after plan: {path}"
            )


def _assert_plan_bounds(plan: StockDailyTrendChannelEventReconciliationPlan) -> None:
    if (
        plan.formula_version != FORMULA_VERSION
        or plan.maximum_event_writes != MAX_EVENT_WRITES
        or not 0 <= plan.expected_materialization_writes <= MAX_MATERIALIZATION_WRITES
        or not 0 <= plan.expected_check_writes <= MAX_CHECK_WRITES
        or plan.expected_materialization_writes + plan.expected_check_writes
        > MAX_EVENT_WRITES
    ):
        raise StockDailyTrendChannelEventReconciliationError(
            "reconciliation plan exceeds its frozen event bounds"
        )


def _stage_report(
    *,
    stage: str,
    plan: StockDailyTrendChannelEventReconciliationPlan,
    attempted: Sequence[str],
    skipped: Sequence[str],
    written: Sequence[Mapping[str, object]],
    before_count: int,
    after_count: int,
    started_at: float,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": stage,
        "status": "already_reconciled" if not written else "applied",
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "partition_date": plan.partition_date,
        "attempted_event_keys": list(attempted),
        "skipped_event_keys": list(skipped),
        "written_events": [dict(value) for value in written],
        "before_event_count": before_count,
        "after_event_count": after_count,
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
    }


def _check_evaluation(record: object) -> object:
    event = getattr(record, "event", None)
    dagster_event = getattr(event, "dagster_event", None)
    return getattr(dagster_event, "event_specific_data", None)


def _check_record_is_success(record: object) -> bool:
    return _status_value(getattr(record, "status", None)) == "SUCCEEDED"


def _check_record_passed(record: object) -> bool:
    return (
        _check_record_is_success(record)
        and getattr(_check_evaluation(record), "passed", None) is True
    )


def _status_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _metadata_value(metadata: Mapping[str, object], key: str) -> object | None:
    value = metadata.get(key)
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "data"):
        return value.data
    if hasattr(value, "text"):
        return value.text
    return value


def _event_log_text_values(entry: object) -> tuple[str, ...]:
    dagster_event = getattr(entry, "dagster_event", None)
    event_data = getattr(dagster_event, "event_specific_data", None)
    error = getattr(event_data, "error", None)
    values = (
        getattr(entry, "user_message", None),
        getattr(dagster_event, "message", None),
        str(error) if error is not None else None,
    )
    return tuple(str(value) for value in values if value)


def _plan_hash(payload: Mapping[str, object]) -> str:
    canonical = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "plan_id", "plan_hash"}
    }
    return _hash_payload(canonical)


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize_date(value: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as error:
        raise StockDailyTrendChannelEventReconciliationError(
            f"invalid ISO partition date: {value}"
        ) from error


def _assert_path_in_root(path: Path, *, root: Path) -> None:
    normalized = path.resolve()
    if normalized == root or not normalized.is_relative_to(root):
        raise StockDailyTrendChannelEventReconciliationError(
            f"path is outside the configured Lake root: {normalized}"
        )


def _validated_report_path(path: Path, *, report_root: Path) -> Path:
    normalized = Path(path).resolve()
    normalized_root = Path(report_root).resolve()
    if normalized == normalized_root or not normalized.is_relative_to(normalized_root):
        raise StockDailyTrendChannelEventReconciliationError(
            f"report must be a file under {normalized_root}"
        )
    return normalized


def _load_json(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StockDailyTrendChannelEventReconciliationError(
            f"reconciliation plan is unreadable: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise StockDailyTrendChannelEventReconciliationError(
            "reconciliation plan must be a JSON object"
        )
    return payload


def _required_mapping(
    payload: Mapping[str, object], key: str
) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise StockDailyTrendChannelEventReconciliationError(
            f"{key} must be an object"
        )
    return value


def _required_mapping_list(
    payload: Mapping[str, object], key: str
) -> tuple[Mapping[str, object], ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise StockDailyTrendChannelEventReconciliationError(
            f"{key} must be an object list"
        )
    return tuple(value)


def _required_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise StockDailyTrendChannelEventReconciliationError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise StockDailyTrendChannelEventReconciliationError(
            f"{key} must be an integer"
        )
    return value


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise StockDailyTrendChannelEventReconciliationError(
            f"{key} must be a boolean"
        )
    return value


def _required_str_tuple(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise StockDailyTrendChannelEventReconciliationError(
            f"{key} must be a string list"
        )
    return tuple(value)


def _assert_stage_budget(started_at: float) -> None:
    if time.perf_counter() - started_at > MAX_STAGE_SECONDS:
        raise StockDailyTrendChannelEventReconciliationError(
            "reconciliation stage exceeded the 30 second safety budget"
        )


__all__ = [
    "StockDailyTrendChannelEventReconciliationError",
    "StockDailyTrendChannelEventReconciliationPlan",
    "apply_stock_daily_trend_channel_check_reconciliation",
    "apply_stock_daily_trend_channel_materialization_reconciliation",
    "audit_stock_daily_trend_channel_event_reconciliation",
    "audit_stock_daily_trend_channel_materialization_reconciliation",
    "build_stock_daily_trend_channel_event_reconciliation_plan",
    "load_stock_daily_trend_channel_event_reconciliation_plan",
    "write_stock_daily_trend_channel_event_reconciliation_report",
]
