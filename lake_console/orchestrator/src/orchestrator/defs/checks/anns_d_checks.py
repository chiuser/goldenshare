"""Partition-bound file and delivery checks without remote source requests."""

from pathlib import Path

import dagster as dg

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
)
from orchestrator.defs.anns_d_execution import verify_announcement_delivery
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_anns_d_path,
)
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy
from orchestrator.defs.run_contracts.metadata import build_check_metadata


def announcement_materialization(instance, day):
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(ANNOUNCEMENT_ASSET), asset_partitions=[day]
        ),
        limit=1,
    ).records
    return records[0] if records else None


def evaluate_announcement_check(
    context, lake_root, *, reconciliation, staging_root=Path(DEFAULT_LAKE_STAGING_ROOT)
):
    day = context.partition_key
    root = lake_root.root()
    path = raw_anns_d_path(root, day)
    failed, rows = [], 0
    try:
        if root != Path(DEFAULT_LAKE_ROOT):
            raise AnnouncementError("announcement_formal_root_contract")
        if not reconciliation:
            store = AnnouncementStore(
                root,
                staging_root,
                context.run.run_id,
                AnnouncementPolicy(),
                AnnouncementControl(),
            )
            before = announcement_file_fingerprint(path)
            rows = store.audit_file(path, day)["written_rows"]
            if before != announcement_file_fingerprint(path):
                raise AnnouncementError("announcement_file_changed_during_check")
        else:
            record = announcement_materialization(context.instance, day)
            if record is None:
                raise AnnouncementError("announcement_materialization_missing")
            metadata = record.asset_materialization.metadata
            identity = metadata["goldenshare/announcement_identity"].value
            checkpoint_path = assert_safe_announcement_path(
                metadata["goldenshare/announcement_checkpoint"].value
            )
            permitted = staging_root / "anns_d"
            if permitted not in checkpoint_path.parents:
                raise AnnouncementError("announcement_checkpoint_outside_staging")
            selected = context.run.asset_selection
            materializing = dg.AssetKey(ANNOUNCEMENT_ASSET) in (
                context.job_def.asset_layer.executable_asset_keys
                if selected is None
                else selected
            )
            steps = context.run.step_keys_to_execute
            if steps is not None:
                materializing = materializing and ANNOUNCEMENT_ASSET in steps
            if materializing and record.event_log_entry.run_id != context.run.run_id:
                raise AnnouncementError("announcement_different_run_delivery")
            policy = AnnouncementPolicy(**identity["policy"])
            run_id = checkpoint_path.parent.name.removeprefix("run_id=")
            store = AnnouncementStore(
                root, staging_root, run_id, policy, AnnouncementControl()
            )
            if checkpoint_path != store.directory / "delivery.json":
                raise AnnouncementError("announcement_checkpoint_path_contract")
            checkpoint = AnnouncementCheckpoint(checkpoint_path, identity)
            if identity["day"] != day:
                raise AnnouncementError("announcement_delivery_wrong_day")
            before = announcement_file_fingerprint(path)
            rows = store.audit_file(path, day)["written_rows"]
            for page in checkpoint.document.get("delivery", {}).get("source_pages", []):
                if permitted not in assert_safe_announcement_path(page["path"]).parents:
                    raise AnnouncementError("announcement_source_page_outside_staging")
            verify_announcement_delivery(store, day, checkpoint)
            latest = announcement_materialization(context.instance, day)
            if before != announcement_file_fingerprint(
                path
            ) or record.storage_id != getattr(latest, "storage_id", None):
                raise AnnouncementError("announcement_delivery_changed_during_check")
    except Exception as error:  # noqa: BLE001 -- unavailable evidence must produce a red check
        failed.append(
            str(error)
            if isinstance(error, AnnouncementError)
            else "announcement_evidence_unavailable"
        )
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
    return evaluate_announcement_check(context, lake_root, reconciliation=False)


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
    return evaluate_announcement_check(context, lake_root, reconciliation=True)
