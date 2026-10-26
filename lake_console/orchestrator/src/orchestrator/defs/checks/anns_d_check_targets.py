"""Bounded materialization targets for announcement checks and reexecution."""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass

import dagster as dg
from dagster._check import CheckError
from dagster._core.event_api import PartitionKeyFilter
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.anns_d_checkpoint import assert_safe_announcement_path
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_CHECKS,
    ANNOUNCEMENT_VERSION,
    AnnouncementError,
    announcement_date_range,
)
from orchestrator.defs.run_contracts.anns_d import ANNOUNCEMENT_EXECUTION_VERSION

ASSET_KEY = dg.AssetKey(ANNOUNCEMENT_ASSET)


def announcement_materialization(instance, day):
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=ASSET_KEY, asset_partitions=[day]), limit=1
    ).records
    return records[0] if records else None


def _asset_step_key(context):
    try:
        return str(
            context.job_def.asset_layer.get_op_output_handle(ASSET_KEY).node_handle
        )
    except CheckError:
        # A check-only subset has no executable asset handle. Use the actual
        # registered definition when classifying its original root run.
        from orchestrator.defs.assets.anns_d import raw_tushare_anns_d

        return raw_tushare_anns_d.op.name


def announcement_asset_is_executing(context, run=None):
    run = context.run if run is None else run
    selected = getattr(run, "asset_selection", None)
    if selected is None:
        job = getattr(context, "job_def", None)
        selected = job.asset_layer.selected_asset_keys if job else ()
    if ASSET_KEY not in selected:
        return False
    steps = getattr(run, "step_keys_to_execute", None)
    if steps is not None:
        return _asset_step_key(context) in steps
    resolved = getattr(run, "resolved_op_selection", None)
    return resolved is None or _asset_step_key(context) in resolved


def _selected_check_names(context):
    layer = context.job_def.asset_layer
    available = {
        spec.key
        for item in layer.data
        for spec in item.assets_def.check_specs
        if spec.asset_key == ASSET_KEY
    }
    selected = getattr(context.run, "asset_check_selection", None)
    steps = context.run.step_keys_to_execute
    return frozenset(
        key.name
        for key in available
        if (selected is None or key in selected)
        and (steps is None or str(layer.get_op_output_handle(key).node_handle) in steps)
    )


def _metadata_identity(record):
    value = record.asset_materialization.metadata.get(
        "goldenshare/announcement_identity"
    )
    identity = getattr(value, "value", None)
    if not isinstance(identity, Mapping):
        raise AnnouncementError("announcement_materialization_identity")
    return identity


def _frozen_check_window(context, days, staging):
    run = context.run
    root_id = getattr(run, "root_run_id", None)
    root = run
    if root_id and root_id != run.run_id:
        root = context.instance.get_run_by_id(root_id)
        if root is None:
            raise AnnouncementError("announcement_check_root_missing")
    tags = getattr(run, "tags", {})
    root_tags = getattr(root, "tags", {})
    has_intent = "anns_d/window_id" in root_tags or "anns_d/window_id" in tags
    if not has_intent and not announcement_asset_is_executing(context, root):
        return None
    intent = tags if "anns_d/window_id" in tags else root_tags
    if "anns_d/window_id" in intent:
        if intent.get("anns_d/execution_version") != str(
            ANNOUNCEMENT_EXECUTION_VERSION
        ):
            raise AnnouncementError("announcement_check_execution_version")
        window_id = intent["anns_d/window_id"]
    else:
        from orchestrator.defs.anns_d_window import announcement_manual_window_id

        window_id = announcement_manual_window_id(
            root_id or root.run_id, days[0], days[-1]
        )
    if (
        not isinstance(window_id, str)
        or not window_id.replace("-", "").replace("_", "").isalnum()
    ):
        raise AnnouncementError("announcement_window_identity")
    path = assert_safe_announcement_path(
        staging / "anns_d" / "windows" / window_id / "execution.json"
    )
    if not path.is_file():
        raise AnnouncementError("announcement_check_execution_missing")
    try:
        identity = json.loads(path.read_text())["identity"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise AnnouncementError("announcement_check_execution_identity") from None
    if (
        not isinstance(identity, Mapping)
        or identity.get("execution_version") != ANNOUNCEMENT_EXECUTION_VERSION
        or identity.get("contract_version") != ANNOUNCEMENT_VERSION
        or identity.get("window_id") != window_id
        or identity.get("days") != list(days)
        or type(identity.get("automatic")) is not bool
        or not isinstance(identity.get("policy"), Mapping)
    ):
        raise AnnouncementError("announcement_check_execution_identity")
    started = identity.get("started_at")
    if type(started) not in (int, float) or not math.isfinite(started) or started <= 0:
        raise AnnouncementError("announcement_check_execution_identity")
    from orchestrator.defs.anns_d_window import announcement_window_dates

    if (
        announcement_window_dates(
            days[0], days[-1], started, automatic=identity["automatic"]
        )
        != days
    ):
        raise AnnouncementError("announcement_check_execution_identity")
    if has_intent and (
        intent.get("anns_d/start_date") != days[0]
        or intent.get("anns_d/end_date") != days[-1]
        or intent.get("anns_d/started_at") != str(started)
        or (intent.get("anns_d/automatic") == "true") != identity["automatic"]
    ):
        raise AnnouncementError("announcement_check_execution_identity")
    return identity


@dataclass(frozen=True)
class AnnouncementCheckTargets:
    records: Mapping
    materializing: bool
    window_identity: Mapping | None
    selected_checks: frozenset[str]

    @property
    def reuse_delivery(self):
        return (
            self.window_identity is not None
            and ANNOUNCEMENT_CHECKS[1] not in self.selected_checks
        )


def prepare_announcement_check_targets(context, days, staging):
    days = tuple(days)
    if not days or announcement_date_range(days[0], days[-1]) != days:
        raise AnnouncementError("announcement_check_partition_range")
    materializing = announcement_asset_is_executing(context)
    identity = None if materializing else _frozen_check_window(context, days, staging)
    records = {day: announcement_materialization(context.instance, day) for day in days}
    selected = _selected_check_names(context)
    if identity is not None:
        for day, record in records.items():
            if record is None:
                raise AnnouncementError("announcement_recovery_materialization_missing")
            daily_identity = _metadata_identity(record)
            if (
                daily_identity.get("window_id") != identity["window_id"]
                or daily_identity.get("day") != day
                or daily_identity.get("policy") != identity["policy"]
            ):
                raise AnnouncementError(
                    "announcement_recovery_materialization_conflict"
                )
        for name in set(ANNOUNCEMENT_CHECKS) - selected:
            for day, target in records.items():
                history = context.instance.event_log_storage.get_asset_check_execution_history(
                    dg.AssetCheckKey(ASSET_KEY, name),
                    limit=1,
                    partition_filter=PartitionKeyFilter(key=day),
                )
                previous = history[0] if history else None
                evaluation = previous.evaluation if previous is not None else None
                reference = (
                    evaluation.target_materialization_data
                    if evaluation is not None
                    else None
                )
                if (
                    previous is None
                    or previous.status != AssetCheckExecutionRecordStatus.SUCCEEDED
                    or previous.partition != day
                    or reference is None
                    or reference.storage_id != target.storage_id
                    or reference.run_id != target.event_log_entry.run_id
                ):
                    raise AnnouncementError("announcement_recovery_sibling_check")
    return AnnouncementCheckTargets(records, materializing, identity, selected)
