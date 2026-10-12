"""Bounded event identity plus physical hash readiness; no date-by-date history queries."""

from dataclasses import dataclass, replace
from pathlib import Path

import dagster as dg

from orchestrator.defs.io.moneyflow_candidates import candidate_file_hash
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_EVENT_RECORD_LIMIT,
    MONEYFLOW_IND_DC_READINESS_FILE_MAX_BYTES,
    MONEYFLOW_READINESS_FILE_MAX_BYTES,
    MONEYFLOW_SENSOR_WINDOW,
    MoneyflowContractError,
    market_moneyflow_day,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    require_moneyflow_automation_contract,
)


@dataclass(frozen=True)
class MoneyflowDelivery:
    ready: bool
    materialized: bool
    reason: str
    record: object = None
    metadata: dict | None = None


def _metadata(record):
    return {
        k.removeprefix("goldenshare/"): v.value
        for k, v in record.asset_materialization.metadata.items()
        if k.startswith("goldenshare/")
    }


def latest_moneyflow_check_evaluations(records, dates):
    latest = {}
    for record in records:
        event = record.event.dagster_event if record.event else None
        if (
            record.partition in dates
            and event
            and event.event_type == dg.DagsterEventType.ASSET_CHECK_EVALUATION
        ):
            latest.setdefault(record.partition, record)
    return latest


def batch_moneyflow_readiness(
    instance, lake_root: Path, dates, *, contract, layers=("raw", "silver")
):
    require_moneyflow_automation_contract(contract)
    dates = tuple(dates)
    if (
        not dates
        or len(dates) > MONEYFLOW_SENSOR_WINDOW
        or len(set(dates)) != len(dates)
    ):
        raise MoneyflowContractError("readiness_window")
    for day in dates:
        market_moneyflow_day(day)
    if layers not in (("raw",), ("raw", "silver")):
        raise MoneyflowContractError("readiness_layers")
    file_budget = (
        MONEYFLOW_IND_DC_READINESS_FILE_MAX_BYTES
        if contract.dataset == "moneyflow_ind_dc"
        else MONEYFLOW_READINESS_FILE_MAX_BYTES
    )
    results = {}
    for layer in layers:
        key = dg.AssetKey(
            contract.raw_asset if layer == "raw" else contract.silver_asset
        )
        check_name = contract.raw_check if layer == "raw" else contract.silver_check
        records = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=key, asset_partitions=list(dates)),
            limit=MONEYFLOW_EVENT_RECORD_LIMIT,
        ).records
        checks = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(key, check_name), limit=MONEYFLOW_EVENT_RECORD_LIMIT
        )
        latest = {}
        for record in records:
            if record.partition_key in dates:
                latest.setdefault(record.partition_key, record)
        latest_checks = latest_moneyflow_check_evaluations(checks, dates)
        if len(records) >= MONEYFLOW_EVENT_RECORD_LIMIT and set(latest) != set(dates):
            raise MoneyflowContractError("readiness_record_limit")
        if len(checks) >= MONEYFLOW_EVENT_RECORD_LIMIT and not set(latest).issubset(
            latest_checks
        ):
            raise MoneyflowContractError("readiness_record_limit")
        statuses = {}
        for day in dates:
            mat, check = latest.get(day), latest_checks.get(day)
            metadata = _metadata(mat) if mat is not None else {}
            reason = "ready"
            if mat is None:
                reason = (
                    "check_without_materialization"
                    if check is not None
                    and check.event is not None
                    and check.event.dagster_event
                    and check.event.dagster_event.event_type
                    == dg.DagsterEventType.ASSET_CHECK_EVALUATION
                    else "missing_materialization"
                )
            else:
                event = (
                    check.event.dagster_event
                    if check is not None and check.event
                    else None
                )
                evaluation = event.event_specific_data if event else None
                target = getattr(evaluation, "target_materialization_data", None)
                if check is None:
                    reason = "check_missing"
                elif not (
                    check.status.value == "SUCCEEDED"
                    and getattr(evaluation, "passed", False)
                    and getattr(evaluation, "blocking", False)
                    and getattr(target, "storage_id", None) == mat.storage_id
                    and getattr(target, "run_id", None) == mat.event_log_entry.run_id
                    and getattr(target, "timestamp", None) == mat.timestamp
                ):
                    reason = "check_failed_or_stale"
            path = (raw_moneyflow_path if layer == "raw" else silver_moneyflow_path)(
                lake_root, contract.dataset, day
            )
            if reason == "ready":
                expected = metadata.get("file_sha256")
                if not isinstance(expected, str) or len(expected) != 64:
                    reason = "file_hash_missing"
                elif not path.is_file() or any(
                    p.is_symlink() for p in (path, *path.parents)
                ):
                    reason = "file_missing_or_symlink"
                elif path.stat().st_size > file_budget:
                    reason = "file_hash_budget"
                elif candidate_file_hash(path) != expected:
                    reason = "file_changed"
            elif mat is None and path.exists():
                reason = "file_without_materialization"
            statuses[day] = MoneyflowDelivery(
                reason == "ready", mat is not None, reason, mat, metadata
            )
        results[layer] = statuses
    if "silver" in results:
        for day in dates:
            raw, silver = results["raw"][day], results["silver"][day]
            if not raw.ready and silver.reason in {"ready", "missing_materialization"}:
                results["silver"][day] = replace(
                    silver, ready=False, reason="raw_not_ready"
                )
            elif silver.ready and silver.metadata.get("raw_sha256") != raw.metadata.get(
                "file_sha256"
            ):
                results["silver"][day] = replace(
                    silver, ready=False, reason="upstream_revision"
                )
    return results
