"""Preflight and recoverable single-file promotion of verified history cohorts."""

import os
import re
import tempfile
import time
from pathlib import Path

from orchestrator.defs.bootstrap.moneyflow_history_candidates import (
    _attempt_path,
    _audit_files,
    _fsync,
    _read_json,
)
from orchestrator.defs.bootstrap.moneyflow_history_cohort import (
    _closed_prefix,
    _cohort_identity,
    _hash_file,
    _large_json,
    _manifest,
    _operation,
    _units,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import _hash
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_directory
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_moneyflow_path,
    silver_moneyflow_path,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError


def _check_path(path):
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(p.is_symlink() for p in (path, *path.parents))
    ):
        raise MoneyflowContractError("history_promotion_path")


def _validate_roots(lake_root, staging_root):
    for path in (lake_root, staging_root):
        _check_path(path)
    if (
        lake_root == staging_root
        or lake_root in staging_root.parents
        or staging_root in lake_root.parents
    ):
        raise MoneyflowContractError("history_promotion_roots_overlap")
    formal = Path(DEFAULT_LAKE_ROOT)
    if lake_root == formal:
        if staging_root != Path(DEFAULT_LAKE_STAGING_ROOT):
            raise MoneyflowContractError("history_promotion_staging_root")
        if not formal.parent.is_mount():
            raise MoneyflowContractError("history_lake_unavailable")
    else:
        temporary_roots = (Path("/private/tmp"), Path(tempfile.gettempdir()).resolve())
        if not all(
            any(path != base and base in path.parents for base in temporary_roots)
            for path in (lake_root, staging_root)
        ):
            raise MoneyflowContractError("history_promotion_lake_root")
    if not lake_root.is_dir():
        raise MoneyflowContractError("history_lake_unavailable")


def _target(lake_root, plan, day, layer):
    path = (raw_moneyflow_path if layer == "raw" else silver_moneyflow_path)(
        lake_root, plan.dataset, day
    )
    _check_path(path)
    if path.parent.exists() and (
        not path.parent.is_dir()
        or any(p.name != "part-000.parquet" for p in path.parent.glob("*.parquet"))
    ):
        raise MoneyflowContractError("history_formal_layout")
    return path


def _existing_parent(path):
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    return parent


def _same_device(source, target_parent):
    return source.stat().st_dev == target_parent.stat().st_dev


def _frozen(root, cutoff):
    saved = _large_json(root / "cohort.json")
    if not isinstance(saved.get("snapshots"), dict):
        raise MoneyflowContractError("history_cohort_invalid")
    expected, plans = _manifest(_cohort_identity(cutoff), saved["snapshots"])
    if saved != expected:
        raise MoneyflowContractError("history_cohort_changed")
    progress = _large_json(root / "progress.json")
    units = _units(plans)
    closed = progress.get("closed_units")
    if (
        not isinstance(closed, list)
        or len(closed) != len(units)
        or progress.get("completed_units") != len(units)
    ):
        raise MoneyflowContractError("history_candidates_not_verified")
    for (plan, unit_id), entry in zip(units, closed, strict=True):
        if (
            not isinstance(entry, dict)
            or entry.get("dataset") != plan.dataset
            or type(entry.get("unit_id")) is not int
            or entry["unit_id"] != unit_id
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("checkpoint_sha256", "")))
            is None
        ):
            raise MoneyflowContractError("history_closed_checkpoint_changed")
    return saved, units, closed, plans


def _promotion_contract(manifest, closed, lake_root):
    payload = {
        "revision": "moneyflow_history_promotion_v1",
        "cohort_hash": manifest["cohort_hash"],
        "closed_units_hash": _hash(closed),
        "lake_root": str(lake_root),
        "total_files": 2 * manifest["total_dates"],
        "total_units": manifest["total_units"],
        "conflict_policy": "refuse_different_hash",
    }
    return {**payload, "contract_hash": _hash(payload)}


def _unit_paths(root, plan, unit_id):
    directory = (
        root / plan.dataset / plan.cutoff / "history_candidates" / f"unit-{unit_id:06d}"
    )
    return directory, directory / "checkpoint.json", directory / "promotion.json"


def _promotion_state(root, plan, unit_id, closed_entry, contract):
    directory, checkpoint, path = _unit_paths(root, plan, unit_id)
    expected = {
        "revision": contract["revision"],
        "contract_hash": contract["contract_hash"],
        "candidate_checkpoint_sha256": closed_entry["checkpoint_sha256"],
        "dataset": plan.dataset,
        "unit_id": unit_id,
    }
    state = (
        _read_json(path)
        if path.exists()
        else {**expected, "stage": "promoting", "files": {}}
    )
    keys = {
        f"{day}/{layer}"
        for day in plan.units[unit_id].dates
        for layer in ("raw", "silver")
    }
    if (
        any(state.get(k) != v for k, v in expected.items())
        or state.get("stage") not in {"promoting", "complete"}
        or not isinstance(state.get("files"), dict)
        or not set(state["files"]).issubset(keys)
    ):
        raise MoneyflowContractError("history_promotion_checkpoint")
    for item in state["files"].values():
        if (
            not isinstance(item, dict)
            or set(item) != {"status", "mode", "size"}
            or item["status"] not in {"intent", "complete"}
            or item["mode"] not in {"move", "reuse"}
            or type(item["size"]) is not int
            or item["size"] <= 0
        ):
            raise MoneyflowContractError("history_promotion_checkpoint")
    if state["stage"] == "complete" and (
        set(state["files"]) != keys
        or any(item["status"] != "complete" for item in state["files"].values())
    ):
        raise MoneyflowContractError("history_promotion_checkpoint")
    return directory, checkpoint, path, state


def _receipt_files(root, plan, unit_id):
    directory, checkpoint, _ = _unit_paths(root, plan, unit_id)
    receipt = _read_json(checkpoint)
    attempt = _attempt_path(directory, receipt.get("attempt"))
    files = receipt.get("files")
    if not isinstance(files, list) or len(files) != len(plan.units[unit_id].dates):
        raise MoneyflowContractError("history_checkpoint_files")
    entries = []
    for day, fact in zip(plan.units[unit_id].dates, files, strict=True):
        if not isinstance(fact, dict) or fact.get("trade_date") != day:
            raise MoneyflowContractError("history_checkpoint_files")
        for layer in ("raw", "silver"):
            source = attempt / day / (layer + ".parquet")
            _check_path(source)
            entries.append((day, layer, source, fact.get(layer + "_sha256")))
    return receipt, entries


def _moved_bytes(root, units, closed, contract, lake_root, check=lambda: None):
    """Account actual formal bytes, including rename-before-checkpoint recovery."""
    used = 0
    for (plan, unit_id), entry in zip(units, closed, strict=True):
        check()
        _, _, _, state = _promotion_state(root, plan, unit_id, entry, contract)
        for day, layer, source, _ in _receipt_files(root, plan, unit_id)[1]:
            check()
            item = state["files"].get(f"{day}/{layer}")
            if item and item["mode"] == "move":
                target = _target(lake_root, plan, day, layer)
                if target.exists():
                    if not target.is_file() or target.stat().st_size != item["size"]:
                        raise MoneyflowContractError("history_formal_changed")
                    used += target.stat().st_size
    return used


def _file_location(lake_root, plan, day, layer, source, item, expected_hash, check):
    target = _target(lake_root, plan, day, layer)
    if target.exists():
        if not target.is_file():
            raise MoneyflowContractError("history_formal_conflict")
        if source.exists() and _hash_file(target, check) != expected_hash:
            raise MoneyflowContractError("history_formal_conflict")
    if source.exists():
        if not _same_device(source, _existing_parent(target)):
            raise MoneyflowContractError("history_cross_device")
        if item and item["status"] == "complete" and not target.exists():
            raise MoneyflowContractError("history_formal_missing")
        return source
    if not item or item["mode"] != "move" or not target.exists():
        raise MoneyflowContractError("history_candidate_missing")
    return target


def _preflight(root, manifest, units, closed, plans, contract, lake_root, control):
    if not _same_device(root, lake_root):
        raise MoneyflowContractError("history_cross_device")
    states = {}
    locations = {}
    summary = {
        "new_files": 0,
        "identical_files": 0,
        "recovered_files": 0,
        "promoted_files": 0,
        "promoted_dates": 0,
        "promoted_rows": 0,
    }
    control.start("promotion_scope_preflight")
    try:
        for (plan, unit_id), entry in zip(units, closed, strict=True):
            control.check()
            _, _, _, state = _promotion_state(root, plan, unit_id, entry, contract)
            states[(plan.dataset, unit_id)] = state
            for day, layer, source, digest in _receipt_files(root, plan, unit_id)[1]:
                target = _target(lake_root, plan, day, layer)
                item = state["files"].get(f"{day}/{layer}")
                key = (plan.dataset, unit_id, day, layer)
                locations[key] = (source, target, item, digest)
                summary[
                    "recovered_files"
                    if not source.exists()
                    else "identical_files"
                    if target.exists()
                    else "new_files"
                ] += 1
                if item and item["status"] == "complete":
                    summary["promoted_files"] += 1
                if not os.access(_existing_parent(target), os.R_OK | os.W_OK | os.X_OK):
                    raise MoneyflowContractError("history_target_permissions")
            counts = {fact.trade_date: fact.row_count for fact in plan.date_counts}
            for day in plan.units[unit_id].dates:
                if all(
                    state["files"].get(f"{day}/{layer}", {}).get("status") == "complete"
                    for layer in ("raw", "silver")
                ):
                    summary["promoted_dates"] += 1
                    summary["promoted_rows"] += counts[day]
    finally:
        control.finish()

    def file_path(plan, unit_id, day, layer, source, check):
        _, _, item, digest = locations[(plan.dataset, unit_id, day, layer)]
        return _file_location(lake_root, plan, day, layer, source, item, digest, check)

    _closed_prefix(root, control, plans, manifest["snapshots"], file_path=file_path)
    return states, locations, summary


def _promote_file(
    source, target, digest, item, state, state_path, key, control, store, row_count
):
    control.check()
    _check_path(target)
    if target.exists() and _hash_file(target, control.check) != digest:
        raise MoneyflowContractError("history_formal_conflict")
    if item is None:
        if not source.is_file() or _hash_file(source, control.check) != digest:
            raise MoneyflowContractError("history_candidate_changed")
        item = {
            "status": "intent",
            "mode": "reuse" if target.exists() else "move",
            "size": source.stat().st_size,
        }
        state["files"][key] = item
        store.json(state_path, state)
    if not target.exists():
        if (
            item["mode"] != "move"
            or not source.is_file()
            or _hash_file(source, control.check) != digest
        ):
            raise MoneyflowContractError("history_candidate_missing")
        target.parent.mkdir(parents=True, exist_ok=True)
        _check_path(target)
        if not _same_device(source, target.parent):
            raise MoneyflowContractError("history_cross_device")
        _fsync(source)
        control.check()
        if target.exists():
            raise MoneyflowContractError("history_formal_changed")
        os.replace(source, target)
        _fsync(source.parent)
        _fsync(target.parent)
    if (
        _hash_file(target, control.check) != digest
        or target.stat().st_size != item["size"]
    ):
        raise MoneyflowContractError("history_formal_changed")
    control.check()
    item["status"] = "complete"
    store.json(state_path, state)
    completed_day = key.endswith("/silver")
    control.progress(
        stage="promoting",
        promoted_files=control.budget["promoted_files"] + 1,
        current_file=key,
        promoted_dates=control.budget["promoted_dates"] + int(completed_day),
        promoted_rows=control.budget["promoted_rows"]
        + (row_count if completed_day else 0),
    )


def promote_moneyflow_history_cohort(
    *,
    staging_root: Path,
    operation_id: str,
    cutoff: str,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    apply: bool = False,
    cancel=lambda: False,
    clock=time.monotonic,
) -> dict:
    """Default preflight only; APPLY requires separate formal Lake authorization."""
    if type(apply) is not bool:
        raise MoneyflowContractError("history_promotion_action")
    _validate_roots(lake_root, staging_root)
    root = moneyflow_candidate_directory(
        staging_root, operation_id, cutoff, dataset="moneyflow"
    ).parents[1]
    manifest, units, closed, plans = _frozen(root, cutoff)
    contract = _promotion_contract(manifest, closed, lake_root)
    contract_path = root / "promotion-contract.json"
    if contract_path.exists() and _read_json(contract_path) != contract:
        raise MoneyflowContractError("history_promotion_contract_changed")
    with _operation(
        staging_root,
        operation_id,
        cutoff,
        cancel,
        clock,
        external_bytes=lambda current, check: _moved_bytes(
            current, units, closed, contract, lake_root, check
        ),
        promotion=True,
    ) as (current, store, control, _identity):
        # Re-read frozen control facts under the same namespace writer lock.
        fresh, fresh_units, fresh_closed, _ = _frozen(current, cutoff)
        if fresh != manifest or fresh_units != units or fresh_closed != closed:
            raise MoneyflowContractError("history_cohort_changed")
        if contract_path.exists() and _read_json(contract_path) != contract:
            raise MoneyflowContractError("history_promotion_contract_changed")
        control.progress(stage="promotion_preflight")
        states, locations, summary = _preflight(
            root, manifest, units, closed, plans, contract, lake_root, control
        )
        if not contract_path.exists():
            store.json(contract_path, contract)
        control.progress(
            promotion_started=True,
            promoted_files=summary["promoted_files"],
            promoted_dates=summary["promoted_dates"],
            promoted_rows=summary["promoted_rows"],
            total_files=contract["total_files"],
            promoted_units=sum(s["stage"] == "complete" for s in states.values()),
            promotion_contract_hash=contract["contract_hash"],
            stage="promotion_planned",
        )
        if not apply:
            return {**summary, **control.budget, "apply": False}
        for index, (plan, unit_id) in enumerate(units):
            control.check()
            directory, _checkpoint, state_path, state = _promotion_state(
                root, plan, unit_id, closed[index], contract
            )
            if state["stage"] == "complete":
                continue
            receipt, entries = _receipt_files(root, plan, unit_id)
            control.progress(
                dataset=plan.dataset, current_unit=unit_id, stage="promotion_audit"
            )
            control.start("promotion_audit")
            try:

                def day_paths(day, plan=plan, unit_id=unit_id, state=state):
                    paths = []
                    for layer in ("raw", "silver"):
                        source, _target_path, _item, digest = locations[
                            (plan.dataset, unit_id, day, layer)
                        ]
                        # Refresh mutable state after a previous partial APPLY.
                        item = state["files"].get(f"{day}/{layer}")
                        paths.append(
                            _file_location(
                                lake_root,
                                plan,
                                day,
                                layer,
                                source,
                                item,
                                digest,
                                control.check,
                            )
                        )
                    return tuple(paths)

                _audit_files(
                    directory, receipt, plan, unit_id, control, file_paths=day_paths
                )
                store.json(state_path, state)
            finally:
                control.finish()
            control.start("promoting")
            try:
                counts = {fact.trade_date: fact.row_count for fact in plan.date_counts}
                for day, layer, source, digest in entries:
                    key = f"{day}/{layer}"
                    item = state["files"].get(key)
                    if item and item["status"] == "complete":
                        continue
                    _promote_file(
                        source,
                        _target(lake_root, plan, day, layer),
                        digest,
                        item,
                        state,
                        state_path,
                        key,
                        control,
                        store,
                        counts[day],
                    )
                state["stage"] = "complete"
                store.json(state_path, state)
                control.progress(
                    stage="promotion_unit_complete",
                    promoted_units=control.budget["promoted_units"] + 1,
                )
            finally:
                control.finish()
        control.progress(stage="files_complete", retained_bytes=store.used)
        return {**control.budget, "apply": True}
