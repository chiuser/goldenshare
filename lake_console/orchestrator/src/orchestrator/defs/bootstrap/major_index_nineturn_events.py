"""Reviewed runless events for fully audited major-index nine-turn history."""

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

from orchestrator.defs.bootstrap.major_index_nineturn_history import (
    MajorIndexNineturnHistoryPlan,
    load_major_index_nineturn_history_plan,
)
from orchestrator.defs.bootstrap.major_index_nineturn_history_audit import AUDIT_PHASE
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.partitions import (
    cn_a_index_trade_days,
    cn_major_index_mins_trade_days,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_major_index_daily_nineturn_path,
    gold_major_index_mins_nineturn_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MAJOR_INDEX_DAILY_NINETURN_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_ASSET_KEYS,
    MAJOR_INDEX_NINETURN_CHECK_NAMES,
    MAJOR_INDEX_NINETURN_HISTORY_MEMORY_LIMIT,
    MAJOR_INDEX_NINETURN_HISTORY_THREADS,
    MAJOR_INDEX_NINETURN_MINUTE_FREQS,
    MAJOR_INDEX_NINETURN_VERSION,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)

EVENT_PLAN_SCHEMA_VERSION = 1
EVENT_PLAN_PHASE = "major_index_nineturn_runless_event_plan"
EVENT_CHECKPOINT_PHASE = "major_index_nineturn_runless_event_checkpoint"
MAX_EVENT_PARTITIONS_PER_PROCESS = 1_000
_ACTIVE_RUN_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class MajorIndexNineturnEventError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MajorIndexNineturnEventCandidate:
    asset_key: str
    freq: int | None
    partition_key: str
    row_count: int
    materialization: bool
    check: bool

    @property
    def identity(self) -> str:
        return f"{self.asset_key}|{self.partition_key}"

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "freq": self.freq or "daily",
            "identity": self.identity,
        }


@dataclass(frozen=True, slots=True)
class MajorIndexNineturnEventPlan:
    report_path: Path
    manifest_path: Path
    history_plan_path: Path
    history_audit_path: Path
    plan_fingerprint: str
    physical_fingerprint: str
    candidates: tuple[MajorIndexNineturnEventCandidate, ...]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)


def plan_major_index_nineturn_events(
    *,
    instance: dg.DagsterInstance,
    history_plan_path: Path,
    history_audit_path: Path,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    output_dir: Path,
) -> MajorIndexNineturnEventPlan:
    """Read Dagster and audited physical state; write only plan reports."""

    started = time.perf_counter()
    history_plan = load_major_index_nineturn_history_plan(history_plan_path)
    root = Path(lake_root).resolve()
    if history_plan.lake_root != root:
        raise MajorIndexNineturnEventError("Event plan Lake root mismatch.")
    history_audit = _load_history_audit(
        history_audit_path,
        expected_plan_fingerprint=history_plan.plan_fingerprint,
    )
    stop_reasons: list[str] = []
    if history_audit.get("should_stop") is not False:
        stop_reasons.append("history_final_audit_failed")
    physical_fingerprint = _physical_fingerprint(history_plan)
    if physical_fingerprint != history_audit.get("physical_fingerprint"):
        stop_reasons.append("physical_fingerprint_drifted")
    active_run_count = _active_run_count(instance)
    if active_run_count:
        stop_reasons.append("active_dagster_runs")

    registered_by_set = {
        cn_a_index_trade_days.name: set(
            instance.get_dynamic_partitions(cn_a_index_trade_days.name)
        ),
        cn_major_index_mins_trade_days.name: set(
            instance.get_dynamic_partitions(cn_major_index_mins_trade_days.name)
        ),
    }
    candidates: list[MajorIndexNineturnEventCandidate] = []
    existing_materialization_count = 0
    existing_ready_check_count = 0
    for spec in _asset_specs():
        partition_keys = _partition_keys(history_plan, spec.asset_key)
        missing_registered = set(partition_keys) - registered_by_set[
            spec.partition_set_name
        ]
        if missing_registered:
            stop_reasons.append(f"{spec.asset_key}:missing_registered_partitions")
        row_counts = _partition_row_counts(history_plan, spec.asset_key)
        materializations = _latest_materializations(
            instance,
            asset_key=spec.asset_key,
            partition_keys=partition_keys,
        )
        checks = _latest_checks(
            instance,
            spec=spec,
            partition_keys=partition_keys,
        )
        existing_materialization_count += len(materializations)
        for partition_key in partition_keys:
            materialization = materializations.get(partition_key)
            check_state = _classify_check(
                checks.get(partition_key),
                materialization_storage_id=(
                    int(materialization.storage_id)
                    if materialization is not None
                    else None
                ),
            )
            if check_state == "failed_current":
                stop_reasons.append(
                    f"{spec.asset_key}:{partition_key}:existing_failed_check"
                )
            if check_state == "passed_current":
                existing_ready_check_count += 1
            needs_materialization = materialization is None
            needs_check = check_state not in {"passed_current", "failed_current"}
            if needs_materialization or needs_check:
                candidates.append(
                    MajorIndexNineturnEventCandidate(
                        asset_key=spec.asset_key,
                        freq=spec.freq,
                        partition_key=partition_key,
                        row_count=row_counts[partition_key],
                        materialization=needs_materialization,
                        check=needs_check,
                    )
                )

    normalized = tuple(sorted(candidates, key=lambda item: item.identity))
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    manifest_path = output_dir / f"major_index_nineturn_events_{timestamp}.jsonl"
    _write_jsonl(manifest_path, (candidate.to_dict() for candidate in normalized))
    fingerprint_payload = {
        "schema_version": EVENT_PLAN_SCHEMA_VERSION,
        "history_plan_fingerprint": history_plan.plan_fingerprint,
        "history_audit_sha256": _sha256_path(history_audit_path),
        "physical_fingerprint": physical_fingerprint,
        "candidate_manifest_sha256": _sha256_path(manifest_path),
        "stop_reasons": sorted(set(stop_reasons)),
    }
    plan_fingerprint = _hash_payload(fingerprint_payload)
    report_path = output_dir / f"major_index_nineturn_events_plan_{timestamp}.json"
    report: dict[str, object] = {
        **fingerprint_payload,
        "phase": EVENT_PLAN_PHASE,
        "read_only": True,
        "history_plan_path": str(Path(history_plan_path).resolve()),
        "history_audit_path": str(Path(history_audit_path).resolve()),
        "candidate_manifest_path": str(manifest_path.resolve()),
        "candidate_partition_count": len(normalized),
        "planned_materialization_event_count": sum(
            candidate.materialization for candidate in normalized
        ),
        "planned_check_event_count": sum(candidate.check for candidate in normalized),
        "planned_event_count": sum(
            candidate.materialization + candidate.check for candidate in normalized
        ),
        "existing_materialization_count": existing_materialization_count,
        "existing_ready_check_count": existing_ready_check_count,
        "active_run_count": active_run_count,
        "stop_reasons": sorted(set(stop_reasons)),
        "should_stop": bool(stop_reasons),
        "plan_fingerprint": plan_fingerprint,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    _write_json_atomic(report_path, report)
    return MajorIndexNineturnEventPlan(
        report_path=report_path,
        manifest_path=manifest_path,
        history_plan_path=Path(history_plan_path).resolve(),
        history_audit_path=Path(history_audit_path).resolve(),
        plan_fingerprint=plan_fingerprint,
        physical_fingerprint=physical_fingerprint,
        candidates=normalized,
        stop_reasons=tuple(sorted(set(stop_reasons))),
        report=report,
    )


def load_major_index_nineturn_event_plan(
    report_path: Path,
) -> MajorIndexNineturnEventPlan:
    payload = _load_json(report_path)
    if (
        payload.get("schema_version") != EVENT_PLAN_SCHEMA_VERSION
        or payload.get("phase") != EVENT_PLAN_PHASE
        or payload.get("read_only") is not True
    ):
        raise MajorIndexNineturnEventError("Event plan contract is invalid.")
    manifest_path = Path(str(payload.get("candidate_manifest_path", ""))).resolve()
    if _sha256_path(manifest_path) != payload.get("candidate_manifest_sha256"):
        raise MajorIndexNineturnEventError("Event candidate manifest drifted.")
    fingerprint_payload = {
        "schema_version": EVENT_PLAN_SCHEMA_VERSION,
        "history_plan_fingerprint": payload.get("history_plan_fingerprint"),
        "history_audit_sha256": payload.get("history_audit_sha256"),
        "physical_fingerprint": payload.get("physical_fingerprint"),
        "candidate_manifest_sha256": payload.get("candidate_manifest_sha256"),
        "stop_reasons": payload.get("stop_reasons"),
    }
    fingerprint = _hash_payload(fingerprint_payload)
    if payload.get("plan_fingerprint") != fingerprint:
        raise MajorIndexNineturnEventError("Event plan fingerprint drifted.")
    candidates = tuple(
        _candidate_from_dict(json.loads(line))
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return MajorIndexNineturnEventPlan(
        report_path=Path(report_path).resolve(),
        manifest_path=manifest_path,
        history_plan_path=Path(str(payload["history_plan_path"])).resolve(),
        history_audit_path=Path(str(payload["history_audit_path"])).resolve(),
        plan_fingerprint=fingerprint,
        physical_fingerprint=str(payload["physical_fingerprint"]),
        candidates=candidates,
        stop_reasons=tuple(str(value) for value in payload.get("stop_reasons", ())),
        report=payload,
    )


def report_major_index_nineturn_events(
    *,
    instance: dg.DagsterInstance,
    plan: MajorIndexNineturnEventPlan,
    expected_plan_fingerprint: str,
    checkpoint_path: Path,
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    partition_limit: int = 1,
    sample_identity: str | None = None,
) -> Mapping[str, object]:
    """Report one explicit sample or one bounded partition group."""

    if plan.should_stop or plan.plan_fingerprint != expected_plan_fingerprint:
        raise MajorIndexNineturnEventError("Event plan stopped or fingerprint mismatched.")
    if not 1 <= partition_limit <= MAX_EVENT_PARTITIONS_PER_PROCESS:
        raise MajorIndexNineturnEventError("Event partition limit is outside 1..1000.")
    _validate_event_inputs(plan=plan, instance=instance, lake_root=Path(lake_root))
    normalized_checkpoint = Path(checkpoint_path).resolve()
    if not normalized_checkpoint.is_relative_to(Path(staging_root).resolve()):
        raise MajorIndexNineturnEventError("Event checkpoint must be below staging.")
    completed = _load_event_checkpoint(
        normalized_checkpoint,
        expected_plan_fingerprint=expected_plan_fingerprint,
    )
    _validate_completed_candidate_identities(plan=plan, completed=completed)
    pending = tuple(
        candidate for candidate in plan.candidates if candidate.identity not in completed
    )
    if sample_identity is not None:
        selected = tuple(
            candidate for candidate in pending if candidate.identity == sample_identity
        )
        if len(selected) != 1:
            raise MajorIndexNineturnEventError(
                "Sample identity must select exactly one pending partition."
            )
    else:
        selected = pending[:partition_limit]
    started = time.perf_counter()
    reported_materializations = 0
    reported_checks = 0
    skipped_materializations = 0
    skipped_checks = 0
    batch_id = str(uuid.uuid4())

    selected_by_asset = _group_candidates(selected)
    materializations_by_asset: dict[str, dict[str, object]] = {}
    for asset_key, asset_candidates in selected_by_asset.items():
        partition_keys = tuple(item.partition_key for item in asset_candidates)
        materializations = _latest_materializations(
            instance, asset_key=asset_key, partition_keys=partition_keys
        )
        for candidate in asset_candidates:
            if not candidate.materialization:
                continue
            if candidate.partition_key in materializations:
                skipped_materializations += 1
                continue
            _report_materialization(
                instance=instance,
                plan=plan,
                candidate=candidate,
                lake_root=Path(lake_root).resolve(),
                batch_id=batch_id,
            )
            reported_materializations += 1
        materializations_by_asset[asset_key] = _latest_materializations(
            instance, asset_key=asset_key, partition_keys=partition_keys
        )

    for asset_key, asset_candidates in selected_by_asset.items():
        spec = _spec_by_asset_key(asset_key)
        partition_keys = tuple(item.partition_key for item in asset_candidates)
        current_checks = _latest_checks(
            instance, spec=spec, partition_keys=partition_keys
        )
        for candidate in asset_candidates:
            if not candidate.check:
                continue
            materialization = materializations_by_asset[asset_key].get(
                candidate.partition_key
            )
            if materialization is None:
                raise MajorIndexNineturnEventError(
                    f"Materialization missing before check: {candidate.identity}."
                )
            if (
                _classify_check(
                    current_checks.get(candidate.partition_key),
                    materialization_storage_id=int(materialization.storage_id),
                )
                == "passed_current"
            ):
                skipped_checks += 1
                continue
            _report_check(
                instance=instance,
                plan=plan,
                candidate=candidate,
                materialization=materialization,
                lake_root=Path(lake_root).resolve(),
                batch_id=batch_id,
            )
            reported_checks += 1

    for candidate in selected:
        completed.add(candidate.identity)
    _write_event_checkpoint(
        normalized_checkpoint,
        plan_fingerprint=expected_plan_fingerprint,
        completed=completed,
    )
    return {
        "plan_fingerprint": expected_plan_fingerprint,
        "selected_partition_count": len(selected),
        "reported_materialization_event_count": reported_materializations,
        "reported_check_event_count": reported_checks,
        "skipped_materialization_event_count": skipped_materializations,
        "skipped_check_event_count": skipped_checks,
        "completed_partition_count": len(completed),
        "remaining_partition_count": len(plan.candidates) - len(completed),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def post_audit_major_index_nineturn_events(
    *,
    instance: dg.DagsterInstance,
    plan: MajorIndexNineturnEventPlan,
    checkpoint_path: Path,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> Mapping[str, object]:
    _validate_event_inputs(plan=plan, instance=instance, lake_root=Path(lake_root))
    completed = _load_event_checkpoint(
        Path(checkpoint_path), expected_plan_fingerprint=plan.plan_fingerprint
    )
    _validate_completed_candidate_identities(plan=plan, completed=completed)
    missing_materializations = 0
    missing_ready_checks = 0
    history_plan = load_major_index_nineturn_history_plan(plan.history_plan_path)
    for spec in _asset_specs():
        partition_keys = _partition_keys(history_plan, spec.asset_key)
        materializations = _latest_materializations(
            instance, asset_key=spec.asset_key, partition_keys=partition_keys
        )
        checks = _latest_checks(instance, spec=spec, partition_keys=partition_keys)
        for partition_key in partition_keys:
            materialization = materializations.get(partition_key)
            if materialization is None:
                missing_materializations += 1
                continue
            if (
                _classify_check(
                    checks.get(partition_key),
                    materialization_storage_id=int(materialization.storage_id),
                )
                != "passed_current"
            ):
                missing_ready_checks += 1
    should_stop = (
        len(completed) != len(plan.candidates)
        or missing_materializations > 0
        or missing_ready_checks > 0
    )
    return {
        "plan_fingerprint": plan.plan_fingerprint,
        "planned_partition_count": len(plan.candidates),
        "completed_partition_count": len(completed),
        "missing_materialization_count": missing_materializations,
        "missing_ready_check_count": missing_ready_checks,
        "should_stop": should_stop,
    }


@dataclass(frozen=True, slots=True)
class _EventAssetSpec:
    asset_key: str
    freq: int | None
    check_name: str
    partition_set_name: str
    observed_columns: tuple[str, ...]


def _asset_specs() -> tuple[_EventAssetSpec, ...]:
    daily_columns = tuple(
        column.name for column in GOLD_MAJOR_INDEX_DAILY_NINETURN_SCHEMA
    )
    minute_columns = tuple(
        column.name for column in GOLD_MAJOR_INDEX_MINS_NINETURN_SCHEMA
    )
    return (
        _EventAssetSpec(
            MAJOR_INDEX_NINETURN_ASSET_KEYS[0],
            None,
            MAJOR_INDEX_NINETURN_CHECK_NAMES[0],
            cn_a_index_trade_days.name,
            daily_columns,
        ),
        *tuple(
            _EventAssetSpec(
                asset_key,
                freq,
                check_name,
                cn_major_index_mins_trade_days.name,
                minute_columns,
            )
            for asset_key, freq, check_name in zip(
                MAJOR_INDEX_NINETURN_ASSET_KEYS[1:],
                MAJOR_INDEX_NINETURN_MINUTE_FREQS,
                MAJOR_INDEX_NINETURN_CHECK_NAMES[1:],
                strict=True,
            )
        ),
    )


def _spec_by_asset_key(asset_key: str) -> _EventAssetSpec:
    return next(spec for spec in _asset_specs() if spec.asset_key == asset_key)


def _partition_keys(
    history_plan: MajorIndexNineturnHistoryPlan, asset_key: str
) -> tuple[str, ...]:
    return tuple(
        trade_date
        for batch in history_plan.batches
        if batch.asset_key == asset_key
        for trade_date in batch.trade_dates
    )


def _partition_row_counts(
    history_plan: MajorIndexNineturnHistoryPlan, asset_key: str
) -> dict[str, int]:
    result: dict[str, int] = {}
    settings = DuckDBConnectionSettings(
        memory_limit=MAJOR_INDEX_NINETURN_HISTORY_MEMORY_LIMIT,
        threads=MAJOR_INDEX_NINETURN_HISTORY_THREADS,
        preserve_insertion_order=False,
    )
    for batch in history_plan.batches:
        if batch.asset_key != asset_key:
            continue
        paths = tuple(
            _target_path(history_plan.lake_root, batch.freq, trade_date)
            for trade_date in batch.trade_dates
        )
        values = ", ".join(duckdb_string(path) for path in paths)
        with connect_configured_duckdb(settings) as connection:
            rows = connection.execute(
                f"SELECT file_name, num_rows FROM parquet_file_metadata([{values}])"
            ).fetchall()
        for file_name, row_count in rows:
            partition_key = Path(str(file_name)).parent.name.removeprefix("trade_date=")
            result[partition_key] = int(row_count)
    expected = set(_partition_keys(history_plan, asset_key))
    if set(result) != expected:
        raise MajorIndexNineturnEventError(
            f"Event row-count manifest differs from history plan: {asset_key}."
        )
    return result


def _latest_materializations(
    instance: dg.DagsterInstance, *, asset_key: str, partition_keys: Sequence[str]
) -> dict[str, object]:
    if not partition_keys:
        return {}
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key), asset_partitions=list(partition_keys)
        ),
        limit=len(partition_keys),
    ).records
    result: dict[str, object] = {}
    for record in records:
        partition_key = getattr(record, "partition_key", None)
        if partition_key is not None and str(partition_key) not in result:
            result[str(partition_key)] = record
    return result


def _latest_checks(
    instance: dg.DagsterInstance,
    *,
    spec: _EventAssetSpec,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    selected = set(partition_keys)
    if not selected:
        return {}
    records = instance.event_log_storage.get_asset_check_execution_history(
        dg.AssetCheckKey(dg.AssetKey(spec.asset_key), spec.check_name),
        limit=max(500, len(selected) * 2),
    )
    result: dict[str, object] = {}
    for record in records:
        partition_key = getattr(record, "partition", None)
        if partition_key in selected and str(partition_key) not in result:
            result[str(partition_key)] = record
    return result


def _classify_check(
    record: object | None, *, materialization_storage_id: int | None
) -> str:
    if record is None:
        return "missing"
    event = getattr(record, "event", None)
    dagster_event = getattr(event, "dagster_event", None) if event else None
    evaluation = getattr(dagster_event, "event_specific_data", None)
    target = getattr(evaluation, "target_materialization_data", None)
    if (
        materialization_storage_id is None
        or target is None
        or int(target.storage_id) != materialization_storage_id
    ):
        return "stale"
    if bool(getattr(evaluation, "passed", False)) and bool(
        getattr(evaluation, "blocking", False)
    ):
        return "passed_current"
    return "failed_current"


def _report_materialization(
    *, instance, plan, candidate, lake_root: Path, batch_id: str
) -> None:
    spec = _spec_by_asset_key(candidate.asset_key)
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=dg.AssetKey(candidate.asset_key),
            partition=candidate.partition_key,
            metadata=build_materialization_metadata(
                uri=_target_path(lake_root, candidate.freq, candidate.partition_key),
                row_count=candidate.row_count,
                observed_columns=spec.observed_columns,
                extra_metadata={
                    "bootstrap_method": "major_index_nineturn_history",
                    "bootstrap_event_backfill": True,
                    "bootstrap_batch_id": batch_id,
                    "history_plan_fingerprint": plan.report[
                        "history_plan_fingerprint"
                    ],
                    "history_audit_path": str(plan.history_audit_path),
                    "formula_version": MAJOR_INDEX_NINETURN_VERSION,
                },
            ),
        )
    )


def _report_check(
    *, instance, plan, candidate, materialization, lake_root: Path, batch_id: str
) -> None:
    spec = _spec_by_asset_key(candidate.asset_key)
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=int(materialization.storage_id),
        run_id=str(materialization.run_id),
        timestamp=float(materialization.timestamp),
    )
    evaluation = dg.AssetCheckEvaluation(
        asset_key=dg.AssetKey(candidate.asset_key),
        check_name=spec.check_name,
        passed=True,
        blocking=True,
        partition=candidate.partition_key,
        target_materialization_data=target,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=candidate.row_count,
            failed_row_count=0,
            file_path=_target_path(
                lake_root, candidate.freq, candidate.partition_key
            ),
            extra_metadata={
                "summary": "主要指数九转历史分区完整性检查通过。",
                "next_action": "无需处理。",
                "failed_rule_names": [],
                "bootstrap_method": "major_index_nineturn_history",
                "bootstrap_event_backfill": True,
                "bootstrap_batch_id": batch_id,
                "history_plan_fingerprint": plan.report[
                    "history_plan_fingerprint"
                ],
                "history_audit_path": str(plan.history_audit_path),
                "formula_version": MAJOR_INDEX_NINETURN_VERSION,
            },
        ),
    )
    instance.report_dagster_event(
        run_id=f"major-index-nineturn-event-{batch_id}",
        dagster_event=DagsterEvent(
            event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
            event_specific_data=evaluation,
            job_name=RUNLESS_JOB_NAME,
        ),
    )


def _validate_event_inputs(*, plan, instance, lake_root: Path) -> None:
    if _active_run_count(instance):
        raise MajorIndexNineturnEventError("Event write blocked by an active Dagster run.")
    if _sha256_path(plan.history_audit_path) != plan.report["history_audit_sha256"]:
        raise MajorIndexNineturnEventError("History audit report drifted.")
    history_plan = load_major_index_nineturn_history_plan(plan.history_plan_path)
    if history_plan.lake_root != lake_root.resolve():
        raise MajorIndexNineturnEventError("Event apply Lake root mismatch.")
    if _physical_fingerprint(history_plan) != plan.physical_fingerprint:
        raise MajorIndexNineturnEventError("Physical target fingerprint drifted.")


def _active_run_count(instance: dg.DagsterInstance) -> int:
    return len(
        instance.get_runs(
            filters=dg.RunsFilter(statuses=list(_ACTIVE_RUN_STATUSES)), limit=1
        )
    )


def _group_candidates(candidates):
    result: dict[str, list[MajorIndexNineturnEventCandidate]] = {}
    for candidate in candidates:
        result.setdefault(candidate.asset_key, []).append(candidate)
    return {key: tuple(value) for key, value in result.items()}


def _target_path(lake_root: Path, freq: int | None, partition_key: str) -> Path:
    return (
        gold_major_index_daily_nineturn_path(lake_root, partition_key)
        if freq is None
        else gold_major_index_mins_nineturn_path(lake_root, freq, partition_key)
    )


def _physical_fingerprint(plan: MajorIndexNineturnHistoryPlan) -> str:
    digest = hashlib.sha256()
    for batch in plan.batches:
        for partition_key in batch.trade_dates:
            path = _target_path(plan.lake_root, batch.freq, partition_key)
            if path.is_file():
                stat = path.stat()
                relative = path.resolve().relative_to(plan.lake_root).as_posix()
                digest.update(
                    f"{relative}\t{stat.st_size}\t{stat.st_mtime_ns}\n".encode()
                )
    return digest.hexdigest()


def _load_history_audit(path: Path, *, expected_plan_fingerprint: str):
    payload = _load_json(path)
    if (
        payload.get("phase") != AUDIT_PHASE
        or payload.get("plan_fingerprint") != expected_plan_fingerprint
    ):
        raise MajorIndexNineturnEventError("History final audit contract is invalid.")
    return payload


def _candidate_from_dict(value: Mapping[str, object]):
    raw_freq = value.get("freq")
    return MajorIndexNineturnEventCandidate(
        asset_key=str(value["asset_key"]),
        freq=None if raw_freq == "daily" else int(str(raw_freq)),
        partition_key=str(value["partition_key"]),
        row_count=int(value["row_count"]),
        materialization=bool(value["materialization"]),
        check=bool(value["check"]),
    )


def _load_event_checkpoint(path: Path, *, expected_plan_fingerprint: str) -> set[str]:
    if not path.is_file():
        return set()
    payload = _load_json(path)
    if (
        payload.get("phase") != EVENT_CHECKPOINT_PHASE
        or payload.get("plan_fingerprint") != expected_plan_fingerprint
        or not isinstance(payload.get("completed"), list)
    ):
        raise MajorIndexNineturnEventError("Event checkpoint contract is invalid.")
    return {str(value) for value in payload["completed"]}


def _validate_completed_candidate_identities(
    *, plan: MajorIndexNineturnEventPlan, completed: set[str]
) -> None:
    expected = {candidate.identity for candidate in plan.candidates}
    unknown = tuple(sorted(completed - expected))
    if unknown:
        raise MajorIndexNineturnEventError(
            "Event checkpoint contains candidates outside the reviewed plan: "
            f"{unknown[:20]}."
        )


def _write_event_checkpoint(path: Path, *, plan_fingerprint: str, completed: set[str]):
    _write_json_atomic(
        path,
        {
            "schema_version": EVENT_PLAN_SCHEMA_VERSION,
            "phase": EVENT_CHECKPOINT_PHASE,
            "plan_fingerprint": plan_fingerprint,
            "completed": sorted(completed),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _load_json(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MajorIndexNineturnEventError(f"Unreadable JSON report: {path}.") from error
    if not isinstance(payload, Mapping):
        raise MajorIndexNineturnEventError("JSON report must be an object.")
    return payload


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


__all__ = [
    "MajorIndexNineturnEventError",
    "MajorIndexNineturnEventPlan",
    "load_major_index_nineturn_event_plan",
    "plan_major_index_nineturn_events",
    "post_audit_major_index_nineturn_events",
    "report_major_index_nineturn_events",
]
