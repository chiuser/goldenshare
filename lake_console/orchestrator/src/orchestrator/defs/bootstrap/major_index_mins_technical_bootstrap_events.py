"""Runless Dagster events for verified major-index minute technical files."""

from __future__ import annotations

import hashlib
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

from orchestrator.defs.bootstrap.major_index_mins_technical_history import (
    BOOTSTRAP_RECENT_CHECK_DATE_COUNT,
    MinuteTechnicalBootstrapPlan,
    load_major_index_mins_technical_bootstrap_plan,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_state_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_SCHEMA,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    major_index_mins_technical_asset_key,
    major_index_mins_technical_checks,
    major_index_mins_technical_state_asset_key,
    major_index_mins_technical_state_checks,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)

LOGGER = logging.getLogger(__name__)
EVENT_PROGRESS_INTERVAL = 1_000
_CHECK_HISTORY_LIMIT = 2_000
_ACTIVE_RUN_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class MajorIndexMinsTechnicalBootstrapEventsError(RuntimeError):
    """Raised before an unsafe runless event write."""


@dataclass(frozen=True, slots=True)
class MinuteTechnicalEventFile:
    asset_key: str
    layer: str
    freq: int
    trade_date: str
    path: Path
    row_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class MinuteTechnicalEventCheckSpec:
    asset_key: str
    check_name: str
    layer: str
    freq: int


@dataclass(frozen=True, slots=True)
class MinuteTechnicalEventPlan:
    frozen_plan: MinuteTechnicalBootstrapPlan
    promote_report_path: Path
    promote_report_sha256: str
    files: tuple[MinuteTechnicalEventFile, ...]
    recent_check_dates: tuple[str, ...]
    missing_registered_dates: tuple[str, ...]
    existing_materializations: tuple[str, ...]
    existing_ready_checks: tuple[str, ...]
    active_run_count: int

    @property
    def should_stop(self) -> bool:
        return self.active_run_count > 0 or bool(self.missing_registered_dates)

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
            "partition_set": cn_major_index_mins_trade_days.name,
            "date_count": len(self.frozen_plan.trade_dates),
            "start_date": self.frozen_plan.trade_dates[0],
            "end_date": self.frozen_plan.trade_dates[-1],
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
class MinuteTechnicalEventReport:
    mode: str
    confirmed: bool
    plan: MinuteTechnicalEventPlan
    selected_dates: tuple[str, ...] = ()
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
            "reported_materialization_count": self.reported_materialization_count,
            "reported_check_count": self.reported_check_count,
            "skipped_materialization_count": self.skipped_materialization_count,
            "skipped_check_count": self.skipped_check_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "plan": self.plan.to_dict(),
        }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MajorIndexMinsTechnicalBootstrapEventsError(
            f"{label} is unreadable: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise MajorIndexMinsTechnicalBootstrapEventsError(
            f"{label} must be a JSON object"
        )
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


def _asset_key(layer: str, freq: int) -> str:
    if layer == "technical":
        return major_index_mins_technical_asset_key(freq)
    if layer == "state":
        return major_index_mins_technical_state_asset_key(freq)
    raise MajorIndexMinsTechnicalBootstrapEventsError(
        f"unsupported promoted layer: {layer!r}"
    )


def _asset_columns(layer: str) -> tuple[str, ...]:
    schema = (
        GOLD_MAJOR_INDEX_MINS_TECHNICAL_SCHEMA
        if layer == "technical"
        else GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_SCHEMA
    )
    return tuple(value.name for value in schema)


def _check_specs() -> tuple[MinuteTechnicalEventCheckSpec, ...]:
    specs: list[MinuteTechnicalEventCheckSpec] = []
    for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
        technical_key = major_index_mins_technical_asset_key(freq)
        specs.extend(
            MinuteTechnicalEventCheckSpec(
                asset_key=technical_key,
                check_name=name,
                layer="technical",
                freq=freq,
            )
            for name in major_index_mins_technical_checks(freq)
        )
        state_key = major_index_mins_technical_state_asset_key(freq)
        specs.extend(
            MinuteTechnicalEventCheckSpec(
                asset_key=state_key,
                check_name=name,
                layer="state",
                freq=freq,
            )
            for name in major_index_mins_technical_state_checks(freq)
        )
    return tuple(specs)


def _materialization_id(value: MinuteTechnicalEventFile) -> str:
    return f"{value.asset_key}|{value.trade_date}"


def _check_id(spec: MinuteTechnicalEventCheckSpec, trade_date: str) -> str:
    return f"{spec.asset_key}|{spec.check_name}|{trade_date}"


def _active_run_count(instance: Any) -> int:
    return len(
        instance.get_runs(
            filters=dg.RunsFilter(statuses=list(_ACTIVE_RUN_STATUSES)),
            limit=1,
        )
    )


def _formal_path(
    plan: MinuteTechnicalBootstrapPlan,
    *,
    layer: str,
    freq: int,
    trade_date: str,
) -> Path:
    if layer == "technical":
        return gold_major_index_mins_technical_path(
            plan.source_lake_root,
            freq,
            trade_date,
        )
    return gold_major_index_mins_technical_state_path(
        plan.source_lake_root,
        freq,
        trade_date,
    )


def _load_formal_files(
    *,
    frozen_plan: MinuteTechnicalBootstrapPlan,
    promote_report_path: Path,
) -> tuple[MinuteTechnicalEventFile, ...]:
    report = _load_json(
        promote_report_path,
        label="major-index minute technical promote report",
    )
    if (
        report.get("plan_hash") != frozen_plan.plan_hash
        or report.get("should_stop") is not False
        or Path(str(report.get("formal_lake_root", ""))).resolve()
        != frozen_plan.source_lake_root.resolve()
    ):
        raise MajorIndexMinsTechnicalBootstrapEventsError(
            "promote report is not green for the frozen plan and formal Lake"
        )
    results = report.get("results")
    if not isinstance(results, list):
        raise MajorIndexMinsTechnicalBootstrapEventsError(
            "promote report has no results"
        )
    expected_keys = {
        (layer, freq, trade_date)
        for trade_date in frozen_plan.trade_dates
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
        for layer in ("technical", "state")
    }
    files: list[MinuteTechnicalEventFile] = []
    observed_keys: set[tuple[str, int, str]] = set()
    for value in results:
        if not isinstance(value, Mapping):
            raise MajorIndexMinsTechnicalBootstrapEventsError(
                "promote result is not an object"
            )
        layer = str(value.get("layer"))
        freq = int(value.get("freq") or 0)
        trade_date = str(value.get("trade_date"))
        key = (layer, freq, trade_date)
        if key in observed_keys:
            raise MajorIndexMinsTechnicalBootstrapEventsError(
                f"duplicate promote result: {key}"
            )
        observed_keys.add(key)
        if key not in expected_keys:
            raise MajorIndexMinsTechnicalBootstrapEventsError(
                f"promote result is outside the frozen scope: {key}"
            )
        expected_path = _formal_path(
            frozen_plan,
            layer=layer,
            freq=freq,
            trade_date=trade_date,
        )
        path = Path(str(value.get("formal_path")))
        expected_hash = str(value.get("sha256"))
        row_count = int(value.get("row_count") or 0)
        if path.resolve() != expected_path.resolve():
            raise MajorIndexMinsTechnicalBootstrapEventsError(
                f"promote result path is outside the frozen target: {path}"
            )
        if not path.is_file() or _file_sha256(path) != expected_hash:
            raise MajorIndexMinsTechnicalBootstrapEventsError(
                f"formal file is missing or changed after promotion: {path}"
            )
        if row_count <= 0:
            raise MajorIndexMinsTechnicalBootstrapEventsError(
                f"formal file has a non-positive promoted row count: {path}"
            )
        files.append(
            MinuteTechnicalEventFile(
                asset_key=_asset_key(layer, freq),
                layer=layer,
                freq=freq,
                trade_date=trade_date,
                path=path,
                row_count=row_count,
                sha256=expected_hash,
            )
        )
    if observed_keys != expected_keys:
        raise MajorIndexMinsTechnicalBootstrapEventsError(
            "promote result scope differs from the frozen minute dates"
        )
    return tuple(
        sorted(files, key=lambda value: (value.trade_date, value.freq, value.layer))
    )


def _materialization_records(
    instance: Any,
    *,
    asset_key: str,
    dates: Sequence[str],
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
    specs: Sequence[MinuteTechnicalEventCheckSpec],
    dates: Sequence[str],
) -> tuple[str, ...]:
    materializations_by_asset = {
        asset_key: _materialization_records(
            instance,
            asset_key=asset_key,
            dates=dates,
        )
        for asset_key in {spec.asset_key for spec in specs}
    }
    ready: set[str] = set()
    for spec in specs:
        storage_ids = {
            trade_date: getattr(record, "storage_id", None)
            for trade_date, record in materializations_by_asset[spec.asset_key].items()
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
                and bool(getattr(evaluation, "blocking", False))
            ):
                ready.add(_check_id(spec, trade_date))
    return tuple(sorted(ready))


def plan_major_index_mins_technical_bootstrap_events(
    *,
    instance: Any,
    plan_report_path: Path,
    promote_report_path: Path,
    expected_plan_hash: str,
) -> MinuteTechnicalEventPlan:
    frozen_plan = load_major_index_mins_technical_bootstrap_plan(
        plan_report_path,
        expected_plan_hash=expected_plan_hash,
    )
    files = _load_formal_files(
        frozen_plan=frozen_plan,
        promote_report_path=promote_report_path,
    )
    dates = frozen_plan.trade_dates
    recent_dates = dates[-BOOTSTRAP_RECENT_CHECK_DATE_COUNT:]
    registered = set(instance.get_dynamic_partitions(cn_major_index_mins_trade_days.name))
    existing_materializations = tuple(
        sorted(
            f"{asset_key}|{trade_date}"
            for asset_key in {_asset_key(value.layer, value.freq) for value in files}
            for trade_date in instance.get_materialized_partitions(
                dg.AssetKey(asset_key)
            )
            if trade_date in set(dates)
        )
    )
    return MinuteTechnicalEventPlan(
        frozen_plan=frozen_plan,
        promote_report_path=promote_report_path,
        promote_report_sha256=_file_sha256(promote_report_path),
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
    )


def _latest_materialization(
    instance: Any,
    *,
    asset_key: str,
    trade_date: str,
) -> object:
    record = _materialization_records(
        instance,
        asset_key=asset_key,
        dates=(trade_date,),
    ).get(trade_date)
    if record is None:
        raise MajorIndexMinsTechnicalBootstrapEventsError(
            f"missing target materialization: {asset_key}:{trade_date}"
        )
    return record


def _report_materialization(
    instance: Any,
    *,
    plan: MinuteTechnicalEventPlan,
    file: MinuteTechnicalEventFile,
) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=dg.AssetKey(file.asset_key),
            partition=file.trade_date,
            metadata=build_materialization_metadata(
                uri=file.path,
                row_count=file.row_count,
                observed_columns=_asset_columns(file.layer),
                extra_metadata={
                    "source_method": "major_index_mins_technical_direct_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_history",
                    "plan_hash": plan.frozen_plan.plan_hash,
                    "promote_report_sha256": plan.promote_report_sha256,
                    "sha256": file.sha256,
                    "frequency": file.freq,
                    "layer": file.layer,
                },
            ),
        )
    )


def _report_check(
    instance: Any,
    *,
    plan: MinuteTechnicalEventPlan,
    file: MinuteTechnicalEventFile,
    spec: MinuteTechnicalEventCheckSpec,
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
            blocking=True,
            partition=file.trade_date,
            target_materialization_data=target,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=file.row_count,
                failed_row_count=0,
                file_path=file.path,
                extra_metadata={
                    "reason_code": "ready",
                    "source_method": "major_index_mins_technical_direct_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_trade_days",
                    "plan_hash": plan.frozen_plan.plan_hash,
                    "promote_report_sha256": plan.promote_report_sha256,
                    "frequency": file.freq,
                    "layer": file.layer,
                },
            ),
        )
    )


def report_major_index_mins_technical_events(
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
) -> MinuteTechnicalEventReport:
    if not dry_run and not confirm_event_write:
        raise MajorIndexMinsTechnicalBootstrapEventsError(
            "event apply requires confirm_event_write=True"
        )
    started = perf_counter()
    plan = plan_major_index_mins_technical_bootstrap_events(
        instance=instance,
        plan_report_path=plan_report_path,
        promote_report_path=promote_report_path,
        expected_plan_hash=expected_plan_hash,
    )
    if dry_run:
        return MinuteTechnicalEventReport(
            mode="dry-run",
            confirmed=False,
            plan=plan,
            elapsed_ms=(perf_counter() - started) * 1_000,
        )
    if plan.should_stop:
        raise MajorIndexMinsTechnicalBootstrapEventsError(
            "event apply is blocked by active runs or missing minute partitions"
        )
    if sample_only:
        if sample_date is None or sample_date not in plan.recent_check_dates:
            raise MajorIndexMinsTechnicalBootstrapEventsError(
                "sample_date must explicitly select a recent-20 trade date"
            )
        selected_dates = (sample_date,)
    else:
        selected_dates = plan.frozen_plan.trade_dates
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
            LOGGER.info(
                "reported %s major-index minute technical Bootstrap events",
                event_count,
            )
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
                LOGGER.info(
                    "reported %s major-index minute technical Bootstrap events",
                    event_count,
                )
    report = MinuteTechnicalEventReport(
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


def post_audit_major_index_mins_technical_events(
    *,
    instance: Any,
    plan_report_path: Path,
    promote_report_path: Path,
    expected_plan_hash: str,
) -> MinuteTechnicalEventPlan:
    plan = plan_major_index_mins_technical_bootstrap_events(
        instance=instance,
        plan_report_path=plan_report_path,
        promote_report_path=promote_report_path,
        expected_plan_hash=expected_plan_hash,
    )
    if plan.should_stop or plan.planned_materialization_count or plan.planned_check_count:
        raise MajorIndexMinsTechnicalBootstrapEventsError(
            "post-audit found missing partitions, events, or an active run"
        )
    return plan


def write_major_index_mins_technical_event_report(
    report: MinuteTechnicalEventPlan | MinuteTechnicalEventReport,
    output_path: Path,
) -> None:
    _atomic_write_json(output_path, report.to_dict())


__all__ = [
    "MajorIndexMinsTechnicalBootstrapEventsError",
    "MinuteTechnicalEventPlan",
    "MinuteTechnicalEventReport",
    "plan_major_index_mins_technical_bootstrap_events",
    "post_audit_major_index_mins_technical_events",
    "report_major_index_mins_technical_events",
    "write_major_index_mins_technical_event_report",
]
