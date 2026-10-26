"""Daily announcement rules and native partition-bound check evaluations."""

import json
import time
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    AnnouncementControl,
    announcement_file_fingerprint,
    assert_safe_announcement_path,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_CHECKS,
    AnnouncementError,
    announcement_file_settings_from_evidence,
)
from orchestrator.defs.anns_d_execution import verify_announcement_delivery
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.checks.anns_d_check_targets import (
    announcement_asset_is_executing,
    announcement_materialization,
    prepare_announcement_check_targets,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_anns_d_path,
)
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy
from orchestrator.defs.run_contracts.metadata import build_check_metadata

_TARGET_NOT_PROVIDED = object()
_CHECK_RULE_FAILURES = frozenset(
    {
        "announcement_materialization_missing",
        "announcement_file_missing",
        "announcement_file_schema",
        "announcement_file_contract",
        "announcement_evidence_metadata",
        "announcement_evidence_policy",
        "announcement_delivery_wrong_day",
        "announcement_delivery_missing",
        "announcement_delivery_incomplete",
        "announcement_delivery_row_count",
        "announcement_delivery_truncated",
        "announcement_different_run_delivery",
        "announcement_checkpoint_identity",
        "announcement_checkpoint_invalid",
    }
)


def _record_identity(record):
    metadata = record.asset_materialization.metadata
    identity = getattr(metadata.get("goldenshare/announcement_identity"), "value", None)
    if not isinstance(identity, Mapping):
        raise AnnouncementError("announcement_evidence_metadata")
    return identity


def _delivery_evidence(record, root, staging, day, control, *, reuse=False):
    identity = _record_identity(record)
    if identity.get("day") != day:
        raise AnnouncementError("announcement_delivery_wrong_day")
    path_value = record.asset_materialization.metadata.get(
        "goldenshare/announcement_checkpoint"
    )
    checkpoint_value = getattr(path_value, "value", None)
    if not isinstance(checkpoint_value, str):
        raise AnnouncementError("announcement_evidence_metadata")
    checkpoint_path = assert_safe_announcement_path(Path(checkpoint_value))
    permitted = staging / "anns_d"
    if permitted not in checkpoint_path.parents:
        raise AnnouncementError("announcement_checkpoint_outside_staging")
    settings = announcement_file_settings_from_evidence(identity)
    run_id = checkpoint_path.parent.name.removeprefix("run_id=")
    store = AnnouncementStore(root, staging, run_id, settings, control)
    if checkpoint_path != store.directory / "delivery.json":
        raise AnnouncementError("announcement_checkpoint_path_contract")
    try:
        checkpoint = AnnouncementCheckpoint(checkpoint_path, identity)
    except json.JSONDecodeError:
        raise AnnouncementError("announcement_checkpoint_invalid") from None
    delivery = checkpoint.document.get("delivery", {})
    if reuse:
        _validate_reused_capture(delivery, settings.page_size)
    for page in delivery.get("source_pages", []):
        path = assert_safe_announcement_path(Path(page["path"]))
        if permitted not in path.parents:
            raise AnnouncementError("announcement_source_page_outside_staging")
    return store, checkpoint


def _verify_reused_delivery_references(record, root, staging, day, control):
    """Prove an unselected successful delivery check still describes these bytes."""
    store, checkpoint = _delivery_evidence(
        record, root, staging, day, control, reuse=True
    )
    delivery = checkpoint.document.get("delivery")
    if not delivery or checkpoint.document.get("phase") != "promoted":
        raise AnnouncementError("announcement_delivery_missing")
    if announcement_file_fingerprint(store.target(day)) != delivery["fingerprint"]:
        raise AnnouncementError("announcement_delivery_file_changed")
    for page in delivery.get("source_pages", []):
        control.check()
        if announcement_file_fingerprint(page["path"]) != page["fingerprint"]:
            raise AnnouncementError("announcement_delivery_source_changed")


def _validate_reused_capture(delivery, page_size):
    """Validate v2 daily source references before reusing an earlier green check."""
    reason = "announcement_recovery_delivery_evidence"
    pages = delivery.get("source_pages")
    if (
        delivery.get("capture_complete") is not True
        or not isinstance(pages, list)
        or not pages
    ):
        raise AnnouncementError(reason)
    for key in ("page_count", "source_rows", "last_offset", "last_page_rows"):
        if type(delivery.get(key)) is not int or delivery[key] < 0:
            raise AnnouncementError(reason)
    last_rows = delivery["last_page_rows"]
    last_offset = (len(pages) - 1) * page_size
    if (
        delivery["page_count"] != len(pages)
        or last_rows >= page_size
        or delivery["last_offset"] != last_offset
        or delivery["source_rows"] != last_offset + last_rows
    ):
        raise AnnouncementError(reason)
    for index, page in enumerate(pages):
        if (
            not isinstance(page, Mapping)
            or not isinstance(page.get("path"), str)
            or not isinstance(page.get("fingerprint"), Mapping)
            or not page["fingerprint"]
            or type(page.get("offset")) is not int
            or page["offset"] != index * page_size
            or type(page.get("rows")) is not int
            or page["rows"] != (last_rows if index == len(pages) - 1 else page_size)
        ):
            raise AnnouncementError(reason)


def evaluate_announcement_check(
    context,
    lake_root,
    *,
    day,
    reconciliation,
    staging_root=None,
    target_record=_TARGET_NOT_PROVIDED,
    materializing=None,
    control=None,
):
    """Check one explicit day; source calls and recovery selection are excluded."""
    root = lake_root.root()
    staging = (
        Path(DEFAULT_LAKE_STAGING_ROOT) if staging_root is None else Path(staging_root)
    )
    path = raw_anns_d_path(root, day)
    control = AnnouncementControl() if control is None else control
    control.check()
    failed, rows = [], 0
    try:
        if root != Path(DEFAULT_LAKE_ROOT):
            raise AnnouncementError("announcement_formal_root_contract")
        record = (
            announcement_materialization(context.instance, day)
            if target_record is _TARGET_NOT_PROVIDED
            else target_record
        )
        if materializing is None:
            materializing = announcement_asset_is_executing(context)
        if record is None and (materializing or reconciliation):
            raise AnnouncementError("announcement_materialization_missing")
        if materializing and record.event_log_entry.run_id != context.run.run_id:
            raise AnnouncementError("announcement_different_run_delivery")
        if reconciliation:
            store, checkpoint = _delivery_evidence(record, root, staging, day, control)
        else:
            settings = announcement_file_settings_from_evidence(
                {"policy": asdict(AnnouncementPolicy())}
            )
            store = AnnouncementStore(
                root, staging, context.run.run_id, settings, control
            )
        before = announcement_file_fingerprint(path)
        if before is None:
            raise AnnouncementError("announcement_file_missing")
        rows = store.audit_file(path, day)["written_rows"]
        if reconciliation:
            verify_announcement_delivery(store, day, checkpoint)
            latest = announcement_materialization(context.instance, day)
            if record.storage_id != getattr(latest, "storage_id", None):
                raise AnnouncementError("announcement_delivery_changed_during_check")
        if before != announcement_file_fingerprint(path):
            raise AnnouncementError("announcement_file_changed_during_check")
    except AnnouncementError as error:
        if str(error) not in _CHECK_RULE_FAILURES:
            raise
        failed.append(str(error))
    control.check()
    return dg.AssetCheckResult(
        passed=not failed,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata=build_check_metadata(
            check_scope="reconciliation" if reconciliation else "schema",
            checked_row_count=rows,
            failed_row_count=rows if failed else 0,
            file_path=path,
            extra_metadata={
                "failed_rule_names": failed,
                "summary": "公告检查通过。"
                if not failed
                else "公告文件或交付依据不一致。",
                "next_action": "可使用。"
                if not failed
                else "检查失败规则和对应日的交付证据。",
            },
        ),
    )


def _announcement_check_events(context, lake_root, *, reconciliation):
    days = tuple(context.partition_keys)
    staging = Path(DEFAULT_LAKE_STAGING_ROOT)

    def cancelled():
        run = context.instance.get_run_by_id(context.run.run_id)
        return run is not None and run.status in (
            dg.DagsterRunStatus.CANCELING,
            dg.DagsterRunStatus.CANCELED,
        )

    control = AnnouncementControl(cancelled=cancelled)
    control.check()
    targets = prepare_announcement_check_targets(context, days, staging)
    if targets.reuse_delivery:
        for day, record in targets.records.items():
            _verify_reused_delivery_references(
                record, lake_root.root(), staging, day, control
            )
    name = ANNOUNCEMENT_CHECKS[1 if reconciliation else 0]
    for number, day in enumerate(days, 1):
        control.check()
        record = targets.records[day]
        result = evaluate_announcement_check(
            context,
            lake_root,
            day=day,
            reconciliation=reconciliation,
            staging_root=staging,
            target_record=record,
            materializing=targets.materializing,
            control=control,
        )
        reference = (
            None
            if record is None
            else AssetCheckEvaluationTargetMaterializationData(
                storage_id=record.storage_id,
                run_id=record.event_log_entry.run_id,
                timestamp=record.timestamp,
            )
        )
        yield AssetCheckEvaluation(
            asset_key=dg.AssetKey(ANNOUNCEMENT_ASSET),
            check_name=name,
            partition=day,
            passed=result.passed,
            metadata=result.metadata,
            severity=result.severity,
            blocking=True,
            target_materialization_data=reference,
        )
        context.log.info(
            json.dumps(
                {
                    "phase": "checked",
                    "check_name": name,
                    "day": day,
                    "evaluated_count": number,
                    "total": len(days),
                    "passed": result.passed,
                    "updated_at": time.time(),
                },
                ensure_ascii=False,
            )
        )
    yield dg.Output(None)


@dg.asset_check(
    asset=ANNOUNCEMENT_ASSET,
    name=ANNOUNCEMENT_CHECKS[0],
    partitions_def=anns_d_natural_days,
    blocking=True,
    description="六字段、类型、自然日分区、完全重复与文件安全；空日及缺URL/rec_time合法。",
)
def raw_tushare_anns_d_file_contract_check(
    context: dg.AssetCheckExecutionContext, lake_root: LakeRootResource
):
    yield from _announcement_check_events(context, lake_root, reconciliation=False)


@dg.asset_check(
    asset=ANNOUNCEMENT_ASSET,
    name=ANNOUNCEMENT_CHECKS[1],
    partitions_def=anns_d_natural_days,
    blocking=True,
    description="核对本次完整capture与源页、目标指纹和读回计数；不重新请求源。",
)
def raw_tushare_anns_d_delivery_reconciliation_check(
    context: dg.AssetCheckExecutionContext, lake_root: LakeRootResource
):
    yield from _announcement_check_events(context, lake_root, reconciliation=True)
