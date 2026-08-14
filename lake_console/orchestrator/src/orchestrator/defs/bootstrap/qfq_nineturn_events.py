"""Runless materialization and recent-check events for QFQ nine-turn history."""

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
from dagster._core.events import DagsterEvent, DagsterEventType
from dagster._core.instance.utils import RUNLESS_JOB_NAME

from orchestrator.defs.bootstrap.qfq_nineturn_history import (
    QfqNineturnHistoryPlan,
    load_qfq_nineturn_history_plan,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_trade_days,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_nineturn_path,
    gold_stock_daily_qfq_nineturn_path,
)
from orchestrator.defs.qfq_nineturn_integrity import (
    audit_qfq_nineturn_integrity,
    qfq_nineturn_source_paths_for_partition,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_HISTORY_CHECK_WINDOW,
    QFQ_NINETURN_MINUTE_FREQS,
    QFQ_NINETURN_VERSION,
)

SCHEMA_VERSION = 1
PLAN_PHASE = "qfq_nineturn_runless_event_plan"
EVENT_BACKFILL_SCOPE = "all_materializations_recent_checks"
MAX_CHECK_HISTORY = 500


class QfqNineturnEventError(RuntimeError):
    """Raised when a runless event gate fails."""


@dataclass(frozen=True, slots=True)
class QfqNineturnEventCandidate:
    asset_key: str
    partition_key: str
    event_type: str
    check_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_key": self.asset_key,
            "partition_key": self.partition_key,
            "event_type": self.event_type,
            "check_name": self.check_name,
        }


@dataclass(frozen=True, slots=True)
class QfqNineturnEventPlan:
    report_path: Path
    manifest_path: Path
    history_plan_path: Path
    history_audit_report_path: Path
    plan_fingerprint: str
    candidates: tuple[QfqNineturnEventCandidate, ...]
    partition_row_counts: Mapping[tuple[str, str], int]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    @property
    def planned_materialization_event_count(self) -> int:
        return sum(candidate.event_type == "materialization" for candidate in self.candidates)

    @property
    def planned_check_event_count(self) -> int:
        return sum(candidate.event_type == "check" for candidate in self.candidates)


@dataclass(frozen=True, slots=True)
class QfqNineturnEventReport:
    plan_fingerprint: str
    batch_id: str
    materialization_event_count: int
    check_event_count: int
    post_plan_event_count: int
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _EventAssetSpec:
    asset_key: str
    freq: int | None
    check_name: str
    observed_columns: tuple[str, ...]


def plan_qfq_nineturn_runless_events(
    *,
    instance: dg.DagsterInstance,
    history_plan_path: Path,
    history_audit_report_path: Path,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource | None = None,
    output_dir: Path = Path("/private/tmp"),
    force_materialization_refresh: bool = False,
    event_revision: str | None = None,
) -> QfqNineturnEventPlan:
    """Build an idempotent event plan without writing Dagster state."""

    if force_materialization_refresh and not (event_revision or "").strip():
        raise QfqNineturnEventError(
            "Forced materialization refresh requires a non-empty event revision."
        )
    started = time.perf_counter()
    history_plan = load_qfq_nineturn_history_plan(history_plan_path)
    if history_plan.lake_root.resolve() != Path(lake_root).resolve():
        raise QfqNineturnEventError("History plan Lake root does not match event plan.")
    history_audit = _load_history_audit(
        history_audit_report_path,
        expected_plan_fingerprint=history_plan.plan_fingerprint,
    )
    stop_reasons: list[str] = []
    if history_audit.get("should_stop"):
        stop_reasons.append("history_final_audit_failed")

    output_dir.mkdir(parents=True, exist_ok=True)
    resource = duckdb_resource or DuckDBResource()
    candidates: list[QfqNineturnEventCandidate] = []
    row_counts: dict[tuple[str, str], int] = {}
    state_fingerprint_rows: list[dict[str, object]] = []
    registered_by_partition_set = {
        cn_a_stock_trade_days.name: set(
            instance.get_dynamic_partitions(cn_a_stock_trade_days.name)
        ),
        cn_a_stock_mins_silver_trade_days.name: set(
            instance.get_dynamic_partitions(cn_a_stock_mins_silver_trade_days.name)
        ),
    }

    with resource.connect() as connection:
        for spec in _asset_specs():
            partition_keys = _history_partition_keys(history_plan, spec.asset_key)
            registered = registered_by_partition_set[_partition_set_name(spec)]
            missing_registered = tuple(sorted(set(partition_keys) - registered))
            if missing_registered:
                stop_reasons.append(f"{spec.asset_key}:missing_registered_partitions")

            target_paths = {
                partition_key: _target_path(Path(lake_root), spec, partition_key)
                for partition_key in partition_keys
            }
            missing_files = tuple(
                partition_key
                for partition_key, path in target_paths.items()
                if not path.is_file()
            )
            if missing_files:
                stop_reasons.append(f"{spec.asset_key}:missing_target_files")
            existing_paths = tuple(path for path in target_paths.values() if path.is_file())
            row_counts.update(
                {
                    (spec.asset_key, partition_key): count
                    for partition_key, count in _row_counts_by_date(
                        connection,
                        existing_paths,
                    ).items()
                }
            )

            materialization_records = _latest_materialization_records(
                instance,
                asset_key=dg.AssetKey(spec.asset_key),
                partition_keys=partition_keys,
            )
            for partition_key in partition_keys:
                record = materialization_records.get(partition_key)
                state_fingerprint_rows.append(
                    {
                        "asset_key": spec.asset_key,
                        "partition_key": partition_key,
                        "materialization_storage_id": (
                            int(record.storage_id)
                            if record is not None
                            else None
                        ),
                    }
                )
                if force_materialization_refresh or record is None:
                    candidates.append(
                        QfqNineturnEventCandidate(
                            asset_key=spec.asset_key,
                            partition_key=partition_key,
                            event_type="materialization",
                        )
                    )

            check_partition_keys = tuple(
                history_plan.latest_check_dates_by_asset.get(spec.asset_key, ())
            )
            if len(check_partition_keys) > QFQ_NINETURN_HISTORY_CHECK_WINDOW:
                stop_reasons.append(f"{spec.asset_key}:check_window_too_large")
            latest_checks = _latest_check_records(
                instance=instance,
                spec=spec,
                partition_keys=check_partition_keys,
            )
            for partition_key in check_partition_keys:
                target_path = target_paths[partition_key]
                source_paths = qfq_nineturn_source_paths_for_partition(
                    lake_root=Path(lake_root),
                    partition_key=partition_key,
                    freq=spec.freq,
                )
                diagnostics = audit_qfq_nineturn_integrity(
                    connection,
                    target_path=target_path,
                    source_paths=source_paths,
                    partition_key=partition_key,
                    freq=spec.freq,
                )
                if not diagnostics.passed:
                    stop_reasons.append(
                        f"{spec.asset_key}:{partition_key}:integrity_failed"
                    )
                materialization = materialization_records.get(partition_key)
                check_record = latest_checks.get(partition_key)
                check_state = _classify_check_record(
                    check_record,
                    materialization_storage_id=(
                        int(materialization.storage_id)
                        if materialization is not None
                        else None
                    ),
                )
                state_fingerprint_rows.append(
                    {
                        "asset_key": spec.asset_key,
                        "partition_key": partition_key,
                        "check_name": spec.check_name,
                        "check_state": check_state,
                        "check_storage_id": (
                            int(check_record.id)
                            if check_record is not None
                            and getattr(check_record, "id", None) is not None
                            else None
                        ),
                    }
                )
                if force_materialization_refresh:
                    candidates.append(
                        QfqNineturnEventCandidate(
                            asset_key=spec.asset_key,
                            partition_key=partition_key,
                            event_type="check",
                            check_name=spec.check_name,
                        )
                    )
                elif check_state == "failed_current":
                    stop_reasons.append(
                        f"{spec.asset_key}:{partition_key}:existing_failed_check"
                    )
                elif check_state != "passed_current":
                    candidates.append(
                        QfqNineturnEventCandidate(
                            asset_key=spec.asset_key,
                            partition_key=partition_key,
                            event_type="check",
                            check_name=spec.check_name,
                        )
                    )

    normalized_candidates = tuple(sorted(candidates, key=_candidate_sort_key))
    physical_fingerprint = _physical_fingerprint(
        Path(lake_root),
        history_plan=history_plan,
    )
    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "history_plan_fingerprint": history_plan.plan_fingerprint,
        "history_audit_sha256": _sha256_path(history_audit_report_path),
        "physical_fingerprint": physical_fingerprint,
        "force_materialization_refresh": force_materialization_refresh,
        "event_revision": event_revision,
        "state": state_fingerprint_rows,
        "candidates": [candidate.to_dict() for candidate in normalized_candidates],
        "stop_reasons": sorted(set(stop_reasons)),
    }
    plan_fingerprint = _hash_payload(fingerprint_payload)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    manifest_path = output_dir / f"qfq_nineturn_events_manifest_{timestamp}.jsonl"
    _write_jsonl(
        manifest_path,
        (candidate.to_dict() for candidate in normalized_candidates),
    )
    report_path = output_dir / f"qfq_nineturn_events_plan_{timestamp}.json"
    report = {
        "schema_version": SCHEMA_VERSION,
        "phase": PLAN_PHASE,
        "read_only": True,
        "history_plan_path": str(history_plan_path),
        "history_plan_fingerprint": history_plan.plan_fingerprint,
        "history_audit_report_path": str(history_audit_report_path),
        "history_audit_sha256": _sha256_path(history_audit_report_path),
        "physical_fingerprint": physical_fingerprint,
        "event_backfill_scope": EVENT_BACKFILL_SCOPE,
        "force_materialization_refresh": force_materialization_refresh,
        "event_revision": event_revision,
        "planned_materialization_event_count": sum(
            candidate.event_type == "materialization"
            for candidate in normalized_candidates
        ),
        "planned_check_event_count": sum(
            candidate.event_type == "check"
            for candidate in normalized_candidates
        ),
        "planned_event_count": len(normalized_candidates),
        "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": _sha256_path(manifest_path),
        "state_fingerprint_rows": state_fingerprint_rows,
        "partition_row_counts": [
            {
                "asset_key": asset_key,
                "partition_key": partition_key,
                "row_count": count,
            }
            for (asset_key, partition_key), count in sorted(row_counts.items())
        ],
        "should_stop": bool(stop_reasons),
        "stop_reasons": sorted(set(stop_reasons)),
        "plan_fingerprint": plan_fingerprint,
        "performance": {
            "history_materialization_partition_count": sum(
                len(_history_partition_keys(history_plan, spec.asset_key))
                for spec in _asset_specs()
            ),
            "check_window_per_asset": QFQ_NINETURN_HISTORY_CHECK_WINDOW,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }
    _write_json(report_path, report)
    return QfqNineturnEventPlan(
        report_path=report_path,
        manifest_path=manifest_path,
        history_plan_path=Path(history_plan_path),
        history_audit_report_path=Path(history_audit_report_path),
        plan_fingerprint=plan_fingerprint,
        candidates=normalized_candidates,
        partition_row_counts=row_counts,
        stop_reasons=tuple(sorted(set(stop_reasons))),
        report=report,
    )


def load_qfq_nineturn_event_plan(plan_report_path: Path) -> QfqNineturnEventPlan:
    payload = json.loads(Path(plan_report_path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise QfqNineturnEventError("Unsupported event plan schema.")
    if payload.get("phase") != PLAN_PHASE or payload.get("read_only") is not True:
        raise QfqNineturnEventError("Event report requires a read-only plan.")
    if payload.get("should_stop"):
        raise QfqNineturnEventError(
            f"Event plan has stop reasons: {payload.get('stop_reasons', [])}."
        )
    manifest_path = Path(str(payload["candidate_manifest_path"]))
    if _sha256_path(manifest_path) != str(payload["candidate_manifest_sha256"]):
        raise QfqNineturnEventError("Event candidate manifest SHA-256 mismatch.")
    candidates = tuple(
        QfqNineturnEventCandidate(
            asset_key=str(item["asset_key"]),
            partition_key=str(item["partition_key"]),
            event_type=str(item["event_type"]),
            check_name=(
                str(item["check_name"]) if item.get("check_name") is not None else None
            ),
        )
        for item in (
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    )
    row_counts = {
        (str(item["asset_key"]), str(item["partition_key"])): int(item["row_count"])
        for item in payload["partition_row_counts"]
    }
    return QfqNineturnEventPlan(
        report_path=Path(plan_report_path),
        manifest_path=manifest_path,
        history_plan_path=Path(str(payload["history_plan_path"])),
        history_audit_report_path=Path(str(payload["history_audit_report_path"])),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        candidates=candidates,
        partition_row_counts=row_counts,
        stop_reasons=(),
        report=payload,
    )


def report_qfq_nineturn_runless_events(
    *,
    instance: dg.DagsterInstance,
    plan: QfqNineturnEventPlan,
    expected_plan_fingerprint: str,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource | None = None,
    output_dir: Path = Path("/private/tmp"),
) -> QfqNineturnEventReport:
    """Append only the exact events in a fresh reviewed plan."""

    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise QfqNineturnEventError("Explicit event fingerprint does not match the plan.")
    fresh_plan = plan_qfq_nineturn_runless_events(
        instance=instance,
        history_plan_path=plan.history_plan_path,
        history_audit_report_path=plan.history_audit_report_path,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        output_dir=output_dir,
        force_materialization_refresh=bool(
            plan.report.get("force_materialization_refresh", False)
        ),
        event_revision=(
            str(plan.report["event_revision"])
            if plan.report.get("event_revision") is not None
            else None
        ),
    )
    if (
        fresh_plan.plan_fingerprint != plan.plan_fingerprint
        or fresh_plan.candidates != plan.candidates
    ):
        raise QfqNineturnEventError(
            "Runless event plan is stale; regenerate and review a new plan."
        )
    if fresh_plan.should_stop:
        raise QfqNineturnEventError(
            f"Fresh event plan failed: {fresh_plan.stop_reasons}."
        )

    started = time.perf_counter()
    batch_id = str(uuid.uuid4())
    materialization_count = 0
    check_count = 0
    candidates_by_partition = {
        (candidate.asset_key, candidate.partition_key, candidate.event_type): candidate
        for candidate in plan.candidates
    }
    history_plan = load_qfq_nineturn_history_plan(plan.history_plan_path)
    for spec in _asset_specs():
        for partition_key in _history_partition_keys(history_plan, spec.asset_key):
            materialization_candidate = candidates_by_partition.get(
                (spec.asset_key, partition_key, "materialization")
            )
            if materialization_candidate is not None:
                instance.report_runless_asset_event(
                    dg.AssetMaterialization(
                        asset_key=dg.AssetKey(spec.asset_key),
                        partition=partition_key,
                        metadata=build_materialization_metadata(
                            uri=_target_path(Path(lake_root), spec, partition_key),
                            row_count=plan.partition_row_counts[
                                (spec.asset_key, partition_key)
                            ],
                            observed_columns=spec.observed_columns,
                            extra_metadata={
                                "bootstrap_method": "qfq_nineturn_history",
                                "bootstrap_event_backfill": True,
                                "event_backfill_scope": EVENT_BACKFILL_SCOPE,
                                "bootstrap_batch_id": batch_id,
                                "history_plan_fingerprint": history_plan.plan_fingerprint,
                                "history_audit_report_path": str(
                                    plan.history_audit_report_path
                                ),
                                "check_events_reported": False,
                                "formula_version": QFQ_NINETURN_VERSION,
                                "event_revision": plan.report.get("event_revision"),
                                "canonical_rebuild_refresh": bool(
                                    plan.report.get(
                                        "force_materialization_refresh", False
                                    )
                                ),
                            },
                        ),
                    )
                )
                materialization_count += 1

            check_candidate = candidates_by_partition.get(
                (spec.asset_key, partition_key, "check")
            )
            if check_candidate is None:
                continue
            materialization = _latest_materialization_records(
                instance,
                asset_key=dg.AssetKey(spec.asset_key),
                partition_keys=(partition_key,),
            ).get(partition_key)
            if materialization is None:
                raise QfqNineturnEventError(
                    f"Missing target materialization for check: {spec.asset_key}:{partition_key}."
                )
            target = AssetCheckEvaluationTargetMaterializationData(
                storage_id=int(materialization.storage_id),
                run_id=str(materialization.run_id),
                timestamp=float(materialization.timestamp),
            )
            _report_partitioned_check_event(
                instance,
                run_id=f"qfq-nineturn-event-refresh-{batch_id}",
                evaluation=dg.AssetCheckEvaluation(
                    asset_key=dg.AssetKey(spec.asset_key),
                    check_name=spec.check_name,
                    passed=True,
                    metadata=build_check_metadata(
                        check_scope=CheckScope.RECONCILIATION,
                        checked_row_count=plan.partition_row_counts[
                            (spec.asset_key, partition_key)
                        ],
                        file_path=_target_path(Path(lake_root), spec, partition_key),
                        extra_metadata={
                            "summary": "历史九转分区聚合完整性检查通过。",
                            "next_action": "无需处理，最近窗口状态已与当前物理文件对齐。",
                            "failed_rule_names": [],
                            "bootstrap_method": "qfq_nineturn_history",
                            "bootstrap_event_backfill": True,
                            "event_backfill_scope": EVENT_BACKFILL_SCOPE,
                            "bootstrap_batch_id": batch_id,
                            "history_plan_fingerprint": history_plan.plan_fingerprint,
                            "history_audit_report_path": str(
                                plan.history_audit_report_path
                            ),
                            "event_revision": plan.report.get("event_revision"),
                            "canonical_rebuild_refresh": bool(
                                plan.report.get(
                                    "force_materialization_refresh", False
                                )
                            ),
                        },
                    ),
                    blocking=True,
                    partition=partition_key,
                    target_materialization_data=target,
                ),
            )
            check_count += 1

    post_plan = plan_qfq_nineturn_runless_events(
        instance=instance,
        history_plan_path=plan.history_plan_path,
        history_audit_report_path=plan.history_audit_report_path,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        output_dir=output_dir,
    )
    if post_plan.should_stop or post_plan.candidates:
        raise QfqNineturnEventError(
            "Runless event post-audit is not empty: "
            f"stop={post_plan.stop_reasons}, candidates={len(post_plan.candidates)}."
        )
    return QfqNineturnEventReport(
        plan_fingerprint=plan.plan_fingerprint,
        batch_id=batch_id,
        materialization_event_count=materialization_count,
        check_event_count=check_count,
        post_plan_event_count=len(post_plan.candidates),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def _asset_specs() -> tuple[_EventAssetSpec, ...]:
    return (
        _EventAssetSpec(
            asset_key="gold_stock_daily_qfq_nineturn",
            freq=None,
            check_name="gold_stock_daily_qfq_nineturn_integrity_check",
            observed_columns=tuple(
                column.name for column in GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA
            ),
        ),
        *(
            _EventAssetSpec(
                asset_key=f"gold_stk_mins_qfq_nineturn_{freq}m",
                freq=freq,
                check_name=f"gold_stk_mins_qfq_nineturn_{freq}m_integrity_check",
                observed_columns=tuple(
                    column.name for column in GOLD_STK_MINS_QFQ_NINETURN_SCHEMA
                ),
            )
            for freq in QFQ_NINETURN_MINUTE_FREQS
        ),
    )


def _report_partitioned_check_event(
    instance: dg.DagsterInstance,
    *,
    run_id: str,
    evaluation: dg.AssetCheckEvaluation,
) -> None:
    """Append a partitioned check without creating a synthetic Dagster run."""

    instance.report_dagster_event(
        run_id=run_id,
        dagster_event=DagsterEvent(
            event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
            event_specific_data=evaluation,
            job_name=RUNLESS_JOB_NAME,
        ),
    )


def _partition_set_name(spec: _EventAssetSpec) -> str:
    return (
        cn_a_stock_trade_days.name
        if spec.freq is None
        else cn_a_stock_mins_silver_trade_days.name
    )


def _history_partition_keys(
    history_plan: QfqNineturnHistoryPlan,
    asset_key: str,
) -> tuple[str, ...]:
    return tuple(
        partition_key
        for batch in history_plan.batches
        if batch.asset_key == asset_key
        for partition_key in batch.trade_dates
    )


def _target_path(lake_root: Path, spec: _EventAssetSpec, partition_key: str) -> Path:
    if spec.freq is None:
        return gold_stock_daily_qfq_nineturn_path(lake_root, partition_key)
    return gold_stk_mins_qfq_nineturn_path(lake_root, spec.freq, partition_key)


def _row_counts_by_date(
    connection,
    paths: Sequence[Path],
) -> dict[str, int]:
    if not paths:
        return {}
    path_sql = ", ".join(duckdb_string(path) for path in paths)
    rows = connection.execute(
        f"""
        SELECT CAST(trade_date AS VARCHAR), count(*)
        FROM read_parquet([{path_sql}], hive_partitioning=false, union_by_name=true)
        GROUP BY trade_date
        ORDER BY trade_date
        """
    ).fetchall()
    return {str(trade_date): int(row_count) for trade_date, row_count in rows}


def _latest_materialization_records(
    instance: dg.DagsterInstance,
    *,
    asset_key: dg.AssetKey,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    if not partition_keys:
        return {}
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key,
            asset_partitions=list(partition_keys),
        ),
        limit=len(partition_keys),
    )
    records: dict[str, object] = {}
    for record in result.records:
        partition_key = getattr(record, "partition_key", None)
        if partition_key is not None and partition_key not in records:
            records[str(partition_key)] = record
    return records


def _latest_check_records(
    *,
    instance: dg.DagsterInstance,
    spec: _EventAssetSpec,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    selected = set(partition_keys)
    records = instance.event_log_storage.get_asset_check_execution_history(
        dg.AssetCheckKey(dg.AssetKey(spec.asset_key), spec.check_name),
        limit=max(MAX_CHECK_HISTORY, len(selected) * 3),
    )
    latest: dict[str, object] = {}
    for record in records:
        partition_key = getattr(record, "partition", None)
        if partition_key in selected and partition_key not in latest:
            latest[str(partition_key)] = record
    return latest


def _classify_check_record(
    record: object | None,
    *,
    materialization_storage_id: int | None,
) -> str:
    if record is None:
        return "missing"
    event = getattr(record, "event", None)
    dagster_event = getattr(event, "dagster_event", None) if event is not None else None
    evaluation = (
        getattr(dagster_event, "event_specific_data", None)
        if dagster_event is not None
        else None
    )
    target = getattr(evaluation, "target_materialization_data", None)
    if (
        materialization_storage_id is None
        or target is None
        or int(target.storage_id) != materialization_storage_id
    ):
        return "stale"
    if (
        getattr(getattr(record, "status", None), "value", None) == "SUCCEEDED"
        and bool(getattr(evaluation, "passed", False))
        and bool(getattr(evaluation, "blocking", False))
    ):
        return "passed_current"
    return "failed_current"


def _load_history_audit(
    path: Path,
    *,
    expected_plan_fingerprint: str,
) -> Mapping[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("phase") != "qfq_nineturn_history_final_audit":
        raise QfqNineturnEventError("Runless events require a final history audit.")
    if payload.get("plan_fingerprint") != expected_plan_fingerprint:
        raise QfqNineturnEventError("History audit fingerprint does not match the plan.")
    return payload


def _physical_fingerprint(
    lake_root: Path,
    *,
    history_plan: QfqNineturnHistoryPlan,
) -> str:
    digest = hashlib.sha256()
    for spec in _asset_specs():
        for partition_key in _history_partition_keys(history_plan, spec.asset_key):
            path = _target_path(lake_root, spec, partition_key)
            if not path.is_file():
                continue
            stat = path.stat()
            relative = path.resolve().relative_to(lake_root.resolve()).as_posix()
            digest.update(f"{relative}\t{stat.st_size}\t{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def _candidate_sort_key(
    candidate: QfqNineturnEventCandidate,
) -> tuple[str, str, str, str]:
    return (
        candidate.asset_key,
        candidate.partition_key,
        candidate.event_type,
        candidate.check_name or "",
    )


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


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]] | object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
