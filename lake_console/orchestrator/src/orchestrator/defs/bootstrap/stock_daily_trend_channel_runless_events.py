"""Controlled runless events for verified stock daily trend-channel history."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.stock_daily_trend_channel_history import (
    FINAL_AUDIT_PHASE,
    PROMOTE_PHASE,
    RESULT_ASSET_KEY,
    STATE_ASSET_KEY,
    StockDailyTrendChannelHistoryPlan,
    load_stock_daily_trend_channel_history_plan,
)
from orchestrator.defs.partitions import cn_a_stock_daily_trend_channel_trade_days
from orchestrator.defs.paths import (
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_state_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA,
    GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.stock_daily_trend_channel import FORMULA_VERSION

RESULT_CONTRACT_CHECK = "gold_stock_daily_trend_channel_contract_check"
STATE_CONTRACT_CHECK = "gold_stock_daily_trend_channel_state_contract_check"
INPUT_COVERAGE_CHECK = "gold_stock_daily_trend_channel_input_coverage_check"
RECENT_CHECK_TRADE_DAY_COUNT = 20
CHECK_EVENT_PARTITION_LIMIT = 21
MATERIALIZATION_EVENT_MULTIPLIER = 2
ORDINARY_CHECK_COUNT = 3
EVENT_PROGRESS_INTERVAL = 100
_CHECK_HISTORY_LIMIT = 200
_ACTIVE_RUN_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class StockDailyTrendChannelRunlessEventError(RuntimeError):
    """Raised before an unreviewed runless event or partition write."""


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelEventFile:
    asset_key: str
    trade_date: str
    path: Path
    row_count: int
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelEventCheck:
    asset_key: str
    check_name: str
    check_scope: CheckScope


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelRunlessEventPlan:
    history_plan: StockDailyTrendChannelHistoryPlan
    promote_hash: str
    final_audit_hash: str
    files: tuple[StockDailyTrendChannelEventFile, ...]
    recent_check_trade_dates: tuple[str, ...]
    missing_registered_trade_dates: tuple[str, ...]
    existing_materializations: tuple[str, ...]
    existing_ready_checks: tuple[str, ...]
    active_run_count: int

    @property
    def planned_registration_count(self) -> int:
        return len(self.missing_registered_trade_dates)

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
            for trade_date in self.recent_check_trade_dates
        )

    @property
    def should_stop(self) -> bool:
        partition_count = len(self.history_plan.trade_dates)
        return (
            self.active_run_count > 0
            or self.planned_registration_count > partition_count
            or self.planned_materialization_count
            > MATERIALIZATION_EVENT_MULTIPLIER * partition_count
            or self.planned_check_count
            > CHECK_EVENT_PARTITION_LIMIT * ORDINARY_CHECK_COUNT
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.history_plan.plan_id,
            "plan_hash": self.history_plan.plan_hash,
            "promote_hash": self.promote_hash,
            "final_audit_hash": self.final_audit_hash,
            "partition_set": cn_a_stock_daily_trend_channel_trade_days.name,
            "approved_partition_count": len(self.history_plan.trade_dates),
            "approved_start_date": self.history_plan.trade_dates[0],
            "approved_end_date": self.history_plan.trade_dates[-1],
            "recent_check_trade_dates": list(self.recent_check_trade_dates),
            "planned_registration_count": self.planned_registration_count,
            "planned_materialization_count": self.planned_materialization_count,
            "planned_check_count": self.planned_check_count,
            "missing_registered_samples": list(
                self.missing_registered_trade_dates[:20]
            ),
            "active_run_count": self.active_run_count,
            "should_stop": self.should_stop,
        }


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelRunlessEventReport:
    mode: str
    plan: StockDailyTrendChannelRunlessEventPlan
    confirmed: bool
    selected_trade_dates: tuple[str, ...] = ()
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
            "selected_trade_dates": list(self.selected_trade_dates),
            "registered_partition_count": self.registered_partition_count,
            "reported_materialization_count": self.reported_materialization_count,
            "reported_check_count": self.reported_check_count,
            "skipped_materialization_count": self.skipped_materialization_count,
            "skipped_check_count": self.skipped_check_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "plan": self.plan.to_dict(),
        }


def plan_stock_daily_trend_channel_runless_events(
    *,
    instance: Any,
    plan_report_path: Path,
    expected_plan_id: str,
    expected_plan_hash: str,
    promote_report_path: Path,
    expected_promote_hash: str,
    final_audit_report_path: Path,
    expected_final_audit_hash: str,
) -> StockDailyTrendChannelRunlessEventPlan:
    """Build an exact bounded event plan from green physical reports."""

    history_plan = load_stock_daily_trend_channel_history_plan(plan_report_path)
    if (
        history_plan.plan_id != expected_plan_id
        or history_plan.plan_hash != expected_plan_hash
        or history_plan.should_stop
    ):
        raise StockDailyTrendChannelRunlessEventError(
            "event plan history identity is not approved"
        )
    files = _load_verified_formal_files(
        history_plan=history_plan,
        promote_report_path=promote_report_path,
        expected_promote_hash=expected_promote_hash,
        final_audit_report_path=final_audit_report_path,
        expected_final_audit_hash=expected_final_audit_hash,
    )
    trade_dates = history_plan.trade_dates
    recent_dates = tuple(
        dict.fromkeys((*trade_dates[-RECENT_CHECK_TRADE_DAY_COUNT:], trade_dates[-1]))
    )
    registered = {
        str(value)
        for value in instance.get_dynamic_partitions(
            cn_a_stock_daily_trend_channel_trade_days.name
        )
    }
    existing_materializations = tuple(
        sorted(
            f"{asset_key}|{trade_date}"
            for asset_key in (RESULT_ASSET_KEY, STATE_ASSET_KEY)
            for trade_date in instance.get_materialized_partitions(
                dg.AssetKey(asset_key)
            )
            if str(trade_date) in set(trade_dates)
        )
    )
    return StockDailyTrendChannelRunlessEventPlan(
        history_plan=history_plan,
        promote_hash=expected_promote_hash,
        final_audit_hash=expected_final_audit_hash,
        files=files,
        recent_check_trade_dates=recent_dates,
        missing_registered_trade_dates=tuple(sorted(set(trade_dates) - registered)),
        existing_materializations=existing_materializations,
        existing_ready_checks=_existing_ready_checks(
            instance,
            specs=_check_specs(),
            trade_dates=recent_dates,
        ),
        active_run_count=_active_run_count(instance),
    )


def report_stock_daily_trend_channel_runless_events(
    *,
    instance: Any,
    plan_report_path: Path,
    expected_plan_id: str,
    expected_plan_hash: str,
    promote_report_path: Path,
    expected_promote_hash: str,
    final_audit_report_path: Path,
    expected_final_audit_hash: str,
    dry_run: bool = True,
    confirm_event_write: bool = False,
    sample_only: bool = False,
    sample_trade_date: str | None = None,
    checkpoint_path: Path | None = None,
) -> StockDailyTrendChannelRunlessEventReport:
    """Register exact dates, then report bounded materialization/check events."""

    started_at = time.perf_counter()
    plan = plan_stock_daily_trend_channel_runless_events(
        instance=instance,
        plan_report_path=plan_report_path,
        expected_plan_id=expected_plan_id,
        expected_plan_hash=expected_plan_hash,
        promote_report_path=promote_report_path,
        expected_promote_hash=expected_promote_hash,
        final_audit_report_path=final_audit_report_path,
        expected_final_audit_hash=expected_final_audit_hash,
    )
    normalized_checkpoint = (
        _validated_control_file(
            checkpoint_path,
            plan=plan.history_plan,
            label="event checkpoint",
        )
        if checkpoint_path is not None
        else None
    )
    if dry_run:
        return StockDailyTrendChannelRunlessEventReport(
            mode="dry-run",
            plan=plan,
            confirmed=False,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
        )
    if not confirm_event_write:
        raise StockDailyTrendChannelRunlessEventError(
            "event apply requires confirm_event_write=True"
        )
    if plan.should_stop:
        raise StockDailyTrendChannelRunlessEventError(
            "event apply is blocked by active runs or an event-count bound"
        )
    if sample_only:
        if sample_trade_date not in plan.recent_check_trade_dates:
            raise StockDailyTrendChannelRunlessEventError(
                "event sample must select one recent check trade date"
            )
        selected_dates = (str(sample_trade_date),)
    else:
        selected_dates = plan.history_plan.trade_dates
    selected = set(selected_dates)
    missing_registered = tuple(
        value for value in plan.missing_registered_trade_dates if value in selected
    )
    if missing_registered:
        instance.add_dynamic_partitions(
            cn_a_stock_daily_trend_channel_trade_days.name,
            list(missing_registered),
        )

    existing_materializations = set(plan.existing_materializations)
    existing_checks = set(plan.existing_ready_checks)
    files_by_key = {(value.asset_key, value.trade_date): value for value in plan.files}
    reported_materializations = 0
    reported_checks = 0
    skipped_materializations = 0
    skipped_checks = 0
    event_count = 0
    for value in plan.files:
        if value.trade_date not in selected:
            continue
        identity = _materialization_id(value)
        if identity in existing_materializations:
            skipped_materializations += 1
            continue
        _report_materialization(instance=instance, plan=plan, file=value)
        existing_materializations.add(identity)
        reported_materializations += 1
        event_count += 1
        _write_event_progress(
            normalized_checkpoint,
            plan=plan,
            event_count=event_count,
            last_identity=identity,
        )

    selected_check_dates = tuple(
        value for value in plan.recent_check_trade_dates if value in selected
    )
    for spec in _check_specs():
        for trade_date in selected_check_dates:
            identity = _check_id(spec, trade_date)
            if identity in existing_checks:
                skipped_checks += 1
                continue
            _report_check(
                instance=instance,
                plan=plan,
                file=files_by_key[(spec.asset_key, trade_date)],
                spec=spec,
            )
            existing_checks.add(identity)
            reported_checks += 1
            event_count += 1
            _write_event_progress(
                normalized_checkpoint,
                plan=plan,
                event_count=event_count,
                last_identity=identity,
            )
    report = StockDailyTrendChannelRunlessEventReport(
        mode="sample" if sample_only else "apply",
        plan=plan,
        confirmed=True,
        selected_trade_dates=selected_dates,
        registered_partition_count=len(missing_registered),
        reported_materialization_count=reported_materializations,
        reported_check_count=reported_checks,
        skipped_materialization_count=skipped_materializations,
        skipped_check_count=skipped_checks,
        elapsed_ms=(time.perf_counter() - started_at) * 1000,
    )
    if normalized_checkpoint is not None:
        _write_json_atomic(normalized_checkpoint, report.to_dict())
    return report


def final_audit_stock_daily_trend_channel_runless_events(
    **kwargs: Any,
) -> StockDailyTrendChannelRunlessEventPlan:
    """Require exact registration, materialization and recent check completion."""

    plan = plan_stock_daily_trend_channel_runless_events(**kwargs)
    if (
        plan.should_stop
        or plan.planned_registration_count
        or plan.planned_materialization_count
        or plan.planned_check_count
    ):
        raise StockDailyTrendChannelRunlessEventError(
            "event final audit found missing registrations or events"
        )
    return plan


def _load_verified_formal_files(
    *,
    history_plan: StockDailyTrendChannelHistoryPlan,
    promote_report_path: Path,
    expected_promote_hash: str,
    final_audit_report_path: Path,
    expected_final_audit_hash: str,
) -> tuple[StockDailyTrendChannelEventFile, ...]:
    promote = _load_json(promote_report_path, label="trend-channel promotion")
    promote_payload = {
        key: value for key, value in promote.items() if key != "promote_hash"
    }
    if (
        promote.get("phase") != PROMOTE_PHASE
        or promote.get("mode") != "apply"
        or promote.get("plan_id") != history_plan.plan_id
        or promote.get("plan_hash") != history_plan.plan_hash
        or promote.get("should_stop") is not False
        or promote.get("promote_hash") != expected_promote_hash
        or _hash_payload(promote_payload) != expected_promote_hash
    ):
        raise StockDailyTrendChannelRunlessEventError(
            "promotion report is not green for event backfill"
        )
    final_audit = _load_json(
        final_audit_report_path,
        label="trend-channel final audit",
    )
    final_payload = {
        key: value for key, value in final_audit.items() if key != "final_audit_hash"
    }
    if (
        final_audit.get("phase") != FINAL_AUDIT_PHASE
        or final_audit.get("plan_id") != history_plan.plan_id
        or final_audit.get("plan_hash") != history_plan.plan_hash
        or final_audit.get("promote_hash") != expected_promote_hash
        or final_audit.get("should_stop") is not False
        or final_audit.get("final_audit_hash") != expected_final_audit_hash
        or _hash_payload(final_payload) != expected_final_audit_hash
    ):
        raise StockDailyTrendChannelRunlessEventError(
            "final physical audit is not green for event backfill"
        )
    raw_files = promote.get("files")
    if not isinstance(raw_files, list):
        raise StockDailyTrendChannelRunlessEventError(
            "promotion report file scope is missing"
        )
    files: list[StockDailyTrendChannelEventFile] = []
    observed: set[tuple[str, str]] = set()
    for value in raw_files:
        if not isinstance(value, Mapping):
            raise StockDailyTrendChannelRunlessEventError(
                "promotion file record is invalid"
            )
        asset_key = str(value.get("asset_key", ""))
        trade_date = str(value.get("trade_date", ""))
        key = (asset_key, trade_date)
        if key in observed:
            raise StockDailyTrendChannelRunlessEventError(
                f"duplicate promotion file identity: {key}"
            )
        observed.add(key)
        path = Path(str(value.get("path", ""))).resolve()
        expected_path = (
            gold_stock_daily_trend_channel_path(history_plan.lake_root, trade_date)
            if asset_key == RESULT_ASSET_KEY
            else gold_stock_daily_trend_channel_state_path(
                history_plan.lake_root,
                trade_date,
            )
        )
        expected_sha = str(value.get("sha256", ""))
        expected_size = int(value.get("size_bytes", 0))
        row_count = int(value.get("row_count", 0))
        if (
            path != expected_path
            or not path.is_file()
            or path.stat().st_size != expected_size
            or row_count <= 0
            or _file_sha256(path) != expected_sha
        ):
            raise StockDailyTrendChannelRunlessEventError(
                f"formal file changed after final audit: {path}"
            )
        files.append(
            StockDailyTrendChannelEventFile(
                asset_key=asset_key,
                trade_date=trade_date,
                path=path,
                row_count=row_count,
                size_bytes=expected_size,
                sha256=expected_sha,
            )
        )
    expected = {
        (asset_key, trade_date)
        for trade_date in history_plan.trade_dates
        for asset_key in (RESULT_ASSET_KEY, STATE_ASSET_KEY)
    }
    if observed != expected:
        raise StockDailyTrendChannelRunlessEventError(
            "promotion file scope differs from the approved history scope"
        )
    return tuple(sorted(files, key=lambda item: (item.trade_date, item.asset_key)))


def _check_specs() -> tuple[StockDailyTrendChannelEventCheck, ...]:
    return (
        StockDailyTrendChannelEventCheck(
            asset_key=RESULT_ASSET_KEY,
            check_name=RESULT_CONTRACT_CHECK,
            check_scope=CheckScope.SCHEMA,
        ),
        StockDailyTrendChannelEventCheck(
            asset_key=RESULT_ASSET_KEY,
            check_name=INPUT_COVERAGE_CHECK,
            check_scope=CheckScope.RECONCILIATION,
        ),
        StockDailyTrendChannelEventCheck(
            asset_key=STATE_ASSET_KEY,
            check_name=STATE_CONTRACT_CHECK,
            check_scope=CheckScope.SCHEMA,
        ),
    )


def _report_materialization(
    *,
    instance: Any,
    plan: StockDailyTrendChannelRunlessEventPlan,
    file: StockDailyTrendChannelEventFile,
) -> None:
    observed_columns = tuple(
        column.name
        for column in (
            GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA
            if file.asset_key == RESULT_ASSET_KEY
            else GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA
        )
    )
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=dg.AssetKey(file.asset_key),
            partition=file.trade_date,
            metadata=build_materialization_metadata(
                uri=file.path,
                row_count=file.row_count,
                observed_columns=observed_columns,
                extra_metadata={
                    "source_method": "stock_daily_trend_channel_direct_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_history",
                    "plan_id": plan.history_plan.plan_id,
                    "plan_hash": plan.history_plan.plan_hash,
                    "promote_hash": plan.promote_hash,
                    "final_audit_hash": plan.final_audit_hash,
                    "sha256": file.sha256,
                    "formula_version": FORMULA_VERSION,
                },
            ),
        )
    )


def _report_check(
    *,
    instance: Any,
    plan: StockDailyTrendChannelRunlessEventPlan,
    file: StockDailyTrendChannelEventFile,
    spec: StockDailyTrendChannelEventCheck,
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
                check_scope=spec.check_scope,
                checked_row_count=file.row_count,
                failed_row_count=0,
                file_path=file.path,
                extra_metadata={
                    "reason_code": "ready",
                    "source_method": "stock_daily_trend_channel_direct_bootstrap",
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_plus_latest",
                    "plan_id": plan.history_plan.plan_id,
                    "plan_hash": plan.history_plan.plan_hash,
                    "promote_hash": plan.promote_hash,
                    "final_audit_hash": plan.final_audit_hash,
                    "formula_version": FORMULA_VERSION,
                },
            ),
        )
    )


def _materialization_records(
    instance: Any,
    *,
    asset_key: str,
    trade_dates: Sequence[str],
) -> dict[str, object]:
    if not trade_dates:
        return {}
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key),
            asset_partitions=list(trade_dates),
        ),
        limit=max(1, len(trade_dates)),
    )
    return {
        str(record.partition_key): record
        for record in result.records
        if getattr(record, "partition_key", None) is not None
    }


def _latest_materialization(
    instance: Any,
    *,
    asset_key: str,
    trade_date: str,
) -> object:
    record = _materialization_records(
        instance,
        asset_key=asset_key,
        trade_dates=(trade_date,),
    ).get(trade_date)
    if record is None:
        raise StockDailyTrendChannelRunlessEventError(
            f"missing target materialization: {asset_key}:{trade_date}"
        )
    return record


def _existing_ready_checks(
    instance: Any,
    *,
    specs: Sequence[StockDailyTrendChannelEventCheck],
    trade_dates: Sequence[str],
) -> tuple[str, ...]:
    materializations_by_asset = {
        asset_key: _materialization_records(
            instance,
            asset_key=asset_key,
            trade_dates=trade_dates,
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


def _active_run_count(instance: Any) -> int:
    return len(
        instance.get_runs(
            filters=dg.RunsFilter(statuses=list(_ACTIVE_RUN_STATUSES)),
            limit=1,
        )
    )


def _materialization_id(value: StockDailyTrendChannelEventFile) -> str:
    return f"{value.asset_key}|{value.trade_date}"


def _check_id(
    spec: StockDailyTrendChannelEventCheck,
    trade_date: str,
) -> str:
    return f"{spec.asset_key}|{spec.check_name}|{trade_date}"


def _write_event_progress(
    path: Path | None,
    *,
    plan: StockDailyTrendChannelRunlessEventPlan,
    event_count: int,
    last_identity: str,
) -> None:
    if path is None or event_count % EVENT_PROGRESS_INTERVAL:
        return
    _write_json_atomic(
        Path(path),
        {
            "schema_version": 1,
            "plan_id": plan.history_plan.plan_id,
            "plan_hash": plan.history_plan.plan_hash,
            "reported_event_count": event_count,
            "last_identity": last_identity,
        },
    )


def write_stock_daily_trend_channel_runless_event_report(
    report: StockDailyTrendChannelRunlessEventPlan
    | StockDailyTrendChannelRunlessEventReport,
    output_path: Path,
) -> None:
    history_plan = (
        report.history_plan
        if isinstance(report, StockDailyTrendChannelRunlessEventPlan)
        else report.plan.history_plan
    )
    normalized = _validated_control_file(
        output_path,
        plan=history_plan,
        label="event review report",
    )
    _write_json_atomic(normalized, report.to_dict())


def _validated_control_file(
    path: Path,
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    label: str,
) -> Path:
    normalized = Path(path).resolve()
    for root, root_label in (
        (plan.lake_root.resolve(), "formal Lake"),
        (plan.staging_root.resolve(), "candidate staging"),
    ):
        if normalized == root or normalized.is_relative_to(root):
            raise StockDailyTrendChannelRunlessEventError(
                f"{label} must remain outside {root_label}"
            )
    return normalized


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StockDailyTrendChannelRunlessEventError(
            f"{label} is unreadable: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise StockDailyTrendChannelRunlessEventError(f"{label} must be an object")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    normalized = Path(path).resolve()
    normalized.parent.mkdir(parents=True, exist_ok=True)
    pending = normalized.with_name(f".{normalized.name}.pending-{uuid.uuid4().hex}")
    pending.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(pending, normalized)


__all__ = [
    "StockDailyTrendChannelRunlessEventError",
    "StockDailyTrendChannelRunlessEventPlan",
    "StockDailyTrendChannelRunlessEventReport",
    "final_audit_stock_daily_trend_channel_runless_events",
    "plan_stock_daily_trend_channel_runless_events",
    "report_stock_daily_trend_channel_runless_events",
    "write_stock_daily_trend_channel_runless_event_report",
]
