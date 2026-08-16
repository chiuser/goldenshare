"""D4 runless-event recovery for the daily no-price QFQ nine-turn migration."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.qfq_nineturn_events import (
    report_qfq_nineturn_check_event,
    report_qfq_nineturn_materialization_event,
)
from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_history import (
    AUDIT_PHASE,
    CONTRACT,
    FORMAL_AUDIT_PHASE,
    StockDailyQfqNineTurnNoPricePlan,
    load_stock_daily_qfq_nineturn_no_price_plan,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.qfq_nineturn_integrity import (
    audit_qfq_nineturn_integrity,
    qfq_nineturn_source_paths_for_partition,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.qfq_nineturn import QFQ_NINETURN_VERSION

SCHEMA_VERSION = 1
PLAN_PHASE = "stock_daily_qfq_nineturn_no_price_event_plan"
APPLY_PHASE = "stock_daily_qfq_nineturn_no_price_event_apply"
EVENT_REVISION = "stock_daily_qfq_nineturn_v2_no_price"
EVENT_BACKFILL_SCOPE = "daily_no_price_all_materializations_recent_checks"
ASSET_KEY = "gold_stock_daily_qfq_nineturn"
CHECK_NAME = "gold_stock_daily_qfq_nineturn_integrity_check"
CHECK_WINDOW = 20
MAX_CHECK_HISTORY = 500
MAX_MATERIALIZATION_EVENTS = 4_000
MAX_CHECK_EVENTS = CHECK_WINDOW
WRITER_SENSOR_NAMES = (
    "gold_stock_daily_qfq_nineturn_update_job_sensor",
    "prod_core_stock_daily_qfq_nineturn_sync_job_sensor",
)
WRITER_JOB_NAMES = (
    "gold_stock_daily_qfq_nineturn_update_job",
    "prod_core_stock_daily_qfq_nineturn_sync_job",
)
_IN_FLIGHT_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class StockDailyQfqNineTurnNoPriceEventError(RuntimeError):
    """Raised when a D4 event-recovery gate fails."""


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnNoPriceEventPartition:
    partition_key: str
    relative_path: str
    file_size: int
    file_mtime_ns: int
    file_sha256: str
    row_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnNoPriceEventCandidate:
    partition_key: str
    event_type: str
    check_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnNoPriceEventPlan:
    report_path: Path
    identity_manifest_path: Path
    candidate_manifest_path: Path
    lake_plan_report_path: Path
    formal_audit_report_path: Path
    plan_fingerprint: str
    partitions: tuple[StockDailyQfqNineTurnNoPriceEventPartition, ...]
    candidates: tuple[StockDailyQfqNineTurnNoPriceEventCandidate, ...]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    @property
    def planned_materialization_event_count(self) -> int:
        return sum(item.event_type == "materialization" for item in self.candidates)

    @property
    def planned_check_event_count(self) -> int:
        return sum(item.event_type == "check" for item in self.candidates)

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "phase": PLAN_PHASE,
            "read_only": True,
            "report_path": str(self.report_path),
            "plan_fingerprint": self.plan_fingerprint,
            "partition_count": len(self.partitions),
            "planned_materialization_event_count": (
                self.planned_materialization_event_count
            ),
            "planned_check_event_count": self.planned_check_event_count,
            "planned_event_count": len(self.candidates),
            "should_stop": self.should_stop,
            "stop_reasons": list(self.stop_reasons),
        }


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnNoPriceEventApplyReport:
    report_path: Path
    plan_fingerprint: str
    batch_id: str
    materialization_event_count: int
    check_event_count: int
    post_plan_event_count: int
    current_revision_materialization_count: int
    current_revision_check_count: int
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["report_path"] = str(self.report_path)
        return payload


def plan_stock_daily_qfq_nineturn_no_price_events(
    *,
    instance: dg.DagsterInstance,
    lake_plan_report_path: Path,
    formal_audit_report_path: Path,
    expected_lake_plan_hash: str,
    expected_partition_count: int,
    expected_row_count: int,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource | None = None,
    output_dir: Path = Path("/private/tmp"),
) -> StockDailyQfqNineTurnNoPriceEventPlan:
    """Freeze the D3 file identity and current Dagster state without writes."""

    started = time.perf_counter()
    lake_plan = load_stock_daily_qfq_nineturn_no_price_plan(lake_plan_report_path)
    normalized_lake_root = Path(lake_root).resolve()
    if lake_plan.plan_hash != expected_lake_plan_hash:
        raise StockDailyQfqNineTurnNoPriceEventError(
            "Reviewed D3 Lake plan hash does not match."
        )
    if lake_plan.lake_root.resolve() != normalized_lake_root:
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D3 Lake plan root does not match D4 Lake root."
        )
    expected_formal_audit = lake_plan.phase_root / "formal-audit.json"
    if Path(formal_audit_report_path).resolve() != expected_formal_audit.resolve():
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D4 requires the formal audit produced by the reviewed D3 plan."
        )
    formal_audit = _load_json(formal_audit_report_path)
    _assert_green_formal_audit(formal_audit, lake_plan=lake_plan)
    candidate_audit_path = lake_plan.phase_root / "candidate-audit-full.json"
    candidate_audit = _load_json(candidate_audit_path)
    _assert_green_candidate_audit(candidate_audit, lake_plan=lake_plan)
    candidate_manifest_path = Path(str(candidate_audit["manifest_path"]))
    if not candidate_manifest_path.resolve().is_relative_to(
        lake_plan.phase_root.resolve()
    ):
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D3 candidate manifest is outside the reviewed staging phase."
        )
    if _sha256_path(candidate_manifest_path) != str(candidate_audit["manifest_sha256"]):
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D3 candidate manifest SHA-256 changed."
        )
    candidate_manifest = _load_json(candidate_manifest_path)
    manifest_by_partition = {
        str(item["partition_key"]): dict(item) for item in candidate_manifest["files"]
    }

    stop_reasons: list[str] = []
    if lake_plan.should_stop:
        stop_reasons.append("d3_lake_plan_should_stop")
    if len(lake_plan.partitions) != expected_partition_count:
        stop_reasons.append("unexpected_partition_count")
    if sum(item.row_count for item in lake_plan.partitions) != expected_row_count:
        stop_reasons.append("unexpected_row_count")
    if int(formal_audit.get("partition_count", -1)) != expected_partition_count:
        stop_reasons.append("formal_audit_partition_count_mismatch")
    if int(formal_audit.get("row_count", -1)) != expected_row_count:
        stop_reasons.append("formal_audit_row_count_mismatch")

    partitions: list[StockDailyQfqNineTurnNoPriceEventPartition] = []
    for item in lake_plan.partitions:
        formal = normalized_lake_root / item.relative_path
        if (
            not formal.resolve().is_relative_to(normalized_lake_root)
            or formal.is_symlink()
            or not formal.is_file()
        ):
            stop_reasons.append(f"{item.partition_key}:formal_file_invalid")
            continue
        manifest_item = manifest_by_partition.get(item.partition_key)
        if manifest_item is None:
            stop_reasons.append(f"{item.partition_key}:d3_manifest_missing")
            continue
        stat = formal.stat()
        file_sha256 = _sha256_path(formal)
        if file_sha256 != str(manifest_item["candidate_sha256"]):
            stop_reasons.append(f"{item.partition_key}:formal_hash_mismatch")
        if int(manifest_item["row_count"]) != item.row_count:
            stop_reasons.append(f"{item.partition_key}:row_count_mismatch")
        partitions.append(
            StockDailyQfqNineTurnNoPriceEventPartition(
                partition_key=item.partition_key,
                relative_path=item.relative_path,
                file_size=stat.st_size,
                file_mtime_ns=stat.st_mtime_ns,
                file_sha256=file_sha256,
                row_count=item.row_count,
            )
        )
    normalized_partitions = tuple(
        sorted(partitions, key=lambda value: value.partition_key)
    )
    if len(normalized_partitions) != expected_partition_count:
        stop_reasons.append("formal_identity_scope_incomplete")

    registered = {
        str(value)
        for value in instance.get_dynamic_partitions(cn_a_stock_trade_days.name)
    }
    missing_registered = tuple(
        sorted({item.partition_key for item in normalized_partitions} - registered)
    )
    if missing_registered:
        stop_reasons.append("missing_registered_partitions")

    sensor_states = _writer_sensor_states(instance)
    running_sensors = tuple(
        name for name, status in sensor_states.items() if status == "RUNNING"
    )
    if running_sensors:
        stop_reasons.append("writer_sensor_running")
    active_runs = _active_writer_run_counts(instance)
    if any(active_runs.values()):
        stop_reasons.append("writer_run_in_flight")

    recent_partitions = tuple(
        item.partition_key for item in normalized_partitions[-CHECK_WINDOW:]
    )
    integrity_by_partition: dict[str, dict[str, object]] = {}
    resource = duckdb_resource or DuckDBResource()
    with resource.connect() as connection:
        for partition_key in recent_partitions:
            target_path = _target_path(normalized_lake_root, partition_key)
            diagnostics = audit_qfq_nineturn_integrity(
                connection,
                target_path=target_path,
                source_paths=qfq_nineturn_source_paths_for_partition(
                    lake_root=normalized_lake_root,
                    partition_key=partition_key,
                    freq=None,
                ),
                partition_key=partition_key,
                freq=None,
            )
            integrity_by_partition[partition_key] = {
                "passed": diagnostics.passed,
                "checked_row_count": diagnostics.checked_row_count,
                "source_row_count": diagnostics.source_row_count,
                "failed_rule_names": list(diagnostics.failed_rule_names),
            }
            if not diagnostics.passed:
                stop_reasons.append(f"{partition_key}:integrity_failed")

    physical_fingerprint = _hash_payload(
        [item.to_dict() for item in normalized_partitions]
    )
    latest_records = _latest_materialization_records(
        instance,
        partition_keys=tuple(item.partition_key for item in normalized_partitions),
    )
    file_sha256_by_partition = {
        item.partition_key: item.file_sha256 for item in normalized_partitions
    }
    current_materializations = {
        partition_key: record
        for partition_key, record in latest_records.items()
        if _materialization_matches_revision(
            record,
            file_sha256=file_sha256_by_partition[partition_key],
        )
    }
    latest_checks = _latest_check_records(instance, recent_partitions)
    current_checks = {
        partition_key: record
        for partition_key, record in latest_checks.items()
        if partition_key in current_materializations
        and _check_matches_revision(
            record,
            materialization_storage_id=int(
                current_materializations[partition_key].storage_id
            ),
        )
    }

    candidates: list[StockDailyQfqNineTurnNoPriceEventCandidate] = []
    for item in normalized_partitions:
        if item.partition_key not in current_materializations:
            candidates.append(
                StockDailyQfqNineTurnNoPriceEventCandidate(
                    partition_key=item.partition_key,
                    event_type="materialization",
                )
            )
    for partition_key in recent_partitions:
        if partition_key not in current_checks:
            candidates.append(
                StockDailyQfqNineTurnNoPriceEventCandidate(
                    partition_key=partition_key,
                    event_type="check",
                    check_name=CHECK_NAME,
                )
            )
    normalized_candidates = tuple(sorted(candidates, key=_candidate_sort_key))
    planned_materialization_event_count = sum(
        item.event_type == "materialization" for item in normalized_candidates
    )
    planned_check_event_count = sum(
        item.event_type == "check" for item in normalized_candidates
    )
    if planned_materialization_event_count > MAX_MATERIALIZATION_EVENTS:
        stop_reasons.append("materialization_event_limit_exceeded")
    if planned_check_event_count > MAX_CHECK_EVENTS:
        stop_reasons.append("check_event_limit_exceeded")
    latest_materialization_storage_id = max(
        (int(record.storage_id) for record in latest_records.values()),
        default=None,
    )
    latest_check_storage_id = max(
        (
            int(record.id)
            for record in latest_checks.values()
            if getattr(record, "id", None) is not None
        ),
        default=None,
    )
    state = {
        "latest_materialization_storage_id": latest_materialization_storage_id,
        "latest_check_storage_id": latest_check_storage_id,
        "current_revision_materialization_count": len(current_materializations),
        "current_revision_check_count": len(current_checks),
        "sensor_states": sensor_states,
        "active_writer_run_counts": active_runs,
    }
    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "asset_key": ASSET_KEY,
        "check_name": CHECK_NAME,
        "event_revision": EVENT_REVISION,
        "lake_plan_hash": lake_plan.plan_hash,
        "formal_audit_sha256": _sha256_path(formal_audit_report_path),
        "physical_fingerprint": physical_fingerprint,
        "state": state,
        "candidates": [item.to_dict() for item in normalized_candidates],
        "stop_reasons": sorted(set(stop_reasons)),
    }
    plan_fingerprint = _hash_payload(fingerprint_payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    identity_manifest_path = output_dir / (
        f"stock_daily_qfq_nineturn_no_price_event_identity_{plan_fingerprint}.jsonl"
    )
    candidate_output_path = output_dir / (
        f"stock_daily_qfq_nineturn_no_price_event_candidates_{plan_fingerprint}.jsonl"
    )
    _write_jsonl(
        identity_manifest_path, [item.to_dict() for item in normalized_partitions]
    )
    _write_jsonl(
        candidate_output_path, [item.to_dict() for item in normalized_candidates]
    )
    report_path = output_dir / (
        f"stock_daily_qfq_nineturn_no_price_event_plan_{plan_fingerprint}.json"
    )
    report = {
        **fingerprint_payload,
        "phase": PLAN_PHASE,
        "read_only": True,
        "planned_at": datetime.now(UTC).isoformat(),
        "plan_fingerprint": plan_fingerprint,
        "lake_root": str(normalized_lake_root),
        "lake_plan_report_path": str(lake_plan_report_path),
        "formal_audit_report_path": str(formal_audit_report_path),
        "identity_manifest_path": str(identity_manifest_path),
        "identity_manifest_sha256": _sha256_path(identity_manifest_path),
        "candidate_manifest_path": str(candidate_output_path),
        "candidate_manifest_sha256": _sha256_path(candidate_output_path),
        "partition_count": len(normalized_partitions),
        "row_count": sum(item.row_count for item in normalized_partitions),
        "first_partition_key": (
            normalized_partitions[0].partition_key if normalized_partitions else None
        ),
        "last_partition_key": (
            normalized_partitions[-1].partition_key if normalized_partitions else None
        ),
        "registered_partition_count": len(registered),
        "missing_registered_partition_count": len(missing_registered),
        "missing_registered_partition_samples": list(missing_registered[:20]),
        "recent_check_partition_keys": list(recent_partitions),
        "recent_integrity": integrity_by_partition,
        "planned_materialization_event_count": planned_materialization_event_count,
        "planned_check_event_count": planned_check_event_count,
        "planned_event_count": len(normalized_candidates),
        "should_stop": bool(stop_reasons),
        "stop_reasons": sorted(set(stop_reasons)),
        "write_counters": {
            "formal_lake": 0,
            "dagster_events": 0,
            "prod_rows": 0,
        },
        "performance": {
            "formal_file_count": len(normalized_partitions),
            "blocking_check_partition_count": len(recent_partitions),
            "dagster_materialization_query_limit": len(normalized_partitions),
            "dagster_check_query_limit": MAX_CHECK_HISTORY,
            "materialization_event_write_limit": MAX_MATERIALIZATION_EVENTS,
            "check_event_write_limit": MAX_CHECK_EVENTS,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }
    _write_json(report_path, report)
    return StockDailyQfqNineTurnNoPriceEventPlan(
        report_path=report_path,
        identity_manifest_path=identity_manifest_path,
        candidate_manifest_path=candidate_output_path,
        lake_plan_report_path=Path(lake_plan_report_path),
        formal_audit_report_path=Path(formal_audit_report_path),
        plan_fingerprint=plan_fingerprint,
        partitions=normalized_partitions,
        candidates=normalized_candidates,
        stop_reasons=tuple(sorted(set(stop_reasons))),
        report=report,
    )


def load_stock_daily_qfq_nineturn_no_price_event_plan(
    report_path: Path,
) -> StockDailyQfqNineTurnNoPriceEventPlan:
    payload = _load_json(report_path)
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != PLAN_PHASE
        or payload.get("read_only") is not True
    ):
        raise StockDailyQfqNineTurnNoPriceEventError("Unsupported D4 event plan.")
    if payload.get("should_stop"):
        raise StockDailyQfqNineTurnNoPriceEventError(
            f"D4 event plan has stop reasons: {payload.get('stop_reasons', [])}."
        )
    identity_manifest_path = Path(str(payload["identity_manifest_path"]))
    candidate_manifest_path = Path(str(payload["candidate_manifest_path"]))
    if _sha256_path(identity_manifest_path) != str(payload["identity_manifest_sha256"]):
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D4 identity manifest SHA-256 changed."
        )
    if _sha256_path(candidate_manifest_path) != str(
        payload["candidate_manifest_sha256"]
    ):
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D4 candidate manifest SHA-256 changed."
        )
    partitions = tuple(
        StockDailyQfqNineTurnNoPriceEventPartition(**item)
        for item in _load_jsonl(identity_manifest_path)
    )
    candidates = tuple(
        StockDailyQfqNineTurnNoPriceEventCandidate(**item)
        for item in _load_jsonl(candidate_manifest_path)
    )
    return StockDailyQfqNineTurnNoPriceEventPlan(
        report_path=Path(report_path),
        identity_manifest_path=identity_manifest_path,
        candidate_manifest_path=candidate_manifest_path,
        lake_plan_report_path=Path(str(payload["lake_plan_report_path"])),
        formal_audit_report_path=Path(str(payload["formal_audit_report_path"])),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        partitions=partitions,
        candidates=candidates,
        stop_reasons=(),
        report=payload,
    )


def apply_stock_daily_qfq_nineturn_no_price_events(
    *,
    instance: dg.DagsterInstance,
    plan: StockDailyQfqNineTurnNoPriceEventPlan,
    expected_plan_fingerprint: str,
    confirm_apply: bool,
    duckdb_resource: DuckDBResource | None = None,
    output_dir: Path = Path("/private/tmp"),
) -> StockDailyQfqNineTurnNoPriceEventApplyReport:
    """Append only the candidates from a freshly regenerated D4 plan."""

    if not confirm_apply:
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D4 event apply requires explicit confirmation."
        )
    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise StockDailyQfqNineTurnNoPriceEventError(
            "Explicit D4 event fingerprint does not match the plan."
        )
    fresh_plan = plan_stock_daily_qfq_nineturn_no_price_events(
        instance=instance,
        lake_plan_report_path=plan.lake_plan_report_path,
        formal_audit_report_path=plan.formal_audit_report_path,
        expected_lake_plan_hash=str(plan.report["lake_plan_hash"]),
        expected_partition_count=int(plan.report["partition_count"]),
        expected_row_count=int(plan.report["row_count"]),
        lake_root=Path(str(plan.report["lake_root"])),
        duckdb_resource=duckdb_resource,
        output_dir=output_dir,
    )
    if (
        fresh_plan.should_stop
        or fresh_plan.plan_fingerprint != plan.plan_fingerprint
        or fresh_plan.candidates != plan.candidates
        or fresh_plan.partitions != plan.partitions
    ):
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D4 event plan is stale; generate and review a new plan."
        )

    started = time.perf_counter()
    batch_id = str(uuid.uuid4())
    by_partition = {item.partition_key: item for item in plan.partitions}
    materialization_candidates = tuple(
        item for item in plan.candidates if item.event_type == "materialization"
    )
    check_candidates = tuple(
        item for item in plan.candidates if item.event_type == "check"
    )
    observed_columns = tuple(
        column.name for column in GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA
    )
    for candidate in materialization_candidates:
        partition = by_partition[candidate.partition_key]
        report_qfq_nineturn_materialization_event(
            instance,
            dg.AssetMaterialization(
                asset_key=dg.AssetKey(ASSET_KEY),
                partition=partition.partition_key,
                metadata=build_materialization_metadata(
                    uri=Path(str(plan.report["lake_root"])) / partition.relative_path,
                    row_count=partition.row_count,
                    observed_columns=observed_columns,
                    extra_metadata={
                        "bootstrap_method": "stock_daily_qfq_nineturn_no_price",
                        "bootstrap_event_backfill": True,
                        "event_backfill_scope": EVENT_BACKFILL_SCOPE,
                        "bootstrap_batch_id": batch_id,
                        "event_revision": EVENT_REVISION,
                        "contract": CONTRACT,
                        "lake_plan_hash": plan.report["lake_plan_hash"],
                        "formal_file_sha256": partition.file_sha256,
                        "formal_physical_fingerprint": plan.report[
                            "physical_fingerprint"
                        ],
                        "check_events_reported": False,
                        "formula_version": QFQ_NINETURN_VERSION,
                    },
                ),
            ),
        )

    for candidate in check_candidates:
        partition = by_partition[candidate.partition_key]
        materialization = _latest_materialization_records(
            instance,
            partition_keys=(partition.partition_key,),
        ).get(partition.partition_key)
        if materialization is None or not _materialization_matches_revision(
            materialization,
            file_sha256=partition.file_sha256,
        ):
            raise StockDailyQfqNineTurnNoPriceEventError(
                f"Missing D4 materialization for check: {partition.partition_key}."
            )
        target = AssetCheckEvaluationTargetMaterializationData(
            storage_id=int(materialization.storage_id),
            run_id=str(materialization.run_id),
            timestamp=float(materialization.timestamp),
        )
        report_qfq_nineturn_check_event(
            instance,
            run_id=f"stock-daily-qfq-nineturn-no-price-{batch_id}",
            evaluation=dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(ASSET_KEY),
                check_name=CHECK_NAME,
                passed=True,
                metadata=build_check_metadata(
                    check_scope=CheckScope.RECONCILIATION,
                    checked_row_count=partition.row_count,
                    file_path=(
                        Path(str(plan.report["lake_root"])) / partition.relative_path
                    ),
                    extra_metadata={
                        "summary": "日线九转六列正式分区完整性检查通过。",
                        "next_action": "无需处理，最近窗口已绑定 D4 新物化事件。",
                        "failed_rule_names": [],
                        "bootstrap_method": "stock_daily_qfq_nineturn_no_price",
                        "bootstrap_event_backfill": True,
                        "event_backfill_scope": EVENT_BACKFILL_SCOPE,
                        "bootstrap_batch_id": batch_id,
                        "event_revision": EVENT_REVISION,
                        "contract": CONTRACT,
                        "lake_plan_hash": plan.report["lake_plan_hash"],
                        "formal_file_sha256": partition.file_sha256,
                        "formula_version": QFQ_NINETURN_VERSION,
                    },
                ),
                blocking=True,
                partition=partition.partition_key,
                target_materialization_data=target,
            ),
        )

    post_plan = plan_stock_daily_qfq_nineturn_no_price_events(
        instance=instance,
        lake_plan_report_path=plan.lake_plan_report_path,
        formal_audit_report_path=plan.formal_audit_report_path,
        expected_lake_plan_hash=str(plan.report["lake_plan_hash"]),
        expected_partition_count=int(plan.report["partition_count"]),
        expected_row_count=int(plan.report["row_count"]),
        lake_root=Path(str(plan.report["lake_root"])),
        duckdb_resource=duckdb_resource,
        output_dir=output_dir,
    )
    if post_plan.should_stop or post_plan.candidates:
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D4 post-audit is not empty: "
            f"stop={post_plan.stop_reasons}, candidates={len(post_plan.candidates)}."
        )
    report_path = output_dir / (
        f"stock_daily_qfq_nineturn_no_price_event_apply_{plan.plan_fingerprint}.json"
    )
    report = StockDailyQfqNineTurnNoPriceEventApplyReport(
        report_path=report_path,
        plan_fingerprint=plan.plan_fingerprint,
        batch_id=batch_id,
        materialization_event_count=len(materialization_candidates),
        check_event_count=len(check_candidates),
        post_plan_event_count=len(post_plan.candidates),
        current_revision_materialization_count=int(
            post_plan.report["state"]["current_revision_materialization_count"]
        ),
        current_revision_check_count=int(
            post_plan.report["state"]["current_revision_check_count"]
        ),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    _write_json(
        report_path,
        {
            "schema_version": SCHEMA_VERSION,
            "phase": APPLY_PHASE,
            "event_revision": EVENT_REVISION,
            **report.to_dict(),
        },
    )
    return report


def _assert_green_formal_audit(
    payload: Mapping[str, object],
    *,
    lake_plan: StockDailyQfqNineTurnNoPricePlan,
) -> None:
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != FORMAL_AUDIT_PHASE
        or payload.get("contract") != CONTRACT
        or payload.get("plan_hash") != lake_plan.plan_hash
        or payload.get("should_stop") is not False
        or int(payload.get("hash_mismatch_count", -1)) != 0
        or int(payload.get("candidate_residual_count", -1)) != 0
    ):
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D4 requires the complete green D3 formal audit."
        )


def _assert_green_candidate_audit(
    payload: Mapping[str, object],
    *,
    lake_plan: StockDailyQfqNineTurnNoPricePlan,
) -> None:
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != AUDIT_PHASE
        or payload.get("contract") != CONTRACT
        or payload.get("plan_hash") != lake_plan.plan_hash
        or payload.get("mode") != "full"
        or payload.get("should_stop") is not False
    ):
        raise StockDailyQfqNineTurnNoPriceEventError(
            "D4 requires the complete green D3 candidate audit."
        )


def _writer_sensor_states(instance: dg.DagsterInstance) -> dict[str, str]:
    states = {name: "NOT_FOUND" for name in WRITER_SENSOR_NAMES}
    for state in instance.all_instigator_state():
        name = getattr(state, "name", None) or getattr(state, "instigator_name", None)
        if name in states:
            states[str(name)] = str(
                getattr(getattr(state, "status", None), "value", "UNKNOWN")
            )
    return states


def _active_writer_run_counts(instance: dg.DagsterInstance) -> dict[str, int]:
    return {
        job_name: instance.get_runs_count(
            filters=dg.RunsFilter(
                job_name=job_name,
                statuses=list(_IN_FLIGHT_STATUSES),
            )
        )
        for job_name in WRITER_JOB_NAMES
    }


def _latest_materialization_records(
    instance: dg.DagsterInstance,
    *,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    if not partition_keys:
        return {}
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(ASSET_KEY),
            asset_partitions=list(partition_keys),
        ),
        limit=len(partition_keys),
    )
    records: dict[str, object] = {}
    for record in result.records:
        partition_key = getattr(record, "partition_key", None)
        if partition_key is not None and str(partition_key) not in records:
            records[str(partition_key)] = record
    return records


def _latest_check_records(
    instance: dg.DagsterInstance,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    selected = set(partition_keys)
    records = instance.event_log_storage.get_asset_check_execution_history(
        dg.AssetCheckKey(dg.AssetKey(ASSET_KEY), CHECK_NAME),
        limit=MAX_CHECK_HISTORY,
    )
    latest: dict[str, object] = {}
    for record in records:
        partition_key = getattr(record, "partition", None)
        if partition_key in selected and str(partition_key) not in latest:
            latest[str(partition_key)] = record
    return latest


def _materialization_matches_revision(record: object, *, file_sha256: str) -> bool:
    materialization = getattr(record, "asset_materialization", None)
    metadata = getattr(materialization, "metadata", {})
    return (
        _metadata_value(metadata, "event_revision") == EVENT_REVISION
        and _metadata_value(metadata, "contract") == CONTRACT
        and _metadata_value(metadata, "formal_file_sha256") == file_sha256
    )


def _check_matches_revision(
    record: object,
    *,
    materialization_storage_id: int,
) -> bool:
    event = getattr(record, "event", None)
    dagster_event = getattr(event, "dagster_event", None) if event is not None else None
    evaluation = (
        getattr(dagster_event, "event_specific_data", None)
        if dagster_event is not None
        else None
    )
    target = getattr(evaluation, "target_materialization_data", None)
    metadata = getattr(evaluation, "metadata", {})
    return (
        getattr(getattr(record, "status", None), "value", None) == "SUCCEEDED"
        and bool(getattr(evaluation, "passed", False))
        and bool(getattr(evaluation, "blocking", False))
        and target is not None
        and int(target.storage_id) == materialization_storage_id
        and _metadata_value(metadata, "event_revision") == EVENT_REVISION
        and _metadata_value(metadata, "contract") == CONTRACT
    )


def _metadata_value(metadata: Mapping[str, object], key: str) -> object | None:
    value = metadata.get(key)
    if value is None:
        value = metadata.get(f"goldenshare/{key}")
    return getattr(value, "value", None) if value is not None else None


def _target_path(lake_root: Path, partition_key: str) -> Path:
    return (
        lake_root
        / "gold/indicator/stock_daily_qfq_nineturn"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )


def _candidate_sort_key(
    candidate: StockDailyQfqNineTurnNoPriceEventCandidate,
) -> tuple[str, str]:
    return (candidate.partition_key, candidate.event_type)


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Mapping[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    return tuple(
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


__all__ = [
    "StockDailyQfqNineTurnNoPriceEventError",
    "apply_stock_daily_qfq_nineturn_no_price_events",
    "load_stock_daily_qfq_nineturn_no_price_event_plan",
    "plan_stock_daily_qfq_nineturn_no_price_events",
]
