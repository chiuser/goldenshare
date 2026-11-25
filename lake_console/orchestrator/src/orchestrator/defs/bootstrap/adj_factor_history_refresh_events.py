"""Register explicitly selected DG evidence for verified history refresh files."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.definitions.data_version import get_input_event_pointer_tag

from orchestrator.defs.bootstrap.adj_factor_history_refresh import (
    FIELDS,
    LAYERS,
    SHANGHAI,
    AdjFactorHistoryRefreshError,
    _assert_identity,
    _checkpoint,
    _json,
    _load_sealed,
    _no_progress,
    _noop,
    _operation,
    _parse_day,
    _passed,
    _sealed_day,
    _sha256,
    _targets,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.sensors.readiness import (
    RAW_ADJ_FACTOR_ASSET_KEY,
    RAW_ADJ_FACTOR_CHECKS,
    SILVER_ADJ_FACTOR_ASSET_KEY,
    SILVER_ADJ_FACTOR_BLOCKING_CHECKS,
    _check_passed_for_materialization,
)
from orchestrator.defs.stock_factor_price_checks import (
    ADJ_FACTOR_PARTITION_SET,
    adj_factor_partition_allowed_status,
)

ASSETS = {"raw": RAW_ADJ_FACTOR_ASSET_KEY, "silver": SILVER_ADJ_FACTOR_ASSET_KEY}
CHECKS = {"raw": RAW_ADJ_FACTOR_CHECKS, "silver": SILVER_ADJ_FACTOR_BLOCKING_CHECKS}
LIFECYCLE = dg.AssetKey("silver_stock_lifecycle")
OPERATION = "goldenshare/adj_factor_history_refresh_operation"
DIGEST = "goldenshare/adj_factor_history_refresh_sha256"
CHECK_SCOPES = {
    "contract_check": CheckScope.SCHEMA,
    "key_value_integrity_check": CheckScope.KEY_UNIQUENESS,
    "lifecycle_coverage_check": CheckScope.REFERENTIAL_INTEGRITY,
    "partition_allowed_check": CheckScope.PARTITION_ALIGNMENT,
}


def _latest(instance, asset: dg.AssetKey, day: str | None = None):
    filter_ = dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[day] if day else None)
    records = instance.fetch_materializations(filter_, limit=1).records
    return records[0] if records else None


def _value(record, key: str):
    if record is None:
        return None
    value = record.asset_materialization.metadata.get(key)
    return value.value if value is not None else None


def _verified_files(run: Path, lake: Path, day: str) -> dict:
    targets = _targets(lake, day)
    receipts = {}
    for layer in LAYERS:
        receipt = _json(run / day / f"{layer}-publication.json")
        if receipt["phase"] != "verified" or not _passed(receipt["checks"]):
            raise AdjFactorHistoryRefreshError(f"File is not verified: {day}, {layer}")
        _assert_identity(targets[layer], receipt["target"])
        receipts[layer] = receipt
    return receipts


def _silver_inputs(instance, item: dict, operation_id: str, day: str, receipts: dict) -> dict:
    raw = _latest(instance, ASSETS["raw"], day)
    lifecycle = _latest(instance, LIFECYCLE)
    if receipts["raw"]["changed"]:
        raw_candidate = receipts["raw"]["candidate"]
        if _value(raw, OPERATION) != operation_id or _value(raw, DIGEST) != raw_candidate["sha256"]:
            raise AdjFactorHistoryRefreshError(f"Register the verified Raw publication first: {day}")
    elif raw is None or raw.storage_id != item.get("raw_materialization_id"):
        raise AdjFactorHistoryRefreshError(f"Missing verified unchanged Raw input reference: {day}")
    if lifecycle is None or lifecycle.storage_id != item.get("lifecycle_materialization_id"):
        raise AdjFactorHistoryRefreshError(f"Missing verified lifecycle input reference: {day}")
    return {get_input_event_pointer_tag(key): str(record.storage_id)
            for key, record in ((ASSETS["raw"], raw), (LIFECYCLE, lifecycle))}


def _materialization(instance, asset, day, target, operation_id, digest, tags, control, checks):
    latest = _latest(instance, asset, day)
    latest_id = latest.storage_id if latest else None
    state = _json(control) if control.exists() else {"previous_id": latest_id, "sha256": digest, "tags": tags}
    if state["sha256"] != digest or state["tags"] != tags:
        raise AdjFactorHistoryRefreshError(f"Event inputs changed after preparation: {asset} {day}")
    if not control.exists():
        _checkpoint(control, state)
    if _value(latest, OPERATION) == operation_id and _value(latest, DIGEST) == digest:
        if (latest.asset_materialization.tags or {}) != tags:
            raise AdjFactorHistoryRefreshError(f"Existing event has different input references: {asset} {day}")
        return latest, 0
    if latest_id != state["previous_id"]:
        raise AdjFactorHistoryRefreshError(f"Publication event changed concurrently: {asset} {day}")
    instance.report_runless_asset_event(dg.AssetMaterialization(
        asset_key=asset, partition=day, tags=tags,
        metadata=build_materialization_metadata(
            uri=target, row_count=checks["rows"], observed_columns=FIELDS,
            extra_metadata={OPERATION: operation_id, DIGEST: digest, "trade_date": day},
        ),
    ))
    latest = _latest(instance, asset, day)
    if _value(latest, OPERATION) != operation_id or _value(latest, DIGEST) != digest:
        raise AdjFactorHistoryRefreshError(f"Cannot read back publication event: {asset} {day}")
    return latest, 1


def _record_checks(instance, asset, day, layer, materialization, operation_id, counts, cancel):
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id, run_id=materialization.run_id, timestamp=materialization.timestamp,
    )
    added = 0
    for name in CHECKS[layer]:
        cancel()
        key = dg.AssetCheckKey(asset, name)
        if _check_passed_for_materialization(instance, key, target.storage_id) is True:
            continue
        metadata = {OPERATION: operation_id, "checked_counts": counts}
        if name == "silver_adj_factor_lifecycle_coverage_check":
            metadata["rule_passed"] = {"silver_adj_factor_coverage_complete": True,
                                       "silver_adj_factor_listed_stock_only": True}
        scope = CHECK_SCOPES[name.removeprefix(f"{layer}_adj_factor_")]
        instance.report_runless_asset_event(dg.AssetCheckEvaluation(
            asset_key=asset, check_name=name, passed=True, blocking=True, partition=day,
            target_materialization_data=target,
            metadata=build_check_metadata(check_scope=scope, checked_row_count=counts["rows"], failed_row_count=0,
                                          extra_metadata=metadata),
        ))
        if _check_passed_for_materialization(instance, key, target.storage_id) is not True:
            raise AdjFactorHistoryRefreshError(f"Cannot read back check: {day}, {name}")
        added += 1
    return added


def register_history_events(*, instance: dg.DagsterInstance, lake: Path, staging: Path, operation_id: str,
                            scope_path: Path, cancel: Callable[[], None] = _noop,
                            progress: Callable[[dict], None] = _no_progress) -> dict:
    """Append only requested, verified publications. The file stages never call this."""
    scope = _json(scope_path)["items"]
    keyed = {(item["day"], item["layer"]): item for item in scope}
    if not scope or len(keyed) != len(scope) or any(layer not in LAYERS for _, layer in keyed):
        raise AdjFactorHistoryRefreshError("Event scope must contain unique asset/date pairs")
    registered = set(instance.get_dynamic_partitions(ADJ_FACTOR_PARTITION_SET))
    totals = {"publications": 0, "checks": 0}
    with _operation(lake, staging, operation_id) as run:
        _, sealed = _load_sealed(run, lake)
        for index, (day, layer) in enumerate(sorted(keyed), 1):
            cancel()
            _parse_day(day)
            if day not in sealed["days"] or not adj_factor_partition_allowed_status(
                partition_key=day, registered_keys=registered, today=datetime.now(SHANGHAI).date().isoformat(),
            )["passed"]:
                raise AdjFactorHistoryRefreshError(f"Event date is outside verified scope: {day}")
            if _sealed_day(run, day, sealed["days"][day])["status"] != "ready":
                raise AdjFactorHistoryRefreshError(f"Date did not pass preparation: {day}")
            receipts = _verified_files(run, lake, day)
            receipt = receipts[layer]
            if not receipt["changed"] and not (layer == "silver" and receipts["raw"]["changed"]):
                raise AdjFactorHistoryRefreshError(f"No revised file or input to register: {day}, {layer}")
            tags = _silver_inputs(instance, keyed[(day, layer)], operation_id, day, receipts) if layer == "silver" else {}
            target = _targets(lake, day)[layer]
            digest = _sha256(target)
            _assert_identity(target, receipt["target"])
            asset = ASSETS[layer]
            cancel()
            record, added = _materialization(instance, asset, day, target, operation_id, digest, tags,
                                               run / day / f"{layer}-event.json", receipt["checks"])
            totals["publications"] += added
            totals["checks"] += _record_checks(instance, asset, day, layer, record, operation_id,
                                              receipt["checks"], cancel)
            progress({"phase": "register-events", "day": day, "layer": layer,
                      "completed": index, "total": len(keyed), **totals})
    return totals
