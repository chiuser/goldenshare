"""Runless Dagster events for verified ``idx_factor_pro`` Bootstrap files."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_plan import (
    BOOTSTRAP_RECENT_CHECK_DATE_COUNT,
    IdxFactorProBootstrapPlan,
    file_sha256,
    load_idx_factor_pro_bootstrap_plan,
)
from orchestrator.defs.partitions import cn_major_index_factor_trade_days
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    silver_index_factor_pro_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA,
    SILVER_INDEX_FACTOR_PRO_SCHEMA,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_RAW_ASSET_KEY,
    IDX_FACTOR_PRO_RAW_CHECKS,
    IDX_FACTOR_PRO_RAW_NULLABLE_CHECK,
    IDX_FACTOR_PRO_SILVER_ASSET_KEY,
    IDX_FACTOR_PRO_SILVER_CHECKS,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)

LOGGER = logging.getLogger(__name__)
EVENT_PROGRESS_INTERVAL = 1_000
PARTITION_BATCH_SIZE = 1_000
_CHECK_HISTORY_LIMIT = 500
_ACTIVE_RUN_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class IdxFactorProBootstrapEventsError(RuntimeError):
    """Raised before an unsafe partition or runless event write."""


@dataclass(frozen=True, slots=True)
class IdxFactorProEventFile:
    asset_key: str
    layer: str
    trade_date: str
    path: Path
    row_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class IdxFactorProEventCheckSpec:
    asset_key: str
    check_name: str
    blocking: bool


@dataclass(frozen=True, slots=True)
class IdxFactorProEventPlan:
    frozen_plan: IdxFactorProBootstrapPlan
    promote_report_path: Path
    promote_report_sha256: str
    files: tuple[IdxFactorProEventFile, ...]
    recent_check_dates: tuple[str, ...]
    missing_registered_dates: tuple[str, ...]
    existing_materializations: tuple[str, ...]
    existing_ready_checks: tuple[str, ...]
    active_run_count: int
    require_registered: bool

    @property
    def should_stop(self) -> bool:
        return self.active_run_count > 0 or (
            self.require_registered and bool(self.missing_registered_dates)
        )

    @property
    def planned_materialization_count(self) -> int:
        existing = set(self.existing_materializations)
        return sum(_materialization_id(value) not in existing for value in self.files)

    @property
    def planned_check_count(self) -> int:
        existing = set(self.existing_ready_checks)
        return sum(
            _check_id(spec, trade_date) not in existing
            for spec in _check_specs()
            for trade_date in self.recent_check_dates
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_hash": self.frozen_plan.plan_hash,
            "promote_report_path": str(self.promote_report_path),
            "promote_report_sha256": self.promote_report_sha256,
            "partition_set": cn_major_index_factor_trade_days.name,
            "date_count": len(self.frozen_plan.candidate_trade_dates),
            "start_date": self.frozen_plan.candidate_trade_dates[0],
            "end_date": self.frozen_plan.candidate_trade_dates[-1],
            "recent_check_dates": list(self.recent_check_dates),
            "file_count": len(self.files),
            "row_count": sum(value.row_count for value in self.files),
            "missing_registered_dates": list(self.missing_registered_dates),
            "active_run_count": self.active_run_count,
            "planned_materialization_count": self.planned_materialization_count,
            "planned_check_count": self.planned_check_count,
            "should_stop": self.should_stop,
            "writes": {
                "formal_lake": 0,
                "dynamic_partitions": 0,
                "dagster_events": 0,
            },
        }


@dataclass(frozen=True, slots=True)
class IdxFactorProEventReport:
    mode: str
    confirmed: bool
    plan: IdxFactorProEventPlan
    selected_dates: tuple[str, ...] = ()
    registered_partition_count: int = 0
    reported_materialization_count: int = 0
    reported_check_count: int = 0
    skipped_materialization_count: int = 0
    skipped_check_count: int = 0
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": self.mode,
            "confirmed": self.confirmed,
            "selected_dates": list(self.selected_dates),
            "registered_partition_count": self.registered_partition_count,
            "reported_materialization_count": self.reported_materialization_count,
            "reported_check_count": self.reported_check_count,
            "skipped_materialization_count": self.skipped_materialization_count,
            "skipped_check_count": self.skipped_check_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "plan": self.plan.to_dict(),
        }


def _load_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IdxFactorProBootstrapEventsError(
            f"{label} is unreadable: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise IdxFactorProBootstrapEventsError(f"{label} must be a JSON object")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _asset_columns(asset_key: str) -> tuple[str, ...]:
    schema = (
        RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA
        if asset_key == IDX_FACTOR_PRO_RAW_ASSET_KEY
        else SILVER_INDEX_FACTOR_PRO_SCHEMA
    )
    return tuple(value.name for value in schema)


def _check_specs() -> tuple[IdxFactorProEventCheckSpec, ...]:
    return tuple(
        [
            IdxFactorProEventCheckSpec(IDX_FACTOR_PRO_RAW_ASSET_KEY, name, True)
            for name in IDX_FACTOR_PRO_RAW_CHECKS
        ]
        + [
            IdxFactorProEventCheckSpec(
                IDX_FACTOR_PRO_RAW_ASSET_KEY,
                IDX_FACTOR_PRO_RAW_NULLABLE_CHECK,
                False,
            )
        ]
        + [
            IdxFactorProEventCheckSpec(IDX_FACTOR_PRO_SILVER_ASSET_KEY, name, True)
            for name in IDX_FACTOR_PRO_SILVER_CHECKS
        ]
    )


def _materialization_id(value: IdxFactorProEventFile) -> str:
    return f"{value.asset_key}|{value.trade_date}"


def _check_id(spec: IdxFactorProEventCheckSpec, trade_date: str) -> str:
    return f"{spec.asset_key}|{spec.check_name}|{trade_date}"


def _active_run_count(instance: Any) -> int:
    return len(
        instance.get_runs(
            filters=dg.RunsFilter(statuses=list(_ACTIVE_RUN_STATUSES)),
            limit=1,
        )
    )


def _load_formal_files(
    *,
    frozen_plan: IdxFactorProBootstrapPlan,
    promote_report_path: Path,
) -> tuple[IdxFactorProEventFile, ...]:
    report = _load_json(promote_report_path, label="idx_factor_pro promote report")
    if (
        report.get("plan_hash") != frozen_plan.plan_hash
        or report.get("should_stop") is not False
        or Path(str(report.get("formal_lake_root", ""))).resolve()
        != frozen_plan.lake_root.resolve()
    ):
        raise IdxFactorProBootstrapEventsError(
            "promote report is not green for the frozen plan and formal Lake"
        )
    results = report.get("results")
    if not isinstance(results, list):
        raise IdxFactorProBootstrapEventsError("promote report has no results")
    expected_keys = {
        (layer, trade_date)
        for layer in ("raw", "silver")
        for trade_date in frozen_plan.candidate_trade_dates
    }
    files: list[IdxFactorProEventFile] = []
    observed_keys: set[tuple[str, str]] = set()
    for value in results:
        if not isinstance(value, Mapping):
            raise IdxFactorProBootstrapEventsError("promote result is not an object")
        layer = str(value.get("layer"))
        trade_date = str(value.get("trade_date"))
        key = (layer, trade_date)
        if key in observed_keys:
            raise IdxFactorProBootstrapEventsError(f"duplicate promote result: {key}")
        observed_keys.add(key)
        asset_key = (
            IDX_FACTOR_PRO_RAW_ASSET_KEY
            if layer == "raw"
            else IDX_FACTOR_PRO_SILVER_ASSET_KEY
            if layer == "silver"
            else ""
        )
        expected_path = (
            raw_idx_factor_pro_path(frozen_plan.lake_root, trade_date)
            if layer == "raw"
            else silver_index_factor_pro_path(frozen_plan.lake_root, trade_date)
        )
        path = Path(str(value.get("formal_path")))
        expected_hash = str(value.get("sha256"))
        if not asset_key or path.resolve() != expected_path.resolve():
            raise IdxFactorProBootstrapEventsError(
                f"promote result path is outside the frozen target: {path}"
            )
        if not path.is_file() or file_sha256(path) != expected_hash:
            raise IdxFactorProBootstrapEventsError(
                f"formal file is missing or changed after promotion: {path}"
            )
        files.append(
            IdxFactorProEventFile(
                asset_key=asset_key,
                layer=layer,
                trade_date=trade_date,
                path=path,
                row_count=int(value.get("row_count") or 0),
                sha256=expected_hash,
            )
        )
    if observed_keys != expected_keys:
        raise IdxFactorProBootstrapEventsError(
            "promote result scope differs from the frozen candidate dates"
        )
    return tuple(sorted(files, key=lambda value: (value.trade_date, value.layer)))


def _materialization_records(
    instance: Any, *, asset_key: str, dates: Sequence[str]
) -> dict[str, object]:
    if not dates:
        return {}
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key),
            asset_partitions=list(dates),
        ),
        limit=max(1, len(dates)),
    )
    return {
        str(record.partition_key): record
        for record in result.records
        if getattr(record, "partition_key", None) is not None
    }


def _existing_ready_checks(
    instance: Any,
    *,
    specs: Sequence[IdxFactorProEventCheckSpec],
    dates: Sequence[str],
) -> tuple[str, ...]:
    ready: set[str] = set()
    for spec in specs:
        materializations = _materialization_records(
            instance,
            asset_key=spec.asset_key,
            dates=dates,
        )
        storage_ids = {
            trade_date: getattr(record, "storage_id", None)
            for trade_date, record in materializations.items()
        }
        history = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(dg.AssetKey(spec.asset_key), spec.check_name),
            limit=_CHECK_HISTORY_LIMIT,
        )
        for record in history:
            trade_date = str(getattr(record, "partition", ""))
            if trade_date not in storage_ids:
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
                and target.storage_id == storage_ids[trade_date]
                and bool(getattr(evaluation, "passed", False))
                and bool(getattr(evaluation, "blocking", False)) == spec.blocking
            ):
                ready.add(_check_id(spec, trade_date))
    return tuple(sorted(ready))


def plan_idx_factor_pro_bootstrap_events(
    *,
    instance: Any,
    plan_report_path: Path,
    promote_report_path: Path,
    expected_plan_hash: str,
    require_registered: bool = False,
) -> IdxFactorProEventPlan:
    frozen_plan = load_idx_factor_pro_bootstrap_plan(
        plan_report_path,
        expected_plan_hash=expected_plan_hash,
    )
    files = _load_formal_files(
        frozen_plan=frozen_plan,
        promote_report_path=promote_report_path,
    )
    dates = frozen_plan.candidate_trade_dates
    recent_dates = dates[-BOOTSTRAP_RECENT_CHECK_DATE_COUNT:]
    registered = set(
        instance.get_dynamic_partitions(cn_major_index_factor_trade_days.name)
    )
    existing_materializations = tuple(
        sorted(
            f"{asset_key}|{trade_date}"
            for asset_key in (
                IDX_FACTOR_PRO_RAW_ASSET_KEY,
                IDX_FACTOR_PRO_SILVER_ASSET_KEY,
            )
            for trade_date in instance.get_materialized_partitions(
                dg.AssetKey(asset_key)
            )
            if trade_date in set(dates)
        )
    )
    return IdxFactorProEventPlan(
        frozen_plan=frozen_plan,
        promote_report_path=promote_report_path,
        promote_report_sha256=file_sha256(promote_report_path),
        files=files,
        recent_check_dates=recent_dates,
        missing_registered_dates=tuple(sorted(set(dates) - registered)),
        existing_materializations=existing_materializations,
        existing_ready_checks=_existing_ready_checks(
            instance,
            specs=_check_specs(),
            dates=recent_dates,
        ),
        active_run_count=_active_run_count(instance),
        require_registered=require_registered,
    )


def register_idx_factor_pro_partitions(
    *,
    instance: Any,
    plan_report_path: Path,
    promote_report_path: Path,
    expected_plan_hash: str,
    apply: bool = False,
    confirm_partition_write: bool = False,
) -> IdxFactorProEventReport:
    started = perf_counter()
    plan = plan_idx_factor_pro_bootstrap_events(
        instance=instance,
        plan_report_path=plan_report_path,
        promote_report_path=promote_report_path,
        expected_plan_hash=expected_plan_hash,
        require_registered=False,
    )
    if not apply:
        return IdxFactorProEventReport(
            mode="register-partitions-dry-run",
            confirmed=False,
            plan=plan,
            elapsed_ms=(perf_counter() - started) * 1_000,
        )
    if not confirm_partition_write:
        raise IdxFactorProBootstrapEventsError(
            "partition registration requires confirm_partition_write=True"
        )
    if plan.active_run_count:
        raise IdxFactorProBootstrapEventsError(
            "partition registration is blocked by an active Dagster run"
        )
    missing = plan.missing_registered_dates
    for start in range(0, len(missing), PARTITION_BATCH_SIZE):
        instance.add_dynamic_partitions(
            cn_major_index_factor_trade_days.name,
            list(missing[start : start + PARTITION_BATCH_SIZE]),
        )
    observed = set(
        instance.get_dynamic_partitions(cn_major_index_factor_trade_days.name)
    )
    if not set(plan.frozen_plan.candidate_trade_dates).issubset(observed):
        raise IdxFactorProBootstrapEventsError(
            "dynamic partition registration post-audit failed"
        )
    return IdxFactorProEventReport(
        mode="register-partitions",
        confirmed=True,
        plan=plan,
        registered_partition_count=len(missing),
        elapsed_ms=(perf_counter() - started) * 1_000,
    )


def _latest_materialization(
    instance: Any, *, asset_key: str, trade_date: str
) -> object:
    records = _materialization_records(
        instance,
        asset_key=asset_key,
        dates=(trade_date,),
    )
    record = records.get(trade_date)
    if record is None:
        raise IdxFactorProBootstrapEventsError(
            f"missing target materialization: {asset_key}:{trade_date}"
        )
    return record


def _report_materialization(
    instance: Any,
    *,
    plan: IdxFactorProEventPlan,
    file: IdxFactorProEventFile,
) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=dg.AssetKey(file.asset_key),
            partition=file.trade_date,
            metadata=build_materialization_metadata(
                uri=file.path,
                row_count=file.row_count,
                observed_columns=_asset_columns(file.asset_key),
                extra_metadata={
                    "source_method": "tushare_idx_factor_pro_direct_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_history",
                    "plan_hash": plan.frozen_plan.plan_hash,
                    "promote_report_sha256": plan.promote_report_sha256,
                    "sha256": file.sha256,
                },
            ),
        )
    )


def _report_check(
    instance: Any,
    *,
    plan: IdxFactorProEventPlan,
    file: IdxFactorProEventFile,
    spec: IdxFactorProEventCheckSpec,
) -> None:
    materialization = _latest_materialization(
        instance,
        asset_key=spec.asset_key,
        trade_date=file.trade_date,
    )
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=dg.AssetKey(spec.asset_key),
            check_name=spec.check_name,
            passed=True,
            blocking=spec.blocking,
            partition=file.trade_date,
            target_materialization_data=target,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=file.row_count,
                failed_row_count=0,
                file_path=file.path,
                extra_metadata={
                    "reason_code": "ready",
                    "source_method": "tushare_idx_factor_pro_direct_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_trade_days",
                    "plan_hash": plan.frozen_plan.plan_hash,
                    "promote_report_sha256": plan.promote_report_sha256,
                },
            ),
        )
    )


def report_idx_factor_pro_events(
    *,
    instance: Any,
    plan_report_path: Path,
    promote_report_path: Path,
    expected_plan_hash: str,
    dry_run: bool = True,
    confirm_event_write: bool = False,
    sample_only: bool = False,
    sample_date: str | None = None,
    checkpoint_path: Path | None = None,
) -> IdxFactorProEventReport:
    if not dry_run and not confirm_event_write:
        raise IdxFactorProBootstrapEventsError(
            "event apply requires confirm_event_write=True"
        )
    started = perf_counter()
    plan = plan_idx_factor_pro_bootstrap_events(
        instance=instance,
        plan_report_path=plan_report_path,
        promote_report_path=promote_report_path,
        expected_plan_hash=expected_plan_hash,
        require_registered=True,
    )
    if dry_run:
        return IdxFactorProEventReport(
            mode="dry-run",
            confirmed=False,
            plan=plan,
            elapsed_ms=(perf_counter() - started) * 1_000,
        )
    if plan.should_stop:
        raise IdxFactorProBootstrapEventsError(
            "event apply is blocked by active runs or missing partitions"
        )
    if sample_only:
        if sample_date is None or sample_date not in plan.recent_check_dates:
            raise IdxFactorProBootstrapEventsError(
                "sample_date must explicitly select a recent-20 trade date"
            )
        selected_dates = (sample_date,)
    else:
        selected_dates = plan.frozen_plan.candidate_trade_dates
    selected = set(selected_dates)
    existing_materializations = set(plan.existing_materializations)
    existing_checks = set(plan.existing_ready_checks)
    files_by_key = {
        (value.asset_key, value.trade_date): value for value in plan.files
    }
    reported_materializations = 0
    reported_checks = 0
    skipped_materializations = 0
    skipped_checks = 0
    event_count = 0
    for file in plan.files:
        if file.trade_date not in selected:
            continue
        identity = _materialization_id(file)
        if identity in existing_materializations:
            skipped_materializations += 1
        else:
            _report_materialization(instance, plan=plan, file=file)
            existing_materializations.add(identity)
            reported_materializations += 1
            event_count += 1
        if checkpoint_path and event_count and event_count % EVENT_PROGRESS_INTERVAL == 0:
            _atomic_write_json(
                checkpoint_path,
                {
                    "plan_hash": plan.frozen_plan.plan_hash,
                    "reported_event_count": event_count,
                    "last_materialization": identity,
                },
            )
            LOGGER.info("reported %s idx_factor_pro Bootstrap events", event_count)
    for spec in _check_specs():
        for trade_date in plan.recent_check_dates:
            if trade_date not in selected:
                continue
            identity = _check_id(spec, trade_date)
            if identity in existing_checks:
                skipped_checks += 1
                continue
            file = files_by_key[(spec.asset_key, trade_date)]
            _report_check(instance, plan=plan, file=file, spec=spec)
            existing_checks.add(identity)
            reported_checks += 1
            event_count += 1
            if checkpoint_path and event_count % EVENT_PROGRESS_INTERVAL == 0:
                _atomic_write_json(
                    checkpoint_path,
                    {
                        "plan_hash": plan.frozen_plan.plan_hash,
                        "reported_event_count": event_count,
                        "last_check": identity,
                    },
                )
                LOGGER.info("reported %s idx_factor_pro Bootstrap events", event_count)
    report = IdxFactorProEventReport(
        mode="sample" if sample_only else "apply",
        confirmed=True,
        plan=plan,
        selected_dates=selected_dates,
        reported_materialization_count=reported_materializations,
        reported_check_count=reported_checks,
        skipped_materialization_count=skipped_materializations,
        skipped_check_count=skipped_checks,
        elapsed_ms=(perf_counter() - started) * 1_000,
    )
    if checkpoint_path:
        _atomic_write_json(checkpoint_path, report.to_dict())
    return report


def post_audit_idx_factor_pro_events(
    *,
    instance: Any,
    plan_report_path: Path,
    promote_report_path: Path,
    expected_plan_hash: str,
) -> IdxFactorProEventPlan:
    plan = plan_idx_factor_pro_bootstrap_events(
        instance=instance,
        plan_report_path=plan_report_path,
        promote_report_path=promote_report_path,
        expected_plan_hash=expected_plan_hash,
        require_registered=True,
    )
    if plan.should_stop or plan.planned_materialization_count or plan.planned_check_count:
        raise IdxFactorProBootstrapEventsError(
            "post-audit found missing partitions, events, or an active run"
        )
    return plan


def write_idx_factor_pro_event_report(
    report: IdxFactorProEventPlan | IdxFactorProEventReport,
    output_path: Path,
) -> None:
    _atomic_write_json(output_path, report.to_dict())


__all__ = [
    "IdxFactorProBootstrapEventsError",
    "IdxFactorProEventPlan",
    "IdxFactorProEventReport",
    "plan_idx_factor_pro_bootstrap_events",
    "post_audit_idx_factor_pro_events",
    "register_idx_factor_pro_partitions",
    "report_idx_factor_pro_events",
    "write_idx_factor_pro_event_report",
]
