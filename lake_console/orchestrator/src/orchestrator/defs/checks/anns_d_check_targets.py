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
from orchestrator.defs.anns_d_run_intent import announcement_root_file_intent
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


def announcement_asset_is_executing(context):
    """Use this run's executable definition and actual steps, never a root run."""
    run = context.run
    job = getattr(context, "job_def", None)
    selected = (
        job.asset_layer.selected_asset_keys
        if job is not None
        else getattr(run, "asset_selection", None) or ()
    )
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


def _fingerprint_metadata(value):
    return (
        isinstance(value, Mapping)
        and type(value.get("size")) is int
        and value["size"] >= 0
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
        and all(character in "0123456789abcdefABCDEF" for character in value["sha256"])
    )


def announcement_materialization_fingerprint(record):
    metadata = record.asset_materialization.metadata
    # Native P2/current assets and existing runless producers use these two keys.
    values = [
        getattr(metadata[key], "value", None)
        for key in ("goldenshare/fingerprint", "goldenshare/announcement_file")
        if key in metadata
    ]
    if not values or not all(_fingerprint_metadata(value) for value in values):
        raise AnnouncementError("announcement_materialization_fingerprint_missing")
    if any(value != values[0] for value in values[1:]):
        raise AnnouncementError("announcement_materialization_fingerprint_conflict")
    return values[0]


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
    identity_tags = (
        "anns_d/window_id",
        "anns_d/execution_version",
        "anns_d/start_date",
        "anns_d/end_date",
        "anns_d/started_at",
        "anns_d/automatic",
    )
    has_intent = "anns_d/window_id" in root_tags
    if not has_intent and not announcement_root_file_intent(
        root, instance=context.instance, asset_step_key=_asset_step_key(context)
    ):
        if any(key in tags for key in identity_tags):
            raise AnnouncementError("announcement_check_execution_identity")
        return None
    if has_intent:
        if root_tags.get("anns_d/execution_version") != str(
            ANNOUNCEMENT_EXECUTION_VERSION
        ):
            raise AnnouncementError("announcement_check_execution_version")
        window_id = root_tags["anns_d/window_id"]
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
        execution = json.loads(path.read_text())
        identity = execution["identity"]
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
    expected_tags = {
        "anns_d/window_id": window_id,
        "anns_d/execution_version": str(ANNOUNCEMENT_EXECUTION_VERSION),
        "anns_d/start_date": days[0],
        "anns_d/end_date": days[-1],
        "anns_d/started_at": str(started),
        "anns_d/automatic": "true" if identity["automatic"] else "false",
    }
    if has_intent and any(
        root_tags.get(key) != value
        for key, value in expected_tags.items()
        if key != "anns_d/automatic" or identity["automatic"]
    ):
        raise AnnouncementError("announcement_check_execution_identity")
    if any(
        supplied[key] != expected_tags[key]
        for supplied in (root_tags, tags)
        for key in identity_tags
        if key in supplied
    ):
        raise AnnouncementError("announcement_check_execution_identity")
    deliveries = execution.get("days")
    if not isinstance(deliveries, Mapping) or set(deliveries) != set(days):
        raise AnnouncementError("announcement_recovery_delivery_missing")
    from orchestrator.defs.anns_d_window import announcement_day_run_id

    for day, delivery in deliveries.items():
        expected_path = (
            staging
            / "anns_d"
            / f"run_id={announcement_day_run_id(window_id, day)}"
            / "delivery.json"
        )
        if (
            not isinstance(delivery, Mapping)
            or delivery.get("phase") != "promoted"
            or not _fingerprint_metadata(delivery.get("fingerprint"))
        ):
            raise AnnouncementError("announcement_recovery_delivery_missing")
        if delivery.get("checkpoint") != str(expected_path):
            raise AnnouncementError(
                "announcement_recovery_delivery_checkpoint_conflict"
            )
    return identity, deliveries


@dataclass(frozen=True)
class AnnouncementCheckTargets:
    records: Mapping
    materializing: bool
    window_identity: Mapping | None
    selected_checks: frozenset[str]
    window_deliveries: Mapping | None

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
    frozen = None if materializing else _frozen_check_window(context, days, staging)
    identity, deliveries = (None, None) if frozen is None else frozen
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
            if (
                announcement_materialization_fingerprint(record)
                != deliveries[day]["fingerprint"]
            ):
                raise AnnouncementError(
                    "announcement_recovery_delivery_fingerprint_conflict"
                )
            checkpoint = record.asset_materialization.metadata.get(
                "goldenshare/announcement_checkpoint"
            )
            if getattr(checkpoint, "value", None) != deliveries[day]["checkpoint"]:
                raise AnnouncementError(
                    "announcement_recovery_delivery_checkpoint_conflict"
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
    return AnnouncementCheckTargets(
        records, materializing, identity, selected, deliveries
    )
