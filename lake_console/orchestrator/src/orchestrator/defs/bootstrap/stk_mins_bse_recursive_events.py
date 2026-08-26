"""Scoped control-plane refresh for recovered BSE recursive minute assets."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.events import DagsterEvent, DagsterEventType
from dagster._core.instance.utils import RUNLESS_JOB_NAME

from orchestrator.defs.bootstrap.cn_a_minute_gold_p9_events import (
    audit_stock_indicator_state_partitions,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_nineturn_path,
)
from orchestrator.defs.qfq_nineturn_integrity import (
    audit_qfq_nineturn_integrity,
    qfq_nineturn_integrity_rule_names,
    qfq_nineturn_source_paths_for_partition,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)

RECURSIVE_EVENT_REFRESH_REVISION = "stk_mins_bse_recursive_event_refresh_v1"
RECURSIVE_EVENT_REFRESH_STAGE = "stk_mins_bse_recursive_event_refresh_plan"
RECURSIVE_EVENT_REFRESH_WINDOW = 20
RECURSIVE_EVENT_REFRESH_MAX_EVENTS = 1_000
RECURSIVE_EVENT_REFRESH_FREQUENCIES = (1, 5, 15, 30, 60, 90, 120)
RECURSIVE_EVENT_REFRESH_NINETURN_FREQUENCIES = (30, 60, 90, 120)
_ACTIVE_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class BseRecursiveEventRefreshError(RuntimeError):
    """Raised before an unsafe recursive event refresh."""


@dataclass(frozen=True, slots=True)
class RecursiveEventRefreshAssetSpec:
    asset_family: str
    asset_key: str
    freq: int
    partition_keys: tuple[str, ...]
    check_names: tuple[str, ...]
    row_count_by_partition: Mapping[str, int]

    @property
    def planned_materialization_count(self) -> int:
        return len(self.partition_keys)

    @property
    def planned_check_count(self) -> int:
        return len(self.partition_keys) * len(self.check_names)

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_family": self.asset_family,
            "asset_key": self.asset_key,
            "freq": self.freq,
            "partition_keys": list(self.partition_keys),
            "partition_count": len(self.partition_keys),
            "check_names": list(self.check_names),
            "row_count_by_partition": dict(self.row_count_by_partition),
        }


@dataclass(frozen=True, slots=True)
class RecursiveEventRefreshPlan:
    plan_hash: str
    lake_root: Path
    manifest_paths: tuple[Path, ...]
    manifest_evidence: tuple[Mapping[str, object], ...]
    target_fingerprint_hash: str
    target_file_count: int
    assets: tuple[RecursiveEventRefreshAssetSpec, ...]
    check_results: Mapping[str, tuple[dg.AssetCheckResult, ...]]
    active_run_count: int
    missing_registered_partitions: tuple[str, ...]
    failed_check_items: tuple[str, ...]
    elapsed_ms: float

    @property
    def planned_materialization_count(self) -> int:
        return sum(asset.planned_materialization_count for asset in self.assets)

    @property
    def planned_check_count(self) -> int:
        return sum(asset.planned_check_count for asset in self.assets)

    @property
    def planned_event_count(self) -> int:
        return self.planned_materialization_count + self.planned_check_count

    @property
    def should_stop(self) -> bool:
        return bool(
            self.active_run_count
            or self.missing_registered_partitions
            or self.failed_check_items
            or self.planned_event_count > RECURSIVE_EVENT_REFRESH_MAX_EVENTS
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "stage": RECURSIVE_EVENT_REFRESH_STAGE,
            "revision": RECURSIVE_EVENT_REFRESH_REVISION,
            "plan_hash": self.plan_hash,
            "lake_root": str(self.lake_root),
            "manifest_paths": [str(path) for path in self.manifest_paths],
            "manifest_evidence": [dict(value) for value in self.manifest_evidence],
            "target_fingerprint_hash": self.target_fingerprint_hash,
            "target_file_count": self.target_file_count,
            "assets": [asset.to_dict() for asset in self.assets],
            "asset_count": len(self.assets),
            "planned_materialization_count": self.planned_materialization_count,
            "planned_check_count": self.planned_check_count,
            "planned_event_count": self.planned_event_count,
            "active_run_count": self.active_run_count,
            "missing_registered_partitions": list(
                self.missing_registered_partitions
            ),
            "failed_check_items": list(self.failed_check_items),
            "should_stop": self.should_stop,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


@dataclass(frozen=True, slots=True)
class RecursiveEventRefreshReport:
    mode: str
    plan_hash: str
    reported_materialization_count: int = 0
    reported_check_count: int = 0
    skipped_materialization_count: int = 0
    skipped_check_count: int = 0
    completed_item_count: int = 0
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": self.mode,
            "revision": RECURSIVE_EVENT_REFRESH_REVISION,
            "plan_hash": self.plan_hash,
            "reported_materialization_count": self.reported_materialization_count,
            "reported_check_count": self.reported_check_count,
            "reported_event_count": (
                self.reported_materialization_count + self.reported_check_count
            ),
            "skipped_materialization_count": self.skipped_materialization_count,
            "skipped_check_count": self.skipped_check_count,
            "completed_item_count": self.completed_item_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


StockAuditBuilder = Callable[
    [Path, int, Sequence[str]], Mapping[str, tuple[dg.AssetCheckResult, ...]]
]
NineturnAuditBuilder = Callable[
    [Path, DuckDBResource, int, str], dg.AssetCheckResult
]


def plan_bse_recursive_event_refresh(
    *,
    instance: Any,
    manifest_paths: Sequence[Path],
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource | None = None,
    stock_audit_builder: StockAuditBuilder | None = None,
    nineturn_audit_builder: NineturnAuditBuilder | None = None,
) -> RecursiveEventRefreshPlan:
    """Build a bounded, read-only plan from promoted recursive manifests."""

    started = perf_counter()
    normalized_manifests = tuple(Path(path) for path in manifest_paths)
    if not normalized_manifests:
        raise BseRecursiveEventRefreshError(
            "At least one recursive changed manifest is required."
        )
    if len(set(normalized_manifests)) != len(normalized_manifests):
        raise BseRecursiveEventRefreshError(
            "Recursive changed manifest selection contains duplicates."
        )

    manifests = tuple(_load_recursive_manifest(path) for path in normalized_manifests)
    manifest_evidence = tuple(
        {
            "path": str(path),
            "sha256": _sha256_file(path),
            "manifest_hash": str(payload["manifest_hash"]),
            "plan_hash": str(payload["plan_hash"]),
        }
        for path, payload in zip(normalized_manifests, manifests, strict=True)
    )
    scope, target_paths = _event_scope(manifests)
    target_fingerprints = _target_fingerprints(target_paths)
    target_fingerprint_hash = _hash_payload(target_fingerprints)

    selected_dates = tuple(
        sorted({value for dates in scope.values() for value in dates})
    )
    if len(selected_dates) > RECURSIVE_EVENT_REFRESH_WINDOW:
        raise BseRecursiveEventRefreshError(
            "Recursive event refresh exceeds the reviewed recent 20 window."
        )
    registered = {
        _normalize_trade_date(value)
        for value in instance.get_dynamic_partitions(
            cn_a_stock_mins_silver_trade_days.name
        )
    }
    reviewed_window = set(
        sorted(registered)[-RECURSIVE_EVENT_REFRESH_WINDOW:]
    )
    missing_registered = tuple(sorted(set(selected_dates) - registered))
    outside_reviewed_window = tuple(
        sorted(set(selected_dates) - reviewed_window - set(missing_registered))
    )
    if outside_reviewed_window:
        raise BseRecursiveEventRefreshError(
            "Recursive event refresh contains dates outside the latest 20 "
            f"registered partitions: {outside_reviewed_window[:10]}"
        )
    active_run_count = _active_run_count(instance)

    stock_builder = stock_audit_builder or _build_stock_audits
    nineturn_builder = nineturn_audit_builder or _build_nineturn_audit
    check_results: dict[str, tuple[dg.AssetCheckResult, ...]] = {}
    for freq in RECURSIVE_EVENT_REFRESH_FREQUENCIES:
        dates = tuple(
            sorted(
                set(scope.get(("macd_kdj", freq), ()))
                | set(scope.get(("macd_kdj_state", freq), ()))
            )
        )
        if dates:
            check_results.update(stock_builder(Path(lake_root), freq, dates))
    resource = duckdb_resource or DuckDBResource()
    for (family, freq), dates in sorted(scope.items()):
        if family != "nineturn":
            continue
        for partition_key in dates:
            asset_key = f"gold_stk_mins_qfq_nineturn_{freq}m"
            check_results[f"{asset_key}|{partition_key}"] = (
                nineturn_builder(Path(lake_root), resource, freq, partition_key),
            )

    assets = _asset_specs(scope, check_results, Path(lake_root))
    failed_checks = tuple(
        sorted(
            f"{item}|{index}"
            for item, results in check_results.items()
            for index, result in enumerate(results)
            if not result.passed
        )
    )
    plan_identity = {
        "revision": RECURSIVE_EVENT_REFRESH_REVISION,
        "lake_root": str(Path(lake_root).resolve()),
        "manifest_evidence": manifest_evidence,
        "target_fingerprint_hash": target_fingerprint_hash,
        "target_file_count": len(target_fingerprints),
        "assets": [asset.to_dict() for asset in assets],
        "check_passed": {
            key: [bool(result.passed) for result in results]
            for key, results in sorted(check_results.items())
        },
        "active_run_count": active_run_count,
        "missing_registered_partitions": missing_registered,
    }
    return RecursiveEventRefreshPlan(
        plan_hash=_hash_payload(plan_identity),
        lake_root=Path(lake_root).resolve(),
        manifest_paths=normalized_manifests,
        manifest_evidence=manifest_evidence,
        target_fingerprint_hash=target_fingerprint_hash,
        target_file_count=len(target_fingerprints),
        assets=assets,
        check_results=check_results,
        active_run_count=active_run_count,
        missing_registered_partitions=missing_registered,
        failed_check_items=failed_checks,
        elapsed_ms=(perf_counter() - started) * 1_000,
    )


def apply_bse_recursive_event_refresh(
    *,
    instance: Any,
    reviewed_plan: RecursiveEventRefreshPlan,
    expected_plan_hash: str,
    checkpoint_path: Path,
) -> RecursiveEventRefreshReport:
    """Append only the reviewed recent-window materialization and check events."""

    if reviewed_plan.plan_hash != expected_plan_hash:
        raise BseRecursiveEventRefreshError(
            "Explicit event plan hash does not match the reviewed plan."
        )
    if reviewed_plan.should_stop:
        raise BseRecursiveEventRefreshError(
            "Recursive event refresh is blocked by the reviewed plan."
        )
    started = perf_counter()
    completed = _load_checkpoint(checkpoint_path, plan_hash=reviewed_plan.plan_hash)
    reported_materializations = 0
    skipped_materializations = 0
    reported_checks = 0
    skipped_checks = 0

    for spec in reviewed_plan.assets:
        for partition_key in spec.partition_keys:
            identity = f"materialization|{spec.asset_key}|{partition_key}"
            existing = _latest_materialization_for_refresh(
                instance,
                asset_key=spec.asset_key,
                partition_key=partition_key,
                plan_hash=reviewed_plan.plan_hash,
            )
            if identity in completed or existing is not None:
                skipped_materializations += 1
            else:
                _report_materialization(
                    instance,
                    plan=reviewed_plan,
                    spec=spec,
                    partition_key=partition_key,
                )
                reported_materializations += 1
            completed.add(identity)
            _write_checkpoint(
                checkpoint_path,
                plan_hash=reviewed_plan.plan_hash,
                completed=completed,
            )

    batch_run_id = f"stk-mins-bse-event-refresh-{uuid.uuid4()}"
    for spec in reviewed_plan.assets:
        materializations = _materializations_by_partition(
            instance,
            asset_key=spec.asset_key,
            partitions=spec.partition_keys,
        )
        if set(materializations) != set(spec.partition_keys):
            missing = sorted(set(spec.partition_keys) - set(materializations))
            raise BseRecursiveEventRefreshError(
                f"Missing refreshed materializations: {spec.asset_key}:{missing[:10]}"
            )
        for check_index, check_name in enumerate(spec.check_names):
            ready = _ready_check_partitions(
                instance,
                asset_key=spec.asset_key,
                check_name=check_name,
                materializations=materializations,
            )
            for partition_key in spec.partition_keys:
                identity = f"check|{spec.asset_key}|{check_name}|{partition_key}"
                if identity in completed or partition_key in ready:
                    skipped_checks += 1
                else:
                    result = reviewed_plan.check_results[
                        f"{spec.asset_key}|{partition_key}"
                    ][check_index]
                    _report_check(
                        instance,
                        run_id=batch_run_id,
                        plan=reviewed_plan,
                        spec=spec,
                        partition_key=partition_key,
                        check_name=check_name,
                        result=result,
                        materialization=materializations[partition_key],
                    )
                    reported_checks += 1
                completed.add(identity)
                _write_checkpoint(
                    checkpoint_path,
                    plan_hash=reviewed_plan.plan_hash,
                    completed=completed,
                )

    return RecursiveEventRefreshReport(
        mode="apply",
        plan_hash=reviewed_plan.plan_hash,
        reported_materialization_count=reported_materializations,
        reported_check_count=reported_checks,
        skipped_materialization_count=skipped_materializations,
        skipped_check_count=skipped_checks,
        completed_item_count=len(completed),
        elapsed_ms=(perf_counter() - started) * 1_000,
    )


def post_audit_bse_recursive_event_refresh(
    *, instance: Any, plan: RecursiveEventRefreshPlan
) -> RecursiveEventRefreshReport:
    """Verify latest materializations and blocking checks for the reviewed scope."""

    if plan.should_stop:
        raise BseRecursiveEventRefreshError("Post-audit plan is not green.")
    started = perf_counter()
    for spec in plan.assets:
        materializations = _materializations_by_partition(
            instance,
            asset_key=spec.asset_key,
            partitions=spec.partition_keys,
        )
        if set(materializations) != set(spec.partition_keys):
            raise BseRecursiveEventRefreshError(
                f"Post-audit materializations are incomplete: {spec.asset_key}"
            )
        for partition_key, record in materializations.items():
            metadata = record.asset_materialization.metadata
            if (
                _metadata_value(metadata, "goldenshare/event_revision")
                != RECURSIVE_EVENT_REFRESH_REVISION
                or _metadata_value(metadata, "goldenshare/event_plan_hash")
                != plan.plan_hash
            ):
                raise BseRecursiveEventRefreshError(
                    f"Post-audit latest materialization is stale: "
                    f"{spec.asset_key}:{partition_key}"
                )
        for check_name in spec.check_names:
            ready = _ready_check_partitions(
                instance,
                asset_key=spec.asset_key,
                check_name=check_name,
                materializations=materializations,
            )
            missing = sorted(set(spec.partition_keys) - ready)
            if missing:
                raise BseRecursiveEventRefreshError(
                    f"Post-audit checks are incomplete: "
                    f"{spec.asset_key}:{check_name}:{missing[:10]}"
                )
    return RecursiveEventRefreshReport(
        mode="post-audit",
        plan_hash=plan.plan_hash,
        completed_item_count=plan.planned_event_count,
        elapsed_ms=(perf_counter() - started) * 1_000,
    )


def write_recursive_event_refresh_report(
    report: RecursiveEventRefreshPlan | RecursiveEventRefreshReport, path: Path
) -> None:
    _atomic_write_json(path, report.to_dict())


def load_recursive_event_refresh_plan_inputs(path: Path) -> tuple[tuple[Path, ...], str]:
    payload = _read_json(path)
    if payload.get("stage") != RECURSIVE_EVENT_REFRESH_STAGE:
        raise BseRecursiveEventRefreshError("Unexpected recursive event plan stage.")
    if payload.get("revision") != RECURSIVE_EVENT_REFRESH_REVISION:
        raise BseRecursiveEventRefreshError("Recursive event plan revision mismatch.")
    manifest_paths = payload.get("manifest_paths")
    if not isinstance(manifest_paths, list) or not manifest_paths:
        raise BseRecursiveEventRefreshError("Recursive event plan manifests are missing.")
    plan_hash = str(payload.get("plan_hash") or "")
    if not plan_hash:
        raise BseRecursiveEventRefreshError("Recursive event plan hash is missing.")
    return tuple(Path(str(value)) for value in manifest_paths), plan_hash


def _build_stock_audits(
    lake_root: Path, freq: int, dates: Sequence[str]
) -> Mapping[str, tuple[dg.AssetCheckResult, ...]]:
    return audit_stock_indicator_state_partitions(
        lake_root=lake_root,
        freq=freq,
        dates=dates,
    )


def _build_nineturn_audit(
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    freq: int,
    partition_key: str,
) -> dg.AssetCheckResult:
    target_path = gold_stk_mins_qfq_nineturn_path(lake_root, freq, partition_key)
    source_paths = qfq_nineturn_source_paths_for_partition(
        lake_root=lake_root,
        partition_key=partition_key,
        freq=freq,
    )
    with duckdb_resource.connect() as connection:
        diagnostics = audit_qfq_nineturn_integrity(
            connection,
            target_path=target_path,
            source_paths=source_paths,
            partition_key=partition_key,
            freq=freq,
        )
    return dg.AssetCheckResult(
        passed=diagnostics.passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=diagnostics.checked_row_count,
            failed_row_count=diagnostics.failed_row_count,
            file_path=target_path,
            extra_metadata={
                "rule_names": list(qfq_nineturn_integrity_rule_names(freq=freq)),
                "failed_rule_names": list(diagnostics.failed_rule_names),
                "failure_samples": list(diagnostics.failure_samples),
                "reason_code": "ready" if diagnostics.passed else "integrity_failed",
            },
        ),
    )


def _event_scope(
    manifests: Sequence[Mapping[str, object]],
) -> tuple[dict[tuple[str, int], tuple[str, ...]], tuple[Path, ...]]:
    scoped_dates: dict[tuple[str, int], set[str]] = defaultdict(set)
    target_paths: set[Path] = set()
    for manifest in manifests:
        rows = manifest.get("changed_files")
        if not isinstance(rows, list):
            raise BseRecursiveEventRefreshError(
                "Recursive changed manifest rows are missing."
            )
        for row in rows:
            if not isinstance(row, Mapping):
                raise BseRecursiveEventRefreshError(
                    "Recursive changed manifest row is invalid."
                )
            family = str(row.get("asset_family") or "")
            recent_dates = row.get("recent_changed_trade_dates")
            if not isinstance(recent_dates, list) or not recent_dates:
                continue
            freq = int(row.get("freq") or 0)
            if family not in {"macd_kdj", "macd_kdj_state", "nineturn"}:
                raise BseRecursiveEventRefreshError(
                    f"Unsupported recent changed family: {family}"
                )
            if freq not in RECURSIVE_EVENT_REFRESH_FREQUENCIES:
                raise BseRecursiveEventRefreshError(
                    f"Unsupported recursive event frequency: {freq}"
                )
            if family == "nineturn" and freq not in RECURSIVE_EVENT_REFRESH_NINETURN_FREQUENCIES:
                raise BseRecursiveEventRefreshError(
                    f"Unsupported nine-turn event frequency: {freq}"
                )
            scoped_dates[(family, freq)].update(
                _normalize_trade_date(value) for value in recent_dates
            )
            target_paths.add(Path(str(row["target_path"])))
    if not scoped_dates:
        raise BseRecursiveEventRefreshError(
            "Recursive changed manifests contain no recent event scope."
        )
    normalized = {
        key: tuple(sorted(values)) for key, values in sorted(scoped_dates.items())
    }
    return normalized, tuple(sorted(target_paths))


def _asset_specs(
    scope: Mapping[tuple[str, int], Sequence[str]],
    check_results: Mapping[str, tuple[dg.AssetCheckResult, ...]],
    lake_root: Path,
) -> tuple[RecursiveEventRefreshAssetSpec, ...]:
    specs: list[RecursiveEventRefreshAssetSpec] = []
    family_order = {"macd_kdj": 0, "macd_kdj_state": 1, "nineturn": 2}
    for (family, freq), dates in sorted(
        scope.items(), key=lambda value: (family_order[value[0][0]], value[0][1])
    ):
        if family == "macd_kdj":
            asset_key = f"gold_stk_mins_qfq_macd_kdj_{freq}m"
            check_names = (
                "gold_stk_mins_qfq_macd_kdj_contract_check",
                "gold_stk_mins_qfq_macd_kdj_source_coverage_check",
            )
        elif family == "macd_kdj_state":
            asset_key = f"gold_stk_mins_qfq_macd_kdj_state_{freq}m"
            check_names = (
                "gold_stk_mins_qfq_macd_kdj_state_file_exists_and_schema_check",
                "gold_stk_mins_qfq_macd_kdj_state_latest_coverage_check",
            )
        else:
            asset_key = f"gold_stk_mins_qfq_nineturn_{freq}m"
            check_names = (f"gold_stk_mins_qfq_nineturn_{freq}m_integrity_check",)
        row_counts = {
            partition_key: _result_row_count(
                check_results[f"{asset_key}|{partition_key}"],
                family=family,
            )
            for partition_key in dates
        }
        specs.append(
            RecursiveEventRefreshAssetSpec(
                asset_family=family,
                asset_key=asset_key,
                freq=freq,
                partition_keys=tuple(dates),
                check_names=check_names,
                row_count_by_partition=row_counts,
            )
        )
    return tuple(specs)


def _result_row_count(
    results: Sequence[dg.AssetCheckResult], *, family: str
) -> int:
    result = results[-1]
    metadata = result.metadata or {}
    if family == "macd_kdj_state":
        value = _metadata_value(metadata, "goldenshare/state_row_count")
    else:
        value = _metadata_value(metadata, "goldenshare/checked_row_count")
    if value is None:
        raise BseRecursiveEventRefreshError(
            f"Missing checked row count for event family: {family}"
        )
    return int(value)


def _asset_uri(lake_root: Path, spec: RecursiveEventRefreshAssetSpec, date: str) -> Path:
    if spec.asset_family == "macd_kdj":
        return gold_stk_mins_qfq_macd_kdj_path(
            lake_root, spec.freq, "{ts_code}", "{year}"
        ).parents[2]
    if spec.asset_family == "macd_kdj_state":
        return gold_stk_mins_qfq_macd_kdj_state_path(lake_root, spec.freq, date)
    return gold_stk_mins_qfq_nineturn_path(lake_root, spec.freq, date)


def _observed_columns(spec: RecursiveEventRefreshAssetSpec) -> tuple[str, ...]:
    if spec.asset_family == "macd_kdj":
        schema = GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA
    elif spec.asset_family == "macd_kdj_state":
        schema = GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA
    else:
        schema = GOLD_STK_MINS_QFQ_NINETURN_SCHEMA
    return tuple(column.name for column in schema)


def _report_materialization(
    instance: Any,
    *,
    plan: RecursiveEventRefreshPlan,
    spec: RecursiveEventRefreshAssetSpec,
    partition_key: str,
) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=dg.AssetKey(spec.asset_key),
            partition=partition_key,
            metadata=build_materialization_metadata(
                uri=_asset_uri(plan.lake_root, spec, partition_key),
                row_count=spec.row_count_by_partition[partition_key],
                observed_columns=_observed_columns(spec),
                extra_metadata={
                    "source_method": "stk_mins_bse_recursive_recovery",
                    "event_backfill_scope": "changed_assets_recent_20_trade_dates",
                    "event_revision": RECURSIVE_EVENT_REFRESH_REVISION,
                    "event_plan_hash": plan.plan_hash,
                    "partition_key": partition_key,
                    "frequency": spec.freq,
                    "asset_family": spec.asset_family,
                    "source_manifest_hashes": [
                        value["manifest_hash"] for value in plan.manifest_evidence
                    ],
                },
            ),
        )
    )


def _report_check(
    instance: Any,
    *,
    run_id: str,
    plan: RecursiveEventRefreshPlan,
    spec: RecursiveEventRefreshAssetSpec,
    partition_key: str,
    check_name: str,
    result: dg.AssetCheckResult,
    materialization: Any,
) -> None:
    if not result.passed:
        raise BseRecursiveEventRefreshError(
            f"Refusing failed check event: {spec.asset_key}:{check_name}:{partition_key}"
        )
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=int(materialization.storage_id),
        run_id=str(materialization.run_id),
        timestamp=float(materialization.timestamp),
    )
    metadata = dict(result.metadata or {})
    metadata.update(
        build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            file_path=_asset_uri(plan.lake_root, spec, partition_key),
            extra_metadata={
                "event_backfill_scope": "changed_assets_recent_20_trade_dates",
                "event_revision": RECURSIVE_EVENT_REFRESH_REVISION,
                "event_plan_hash": plan.plan_hash,
                "partition_key": partition_key,
                "frequency": spec.freq,
                "asset_family": spec.asset_family,
                "reason_code": "ready",
            },
        )
    )
    instance.report_dagster_event(
        run_id=run_id,
        dagster_event=DagsterEvent(
            event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
            event_specific_data=dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(spec.asset_key),
                check_name=check_name,
                passed=True,
                blocking=True,
                partition=partition_key,
                target_materialization_data=target,
                metadata=metadata,
            ),
            job_name=RUNLESS_JOB_NAME,
        ),
    )


def _materializations_by_partition(
    instance: Any, *, asset_key: str, partitions: Sequence[str]
) -> dict[str, Any]:
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key), asset_partitions=list(partitions)
        ),
        limit=max(1, len(partitions)),
    ).records
    return {
        str(record.partition_key): record
        for record in records
        if getattr(record, "partition_key", None) is not None
    }


def _latest_materialization_for_refresh(
    instance: Any, *, asset_key: str, partition_key: str, plan_hash: str
) -> Any | None:
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key), asset_partitions=[partition_key]
        ),
        limit=1,
    ).records
    if not records:
        return None
    record = records[0]
    metadata = record.asset_materialization.metadata
    if (
        _metadata_value(metadata, "goldenshare/event_revision")
        != RECURSIVE_EVENT_REFRESH_REVISION
        or _metadata_value(metadata, "goldenshare/event_plan_hash") != plan_hash
    ):
        return None
    return record


def _ready_check_partitions(
    instance: Any,
    *,
    asset_key: str,
    check_name: str,
    materializations: Mapping[str, Any],
) -> set[str]:
    expected_ids = {
        partition: int(record.storage_id)
        for partition, record in materializations.items()
    }
    ready: set[str] = set()
    history = instance.event_log_storage.get_asset_check_execution_history(
        dg.AssetCheckKey(dg.AssetKey(asset_key), check_name),
        limit=max(100, len(expected_ids) * 3),
    )
    for record in history:
        partition = str(getattr(record, "partition", ""))
        if partition not in expected_ids or partition in ready:
            continue
        event = getattr(record, "event", None)
        dagster_event = getattr(event, "dagster_event", None) if event else None
        evaluation = (
            getattr(dagster_event, "event_specific_data", None)
            if dagster_event
            else None
        )
        target = getattr(evaluation, "target_materialization_data", None)
        if (
            target is not None
            and int(target.storage_id) == expected_ids[partition]
            and bool(getattr(evaluation, "passed", False))
            and bool(getattr(evaluation, "blocking", False))
        ):
            ready.add(partition)
    return ready


def _load_recursive_manifest(path: Path) -> dict[str, object]:
    payload = _read_json(path)
    if payload.get("stage") != "actual_changed_recursive_manifest":
        raise BseRecursiveEventRefreshError(
            f"Unexpected recursive changed manifest stage: {path}"
        )
    if payload.get("should_stop") is not False:
        raise BseRecursiveEventRefreshError(
            f"Recursive changed manifest is not green: {path}"
        )
    frozen = {
        key: value
        for key, value in payload.items()
        if key not in {"manifest_hash", "generated_at", "should_stop"}
    }
    if _hash_payload(frozen) != payload.get("manifest_hash"):
        raise BseRecursiveEventRefreshError(
            f"Recursive changed manifest hash mismatch: {path}"
        )
    rows = payload.get("changed_files")
    if not isinstance(rows, list) or len(rows) != int(
        payload.get("changed_file_count", -1)
    ):
        raise BseRecursiveEventRefreshError(
            f"Recursive changed manifest rows are incomplete: {path}"
        )
    return payload


def _target_fingerprints(paths: Sequence[Path]) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for path in paths:
        if not path.is_file():
            raise BseRecursiveEventRefreshError(
                f"Promoted recursive target is missing: {path}"
            )
        stat = path.stat()
        values.append(
            {
                "path": str(path),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return values


def _active_run_count(instance: Any) -> int:
    return len(
        instance.get_runs(
            filters=dg.RunsFilter(statuses=list(_ACTIVE_STATUSES)), limit=1
        )
    )


def _load_checkpoint(path: Path, *, plan_hash: str) -> set[str]:
    if not path.exists():
        return set()
    payload = _read_json(path)
    if payload.get("plan_hash") != plan_hash:
        raise BseRecursiveEventRefreshError(
            "Recursive event checkpoint belongs to another plan."
        )
    completed = payload.get("completed_items")
    if not isinstance(completed, list):
        raise BseRecursiveEventRefreshError(
            "Recursive event checkpoint is invalid."
        )
    return {str(value) for value in completed}


def _write_checkpoint(path: Path, *, plan_hash: str, completed: set[str]) -> None:
    _atomic_write_json(
        path,
        {
            "schema_version": 1,
            "revision": RECURSIVE_EVENT_REFRESH_REVISION,
            "plan_hash": plan_hash,
            "completed_items": sorted(completed),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _metadata_value(metadata: Mapping[str, object], key: str) -> object | None:
    value = metadata.get(key)
    return getattr(value, "value", value)


def _normalize_trade_date(value: object) -> str:
    return date.fromisoformat(str(value)).isoformat()


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise BseRecursiveEventRefreshError(f"Required report is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BseRecursiveEventRefreshError(f"Expected JSON object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "RECURSIVE_EVENT_REFRESH_REVISION",
    "BseRecursiveEventRefreshError",
    "RecursiveEventRefreshPlan",
    "RecursiveEventRefreshReport",
    "apply_bse_recursive_event_refresh",
    "load_recursive_event_refresh_plan_inputs",
    "plan_bse_recursive_event_refresh",
    "post_audit_bse_recursive_event_refresh",
    "write_recursive_event_refresh_report",
]
