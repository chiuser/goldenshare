"""Frozen and resumable runless events for ETF daily Bootstrap."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.etf_daily_bootstrap_apply import (
    EtfDailyBootstrapCheckpointEntry,
    append_checkpoint,
    load_checkpoint,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_audit import validate_report_hash
from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    EtfDailySilverBootstrapPlan,
    atomic_write_json,
    hash_payload,
    load_json,
    write_immutable_json,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_BOOTSTRAP_CHECK_EVENT_TAIL_DAYS,
    RAW_FUND_ADJ_CHECKS,
    RAW_FUND_DAILY_CHECKS,
    RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
    RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
    SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
    SILVER_ETF_DAILY_ASSET_KEY,
    SILVER_ETF_DAILY_BLOCKING_CHECKS,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)

_ACTIVE_RUN_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class EtfDailyBootstrapEventsError(ValueError):
    """Raised before an unsafe runless event operation."""


@dataclass(frozen=True, slots=True)
class EtfDailyMaterializationEventSpec:
    asset_key: str
    trade_date: str
    target_path: str
    row_count: int
    content_hash: str
    metadata: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "metadata": dict(self.metadata)}


@dataclass(frozen=True, slots=True)
class EtfDailyCheckEventSpec:
    asset_key: str
    check_name: str
    trade_date: str
    target_path: str
    row_count: int
    metadata: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "metadata": dict(self.metadata)}


@dataclass(frozen=True, slots=True)
class EtfDailyBootstrapEventPlan:
    schema_version: str
    operation_id: str
    created_at: str
    silver_plan_hash: str
    physical_report_path: str
    physical_report_hash: str
    materializations: tuple[EtfDailyMaterializationEventSpec, ...]
    checks: tuple[EtfDailyCheckEventSpec, ...]
    existing_materializations: tuple[str, ...]
    pending_materializations: tuple[str, ...]
    conflicting_materializations: tuple[str, ...]
    existing_checks: tuple[str, ...]
    pending_checks: tuple[str, ...]
    conflicting_checks: tuple[str, ...]
    active_run_count: int
    event_plan_hash: str

    @property
    def should_stop(self) -> bool:
        return bool(
            self.active_run_count
            or self.conflicting_materializations
            or self.conflicting_checks
        )

    def hash_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "created_at": self.created_at,
            "silver_plan_hash": self.silver_plan_hash,
            "physical_report_path": self.physical_report_path,
            "physical_report_hash": self.physical_report_hash,
            "materializations": [item.to_dict() for item in self.materializations],
            "checks": [item.to_dict() for item in self.checks],
            "existing_materializations": list(self.existing_materializations),
            "pending_materializations": list(self.pending_materializations),
            "conflicting_materializations": list(self.conflicting_materializations),
            "existing_checks": list(self.existing_checks),
            "pending_checks": list(self.pending_checks),
            "conflicting_checks": list(self.conflicting_checks),
            "active_run_count": self.active_run_count,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.hash_payload(),
            "event_plan_hash": self.event_plan_hash,
            "should_stop": self.should_stop,
            "writes": {"lake_files": 0, "dynamic_partitions": 0, "sensor_changes": 0},
        }


def build_event_plan(
    *,
    instance: dg.DagsterInstance,
    silver_plan: EtfDailySilverBootstrapPlan,
    physical_report_path: Path,
    created_at: datetime | None = None,
) -> EtfDailyBootstrapEventPlan:
    report = _load_physical_report(
        silver_plan=silver_plan,
        physical_report_path=physical_report_path,
    )
    materializations = _materialization_specs(report)
    recent_dates = tuple(sorted(silver_plan.trade_dates))[
        -ETF_DAILY_BOOTSTRAP_CHECK_EVENT_TAIL_DAYS:
    ]
    checks = _check_specs(materializations, recent_dates=recent_dates)
    records = _load_materializations(instance, materializations)
    existing_mats: list[str] = []
    pending_mats: list[str] = []
    conflicting_mats: list[str] = []
    for spec in materializations:
        identity = _materialization_identity(spec)
        record = records.get((spec.asset_key, spec.trade_date))
        if record is None:
            pending_mats.append(identity)
        elif _materialization_matches(record, spec):
            existing_mats.append(identity)
        else:
            conflicting_mats.append(identity)
    check_records = _load_checks(instance, checks)
    existing_checks: list[str] = []
    pending_checks: list[str] = []
    conflicting_checks: list[str] = []
    for spec in checks:
        identity = _check_identity(spec)
        record = check_records.get((spec.asset_key, spec.check_name, spec.trade_date))
        materialization = records.get((spec.asset_key, spec.trade_date))
        if record is None:
            pending_checks.append(identity)
        elif materialization is not None and _check_matches(
            record,
            target_storage_id=int(materialization.storage_id),
        ):
            existing_checks.append(identity)
        else:
            conflicting_checks.append(identity)
    draft = EtfDailyBootstrapEventPlan(
        schema_version="etf_daily_bootstrap_events_v1",
        operation_id=silver_plan.operation_id,
        created_at=(created_at or datetime.now().astimezone()).isoformat(),
        silver_plan_hash=silver_plan.silver_plan_hash,
        physical_report_path=str(physical_report_path),
        physical_report_hash=str(report["report_hash"]),
        materializations=materializations,
        checks=checks,
        existing_materializations=tuple(existing_mats),
        pending_materializations=tuple(pending_mats),
        conflicting_materializations=tuple(conflicting_mats),
        existing_checks=tuple(existing_checks),
        pending_checks=tuple(pending_checks),
        conflicting_checks=tuple(conflicting_checks),
        active_run_count=_active_run_count(instance),
        event_plan_hash="",
    )
    plan = replace(draft, event_plan_hash=hash_payload(draft.hash_payload()))
    _validate_event_plan_scope(plan)
    return plan


def write_event_plan(plan: EtfDailyBootstrapEventPlan, path: Path) -> None:
    write_immutable_json(path, plan.to_dict())


def load_event_plan(
    path: Path, *, expected_plan_hash: str
) -> EtfDailyBootstrapEventPlan:
    payload = load_json(path, label="ETF daily event plan")
    if payload.get("event_plan_hash") != expected_plan_hash:
        raise EtfDailyBootstrapEventsError("expected event plan hash does not match")
    try:
        plan = EtfDailyBootstrapEventPlan(
            schema_version=str(payload["schema_version"]),
            operation_id=str(payload["operation_id"]),
            created_at=str(payload["created_at"]),
            silver_plan_hash=str(payload["silver_plan_hash"]),
            physical_report_path=str(payload["physical_report_path"]),
            physical_report_hash=str(payload["physical_report_hash"]),
            materializations=tuple(
                _materialization_spec_from_payload(item)
                for item in payload["materializations"]
            ),
            checks=tuple(_check_spec_from_payload(item) for item in payload["checks"]),
            existing_materializations=tuple(payload["existing_materializations"]),
            pending_materializations=tuple(payload["pending_materializations"]),
            conflicting_materializations=tuple(payload["conflicting_materializations"]),
            existing_checks=tuple(payload["existing_checks"]),
            pending_checks=tuple(payload["pending_checks"]),
            conflicting_checks=tuple(payload["conflicting_checks"]),
            active_run_count=int(payload["active_run_count"]),
            event_plan_hash=str(payload["event_plan_hash"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EtfDailyBootstrapEventsError("event plan is structurally invalid") from error
    if (
        plan.schema_version != "etf_daily_bootstrap_events_v1"
        or hash_payload(plan.hash_payload()) != expected_plan_hash
    ):
        raise EtfDailyBootstrapEventsError("event plan payload has drifted")
    _validate_event_plan_scope(plan)
    return plan


def apply_events(
    *,
    instance: dg.DagsterInstance,
    plan: EtfDailyBootstrapEventPlan,
    checkpoint_path: Path,
    output_path: Path,
    confirm_events_apply: bool,
) -> dict[str, object]:
    if not confirm_events_apply:
        raise EtfDailyBootstrapEventsError("events apply confirmation is required")
    if plan.should_stop:
        raise EtfDailyBootstrapEventsError("event plan contains an active run or conflict")
    _revalidate_physical_report(plan)
    if _active_run_count(instance):
        raise EtfDailyBootstrapEventsError("Dagster has an active run; events apply stopped")
    checkpoint = load_checkpoint(checkpoint_path)
    if any(
        item.phase == "events" and item.phase_plan_hash != plan.event_plan_hash
        for item in checkpoint
    ):
        raise EtfDailyBootstrapEventsError("event checkpoint belongs to another plan")
    materialization_records = _load_materializations(instance, plan.materializations)
    reported_materializations = 0
    for spec in plan.materializations:
        record = materialization_records.get((spec.asset_key, spec.trade_date))
        if record is not None:
            if not _materialization_matches(record, spec):
                raise EtfDailyBootstrapEventsError(
                    f"materialization conflict: {_materialization_identity(spec)}"
                )
            _ensure_event_checkpoint(
                checkpoint_path,
                plan_hash=plan.event_plan_hash,
                asset_key=spec.asset_key,
                trade_date=spec.trade_date,
                target_path=f"dagster://materialization/{spec.asset_key}",
                content_hash=spec.content_hash,
                row_count=spec.row_count,
                write_mode="reuse_equivalent",
            )
            continue
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=dg.AssetKey(spec.asset_key),
                partition=spec.trade_date,
                metadata=dict(spec.metadata),
            )
        )
        record = _load_materializations(instance, (spec,)).get(
            (spec.asset_key, spec.trade_date)
        )
        if record is None or not _materialization_matches(record, spec):
            raise EtfDailyBootstrapEventsError("materialization post-write verification failed")
        materialization_records[(spec.asset_key, spec.trade_date)] = record
        reported_materializations += 1
        _ensure_event_checkpoint(
            checkpoint_path,
            plan_hash=plan.event_plan_hash,
            asset_key=spec.asset_key,
            trade_date=spec.trade_date,
            target_path=f"dagster://materialization/{spec.asset_key}",
            content_hash=spec.content_hash,
            row_count=spec.row_count,
            write_mode="write_new",
        )
    reported_checks = 0
    for spec in plan.checks:
        materialization = materialization_records[(spec.asset_key, spec.trade_date)]
        existing = _load_checks(instance, (spec,)).get(
            (spec.asset_key, spec.check_name, spec.trade_date)
        )
        if existing is not None:
            if not _check_matches(existing, target_storage_id=int(materialization.storage_id)):
                raise EtfDailyBootstrapEventsError(
                    f"asset check conflict: {_check_identity(spec)}"
                )
            mode = "reuse_equivalent"
        else:
            target = AssetCheckEvaluationTargetMaterializationData(
                storage_id=int(materialization.storage_id),
                run_id=materialization.run_id,
                timestamp=materialization.timestamp,
            )
            instance.report_runless_asset_event(
                dg.AssetCheckEvaluation(
                    asset_key=dg.AssetKey(spec.asset_key),
                    check_name=spec.check_name,
                    passed=True,
                    blocking=True,
                    partition=spec.trade_date,
                    target_materialization_data=target,
                    metadata=dict(spec.metadata),
                )
            )
            written = _load_checks(instance, (spec,)).get(
                (spec.asset_key, spec.check_name, spec.trade_date)
            )
            if written is None or not _check_matches(
                written, target_storage_id=int(materialization.storage_id)
            ):
                raise EtfDailyBootstrapEventsError("asset check post-write verification failed")
            mode = "write_new"
            reported_checks += 1
        _ensure_event_checkpoint(
            checkpoint_path,
            plan_hash=plan.event_plan_hash,
            asset_key=spec.asset_key,
            trade_date=spec.trade_date,
            target_path=f"dagster://asset-check/{spec.asset_key}/{spec.check_name}",
            content_hash=hash_payload(spec.to_dict()),
            row_count=spec.row_count,
            write_mode=mode,
        )
    payload: dict[str, object] = {
        "schema_version": "etf_daily_events_apply_v1",
        "event_plan_hash": plan.event_plan_hash,
        "reported_materialization_count": reported_materializations,
        "reported_check_count": reported_checks,
        "materialization_count": len(plan.materializations),
        "blocking_check_count": len(plan.checks),
        "lake_files_written": 0,
        "dynamic_partitions_written": 0,
        "sensor_changes": 0,
    }
    payload["report_hash"] = hash_payload(payload)
    atomic_write_json(output_path, payload)
    return payload


def post_audit_events(
    *,
    instance: dg.DagsterInstance,
    plan: EtfDailyBootstrapEventPlan,
    output_path: Path,
) -> dict[str, object]:
    _revalidate_physical_report(plan)
    materializations = _load_materializations(instance, plan.materializations)
    checks = _load_checks(instance, plan.checks)
    failures: list[str] = []
    for spec in plan.materializations:
        record = materializations.get((spec.asset_key, spec.trade_date))
        if record is None or not _materialization_matches(record, spec):
            failures.append(_materialization_identity(spec))
    for spec in plan.checks:
        materialization = materializations.get((spec.asset_key, spec.trade_date))
        record = checks.get((spec.asset_key, spec.check_name, spec.trade_date))
        if (
            materialization is None
            or record is None
            or not _check_matches(record, target_storage_id=int(materialization.storage_id))
        ):
            failures.append(_check_identity(spec))
    payload: dict[str, object] = {
        "schema_version": "etf_daily_events_post_audit_v1",
        "event_plan_hash": plan.event_plan_hash,
        "materialization_count": len(plan.materializations),
        "blocking_check_count": len(plan.checks),
        "failure_count": len(failures),
        "failures": failures,
        "passed": not failures,
        "lake_files_written": 0,
        "dynamic_partitions_written": 0,
        "sensor_changes": 0,
    }
    payload["report_hash"] = hash_payload(payload)
    write_immutable_json(output_path, payload)
    if failures:
        raise EtfDailyBootstrapEventsError("event post-audit did not close all facts")
    return payload


def _load_physical_report(
    *,
    silver_plan: EtfDailySilverBootstrapPlan,
    physical_report_path: Path,
) -> dict[str, Any]:
    report = load_json(physical_report_path, label="ETF daily physical post-audit")
    validate_report_hash(report)
    if (
        report.get("passed") is not True
        or report.get("silver_plan_hash") != silver_plan.silver_plan_hash
        or int(report.get("dagster_events_written", -1)) != 0
    ):
        raise EtfDailyBootstrapEventsError("physical post-audit is not green")
    evidence = report.get("file_evidence")
    if not isinstance(evidence, list):
        raise EtfDailyBootstrapEventsError("physical post-audit has no file evidence")
    expected = {
        (asset_key, trade_date)
        for trade_date in silver_plan.trade_dates
        for asset_key in (
            RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
            RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
            SILVER_ETF_DAILY_ASSET_KEY,
            SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
        )
    }
    observed = {
        (str(item.get("asset_key")), str(item.get("trade_date")))
        for item in evidence
        if isinstance(item, Mapping)
    }
    if observed != expected or len(evidence) != len(expected):
        raise EtfDailyBootstrapEventsError("physical file evidence scope is incomplete")
    return report


def _revalidate_physical_report(plan: EtfDailyBootstrapEventPlan) -> None:
    report = load_json(Path(plan.physical_report_path), label="ETF daily physical post-audit")
    validate_report_hash(report)
    if (
        report.get("report_hash") != plan.physical_report_hash
        or report.get("passed") is not True
        or report.get("silver_plan_hash") != plan.silver_plan_hash
    ):
        raise EtfDailyBootstrapEventsError("physical evidence changed after event plan")


def _materialization_specs(
    report: Mapping[str, Any],
) -> tuple[EtfDailyMaterializationEventSpec, ...]:
    evidence = report.get("file_evidence")
    if not isinstance(evidence, list):
        raise EtfDailyBootstrapEventsError("physical report has no file evidence")
    specs: list[EtfDailyMaterializationEventSpec] = []
    for item in evidence:
        if not isinstance(item, Mapping) or item.get("passed") is not True:
            raise EtfDailyBootstrapEventsError("physical file evidence is invalid")
        asset_key = str(item["asset_key"])
        source_fields = tuple(str(value) for value in item["source_fields"])
        extra = {
            key: item[key]
            for key in (
                "source_row_count",
                "normalized_row_count",
                "raw_row_count",
                "selected_row_count",
                "rejected_row_count",
                "written_row_count",
                "reject_reason_counts",
                "basic_reference",
                "basic_reference_fingerprint",
                "basic_raw_snapshot_hash",
                "basic_silver_content_hash",
                "basic_raw_uri",
                "basic_silver_uri",
                "content_hash",
            )
            if key in item
        }
        metadata = build_materialization_metadata(
            uri=str(item["target_path"]),
            row_count=int(item["row_count"]),
            observed_columns=source_fields,
            extra_metadata=extra,
        )
        specs.append(
            EtfDailyMaterializationEventSpec(
                asset_key=asset_key,
                trade_date=str(item["trade_date"]),
                target_path=str(item["target_path"]),
                row_count=int(item["row_count"]),
                content_hash=str(item["content_hash"]),
                metadata=metadata,
            )
        )
    return tuple(specs)


def _check_specs(
    materializations: Sequence[EtfDailyMaterializationEventSpec],
    *,
    recent_dates: Sequence[str],
) -> tuple[EtfDailyCheckEventSpec, ...]:
    checks_by_asset = {
        RAW_TUSHARE_FUND_DAILY_ASSET_KEY: RAW_FUND_DAILY_CHECKS,
        RAW_TUSHARE_FUND_ADJ_ASSET_KEY: RAW_FUND_ADJ_CHECKS,
        SILVER_ETF_DAILY_ASSET_KEY: SILVER_ETF_DAILY_BLOCKING_CHECKS,
        SILVER_ETF_ADJ_FACTOR_ASSET_KEY: SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
    }
    recent = set(recent_dates)
    specs: list[EtfDailyCheckEventSpec] = []
    for materialization in materializations:
        if materialization.trade_date not in recent:
            continue
        for check_name in checks_by_asset[materialization.asset_key]:
            specs.append(
                EtfDailyCheckEventSpec(
                    asset_key=materialization.asset_key,
                    check_name=check_name,
                    trade_date=materialization.trade_date,
                    target_path=materialization.target_path,
                    row_count=materialization.row_count,
                    metadata=build_check_metadata(
                        check_scope=CheckScope.RECONCILIATION,
                        checked_row_count=materialization.row_count,
                        failed_row_count=0,
                        file_path=materialization.target_path,
                        extra_metadata={
                            "reason_code": "ready",
                            "source_method": "tushare_etf_daily_direct_bootstrap",
                        },
                    ),
                )
            )
    return tuple(specs)


def _load_materializations(
    instance: dg.DagsterInstance,
    specs: Sequence[EtfDailyMaterializationEventSpec],
) -> dict[tuple[str, str], object]:
    grouped: dict[str, set[str]] = {}
    for spec in specs:
        grouped.setdefault(spec.asset_key, set()).add(spec.trade_date)
    result: dict[tuple[str, str], object] = {}
    for asset_key, partitions in grouped.items():
        limit = max(1_000, len(partitions) * 4)
        records = instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(asset_key),
                asset_partitions=sorted(partitions),
            ),
            limit=limit,
        ).records
        for record in records:
            partition = str(getattr(record, "partition_key", "") or "")
            if partition in partitions:
                result.setdefault((asset_key, partition), record)
        if len(records) == limit and any(
            (asset_key, partition) not in result for partition in partitions
        ):
            raise EtfDailyBootstrapEventsError("materialization history was truncated")
    return result


def _load_checks(
    instance: dg.DagsterInstance,
    specs: Sequence[EtfDailyCheckEventSpec],
) -> dict[tuple[str, str, str], object]:
    grouped: dict[tuple[str, str], set[str]] = {}
    for spec in specs:
        grouped.setdefault((spec.asset_key, spec.check_name), set()).add(spec.trade_date)
    result: dict[tuple[str, str, str], object] = {}
    for (asset_key, check_name), partitions in grouped.items():
        limit = max(500, len(partitions) * 10)
        records = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(dg.AssetKey(asset_key), check_name),
            limit=limit,
        )
        for record in records:
            partition = str(getattr(record, "partition", "") or "")
            if partition in partitions:
                result.setdefault((asset_key, check_name, partition), record)
        if len(records) == limit and any(
            (asset_key, check_name, partition) not in result for partition in partitions
        ):
            raise EtfDailyBootstrapEventsError("asset check history was truncated")
    return result


def _active_run_count(instance: dg.DagsterInstance) -> int:
    return len(
        instance.get_runs(
            filters=dg.RunsFilter(statuses=list(_ACTIVE_RUN_STATUSES)),
            limit=1,
        )
    )


def _materialization_matches(record: object, spec: EtfDailyMaterializationEventSpec) -> bool:
    materialization = getattr(record, "asset_materialization", None)
    return bool(
        materialization is not None
        and _metadata_contains(materialization.metadata, spec.metadata)
    )


def _check_matches(record: object, *, target_storage_id: int) -> bool:
    event = getattr(record, "event", None)
    dagster_event = getattr(event, "dagster_event", None) if event else None
    evaluation = (
        getattr(dagster_event, "event_specific_data", None)
        if dagster_event is not None
        else None
    )
    target = getattr(evaluation, "target_materialization_data", None)
    return bool(
        evaluation is not None
        and bool(getattr(evaluation, "passed", False))
        and bool(getattr(evaluation, "blocking", False))
        and target is not None
        and int(target.storage_id) == target_storage_id
    )


def _metadata_contains(
    actual: Mapping[str, object], expected: Mapping[str, object]
) -> bool:
    return all(_metadata_scalar(actual.get(key)) == _metadata_scalar(value) for key, value in expected.items())


def _metadata_scalar(value: object) -> object:
    scalar = getattr(value, "value", value)
    if isinstance(scalar, Mapping):
        return {str(key): _metadata_scalar(item) for key, item in scalar.items()}
    if isinstance(scalar, Sequence) and not isinstance(scalar, (str, bytes)):
        return [_metadata_scalar(item) for item in scalar]
    return scalar


def _materialization_identity(spec: EtfDailyMaterializationEventSpec) -> str:
    return f"{spec.asset_key}|{spec.trade_date}"


def _check_identity(spec: EtfDailyCheckEventSpec) -> str:
    return f"{spec.asset_key}|{spec.check_name}|{spec.trade_date}"


def _validate_event_plan_scope(plan: EtfDailyBootstrapEventPlan) -> None:
    materialization_ids = tuple(
        _materialization_identity(spec) for spec in plan.materializations
    )
    check_ids = tuple(_check_identity(spec) for spec in plan.checks)
    if len(materialization_ids) != len(set(materialization_ids)) or len(check_ids) != len(
        set(check_ids)
    ):
        raise EtfDailyBootstrapEventsError("event plan has duplicate identities")
    dates = tuple(sorted({spec.trade_date for spec in plan.materializations}))
    expected_materializations = {
        f"{asset_key}|{trade_date}"
        for trade_date in dates
        for asset_key in (
            RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
            RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
            SILVER_ETF_DAILY_ASSET_KEY,
            SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
        )
    }
    materialization_states = (
        set(plan.existing_materializations),
        set(plan.pending_materializations),
        set(plan.conflicting_materializations),
    )
    expected_check_dates = set(dates[-ETF_DAILY_BOOTSTRAP_CHECK_EVENT_TAIL_DAYS:])
    expected_checks = {
        f"{asset_key}|{check_name}|{trade_date}"
        for trade_date in expected_check_dates
        for asset_key, names in (
            (RAW_TUSHARE_FUND_DAILY_ASSET_KEY, RAW_FUND_DAILY_CHECKS),
            (RAW_TUSHARE_FUND_ADJ_ASSET_KEY, RAW_FUND_ADJ_CHECKS),
            (SILVER_ETF_DAILY_ASSET_KEY, SILVER_ETF_DAILY_BLOCKING_CHECKS),
            (
                SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
                SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
            ),
        )
        for check_name in names
    }
    check_states = (
        set(plan.existing_checks),
        set(plan.pending_checks),
        set(plan.conflicting_checks),
    )
    if (
        not dates
        or set(materialization_ids) != expected_materializations
        or set(check_ids) != expected_checks
        or set.union(*materialization_states) != expected_materializations
        or any(left & right for left in materialization_states for right in materialization_states if left is not right)
        or set.union(*check_states) != expected_checks
        or any(left & right for left in check_states for right in check_states if left is not right)
        or plan.active_run_count < 0
        or not Path(plan.physical_report_path).is_absolute()
    ):
        raise EtfDailyBootstrapEventsError("event plan scope or state partition is invalid")


def _ensure_event_checkpoint(
    checkpoint_path: Path,
    *,
    plan_hash: str,
    asset_key: str,
    trade_date: str,
    target_path: str,
    content_hash: str,
    row_count: int,
    write_mode: Literal["write_new", "reuse_equivalent"],
) -> None:
    entry = EtfDailyBootstrapCheckpointEntry(
        phase_plan_hash=plan_hash,
        phase="events",
        asset_key=asset_key,
        trade_date=trade_date,
        target_path=target_path,
        content_hash=content_hash,
        row_count=row_count,
        write_mode=write_mode,
        completed_at=datetime.now().astimezone().isoformat(),
    )
    existing = next(
        (
            item
            for item in load_checkpoint(checkpoint_path)
            if item.phase == "events"
            and item.asset_key == asset_key
            and item.trade_date == trade_date
            and item.target_path == target_path
        ),
        None,
    )
    if existing is not None:
        if (
            existing.phase_plan_hash != plan_hash
            or existing.content_hash != content_hash
            or existing.row_count != row_count
        ):
            raise EtfDailyBootstrapEventsError("event checkpoint conflicts with current fact")
        return
    append_checkpoint(checkpoint_path, entry=entry)


def _materialization_spec_from_payload(
    value: Mapping[str, Any],
) -> EtfDailyMaterializationEventSpec:
    return EtfDailyMaterializationEventSpec(
        asset_key=str(value["asset_key"]),
        trade_date=str(value["trade_date"]),
        target_path=str(value["target_path"]),
        row_count=int(value["row_count"]),
        content_hash=str(value["content_hash"]),
        metadata=dict(value["metadata"]),
    )


def _check_spec_from_payload(value: Mapping[str, Any]) -> EtfDailyCheckEventSpec:
    return EtfDailyCheckEventSpec(
        asset_key=str(value["asset_key"]),
        check_name=str(value["check_name"]),
        trade_date=str(value["trade_date"]),
        target_path=str(value["target_path"]),
        row_count=int(value["row_count"]),
        metadata=dict(value["metadata"]),
    )


__all__ = [
    "EtfDailyBootstrapEventPlan",
    "EtfDailyBootstrapEventsError",
    "EtfDailyCheckEventSpec",
    "EtfDailyMaterializationEventSpec",
    "apply_events",
    "build_event_plan",
    "load_event_plan",
    "post_audit_events",
    "write_event_plan",
]
