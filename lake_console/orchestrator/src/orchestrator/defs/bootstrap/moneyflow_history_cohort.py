"""Seven independent history plans with one durable execution budget and writer."""

import hashlib
import io
import json
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from orchestrator.defs.bootstrap.moneyflow_history_candidates import (
    _attempt_path,
    _build_unit,
    _Control,
    _identity,
    _MemorySink,
    _read_json,
    _receipt_scope,
    _Store,
    _validate_receipt,
    _writer_lock,
)
from orchestrator.defs.bootstrap.moneyflow_history_metadata import (
    MoneyflowHistoryMetadataRequest,
    expected_history_scopes,
    parse_moneyflow_history_metadata,
    validate_moneyflow_history_metadata,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    MoneyflowHistoryDateCount,
    _hash,
    build_moneyflow_history_plan,
)
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_directory
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_DATASETS,
    MONEYFLOW_HISTORY_EXTRA_REQUESTS,
    MONEYFLOW_HISTORY_MAX_BUFFER_BYTES,
    MONEYFLOW_HISTORY_MIN_FREE_BYTES,
    MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
)


def _cohort_identity(cutoff):
    templates = [
        build_moneyflow_history_plan(
            ds, (MoneyflowHistoryDateCount(cutoff, 1, 1),), cutoff=cutoff
        )
        for ds in MONEYFLOW_HISTORY_DATASETS
    ]
    return {
        "revision": "moneyflow_history_cohort_dates_v1",
        "cutoff": cutoff,
        "dataset_contracts": {p.dataset: p.plan_hash for p in templates},
        "limits": _identity(templates[0])["limits"],
        "extra_requests": MONEYFLOW_HISTORY_EXTRA_REQUESTS,
    }


def _large_json(path):
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > MONEYFLOW_HISTORY_MAX_BUFFER_BYTES
    ):
        raise MoneyflowContractError("history_cohort_file")
    try:
        value = json.loads(path.read_bytes())
    except (ValueError, UnicodeError) as error:
        raise MoneyflowContractError("history_cohort_invalid") from error
    if not isinstance(value, dict):
        raise MoneyflowContractError("history_cohort_invalid")
    return value


def _write_large(store, path, value):
    if (
        len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
        > MONEYFLOW_HISTORY_MAX_BUFFER_BYTES
    ):
        raise MoneyflowContractError("history_cohort_bytes")
    store.json(path, value)


@contextmanager
def _operation(staging_root, operation_id, cutoff, cancel, clock):
    base = moneyflow_candidate_directory(
        staging_root, operation_id, cutoff, dataset=MONEYFLOW_HISTORY_DATASETS[0]
    )
    root, namespace = base.parents[1], base.parents[2]
    existing = namespace
    while not existing.exists():
        existing = existing.parent
    marker = root / "cohort-control.json"
    if shutil.disk_usage(existing).free < (
        2 * MONEYFLOW_HISTORY_MAX_BUFFER_BYTES
        if marker.exists()
        else MONEYFLOW_HISTORY_MIN_FREE_BYTES
    ):
        raise MoneyflowContractError("history_free_space")
    if cancel():
        raise InterruptedError("history_cancelled")
    namespace.mkdir(parents=True, exist_ok=True)
    with _writer_lock(namespace):
        identity = _cohort_identity(cutoff)
        if marker.exists():
            if _read_json(marker) != identity:
                raise MoneyflowContractError("history_execution_contract_changed")
        elif root.exists() and any(root.iterdir()):
            raise MoneyflowContractError("history_legacy_operation")
        root.mkdir(exist_ok=True)
        started = clock()

        def inventory_check():
            if cancel():
                raise InterruptedError("history_cancelled")
            assert_moneyflow_memory_budget()
            if not 0 <= clock() - started <= MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS:
                raise MoneyflowContractError("history_unit_timeout")

        store = _Store(
            root, inventory_check, json_limit=MONEYFLOW_HISTORY_MAX_BUFFER_BYTES
        )
        # Inventory checks apply only to this initial metadata walk; subsequent
        # failure recounts use the current operation cancellation guard.
        store.check = lambda: None
        if not marker.exists():
            store.json(marker, identity)
        existing_progress = (
            _large_json(root / "progress.json")
            if (root / "progress.json").exists()
            else {}
        )
        total = existing_progress.get("total_units", 0)
        if type(total) is not int or total < 0:
            raise MoneyflowContractError("history_checkpoint_progress")
        frozen = (root / "cohort.json").exists()
        maximum = (
            2 * len(MONEYFLOW_HISTORY_DATASETS)
            + 2 * total
            + MONEYFLOW_HISTORY_EXTRA_REQUESTS
            if frozen
            else 2 * len(MONEYFLOW_HISTORY_DATASETS) + MONEYFLOW_HISTORY_EXTRA_REQUESTS
        )
        control = _Control(
            store,
            identity,
            0,
            total,
            clock,
            cancel,
            max_requests=maximum,
            read_progress=_large_json,
        )
        control.progress(eta="暂无法估算", max_requests=maximum)
        try:
            yield root, store, control, identity
        except (InterruptedError, MoneyflowContractError) as error:
            control.finish()
            store.recount()
            control.progress(
                stage="interrupted"
                if isinstance(error, InterruptedError)
                else "blocked",
                error_code=str(error),
            )
            raise


def _metadata(root, store, control, source, dataset, cutoff):
    control.progress(dataset=dataset, current_unit=None, stage="source_metadata")
    directory = root / "metadata" / dataset / uuid4().hex
    directory.mkdir(parents=True)
    request = MoneyflowHistoryMetadataRequest(dataset, cutoff, directory / "source.sql")
    control.start("source_metadata")
    try:
        store.reserve(MONEYFLOW_HISTORY_MAX_BUFFER_BYTES)
        with io.BytesIO() as buffer:
            control.record_source_copy()
            source.metadata(request, _MemorySink(buffer, control), control.check)
            if request.sql_path.is_file():
                store.add_file(request.sql_path)
            wire = buffer.getvalue()
            snapshot = parse_moneyflow_history_metadata(wire, dataset, cutoff)
            proof = {
                "dataset": dataset,
                "cutoff": cutoff,
                "wire_sha256": hashlib.sha256(wire).hexdigest(),
                "snapshot_hash": _hash(snapshot),
                "sql_sha256": hashlib.sha256(request.sql().encode()).hexdigest(),
                "wire_bytes": len(wire),
                "elapsed_seconds": control.clock() - control.started,
            }
            store.json(directory / "proof.json", proof)
            control.check()
            return snapshot, proof
    finally:
        control.finish()


def _manifest(identity, snapshots):
    if list(snapshots) != list(MONEYFLOW_HISTORY_DATASETS):
        raise MoneyflowContractError("history_cohort_datasets")
    plans = [
        validate_moneyflow_history_metadata(snapshots[ds], ds, identity["cutoff"])
        for ds in MONEYFLOW_HISTORY_DATASETS
    ]
    value = {
        **identity,
        "snapshots": snapshots,
        "plans": {
            p.dataset: {
                "plan_hash": p.plan_hash,
                "rows": p.row_count,
                "dates": len(p.date_counts),
                "units": len(p.units),
            }
            for p in plans
        },
        "total_units": sum(len(p.units) for p in plans),
        "total_rows": sum(p.row_count for p in plans),
        "total_dates": sum(len(p.date_counts) for p in plans),
    }
    value["max_requests"] = (
        2 * len(MONEYFLOW_HISTORY_DATASETS)
        + 2 * value["total_units"]
        + MONEYFLOW_HISTORY_EXTRA_REQUESTS
    )
    value["cohort_hash"] = _hash(value)
    return value, plans


def _freeze(root, store, control, identity, source):
    path = root / "cohort.json"
    if path.exists():
        saved = _large_json(path)
        snapshots = saved.get("snapshots")
        if not isinstance(snapshots, dict):
            raise MoneyflowContractError("history_cohort_invalid")
        expected, plans = _manifest(identity, snapshots)
        if saved != expected or control.budget["total_units"] not in (
            0,
            expected["total_units"],
        ):
            raise MoneyflowContractError("history_cohort_changed")
        control.max_requests = expected["max_requests"]
        for dataset in MONEYFLOW_HISTORY_DATASETS:
            current, _ = _metadata(
                root, store, control, source, dataset, identity["cutoff"]
            )
            if current != snapshots[dataset]:
                raise MoneyflowContractError("history_source_metadata_changed")
    else:
        snapshots = {}
        directory = root / "source-freeze"
        directory.mkdir(exist_ok=True)
        for dataset in MONEYFLOW_HISTORY_DATASETS:
            control.check()
            frozen_path = directory / (dataset + ".json")
            if frozen_path.exists():
                saved = _large_json(frozen_path)
                if (
                    set(saved) != {"snapshot", "proofs"}
                    or not isinstance(saved["proofs"], list)
                    or len(saved["proofs"]) != 2
                ):
                    raise MoneyflowContractError("history_cohort_invalid")
                snapshot = saved["snapshot"]
                validate_moneyflow_history_metadata(
                    snapshot, dataset, identity["cutoff"]
                )
                if any(
                    p.get("snapshot_hash") != _hash(snapshot) for p in saved["proofs"]
                ):
                    raise MoneyflowContractError("history_cohort_changed")
                # Partial freeze recovery still checks today's source once.
                current, _ = _metadata(
                    root, store, control, source, dataset, identity["cutoff"]
                )
                if current != snapshot:
                    raise MoneyflowContractError("history_source_metadata_changed")
            else:
                snapshot, first = _metadata(
                    root, store, control, source, dataset, identity["cutoff"]
                )
                second_snapshot, second = _metadata(
                    root, store, control, source, dataset, identity["cutoff"]
                )
                if snapshot != second_snapshot:
                    raise MoneyflowContractError("history_source_metadata_changed")
                _write_large(
                    store,
                    frozen_path,
                    {"snapshot": snapshot, "proofs": [first, second]},
                )
            snapshots[dataset] = snapshot
        expected, plans = _manifest(identity, snapshots)
        _write_large(store, path, expected)
        control.max_requests = expected["max_requests"]
    control.progress(
        stage="source_frozen",
        cohort_hash=expected["cohort_hash"],
        total_units=expected["total_units"],
        max_requests=expected["max_requests"],
    )
    return expected, plans


def freeze_moneyflow_history_cohort(
    *,
    staging_root: Path,
    operation_id: str,
    cutoff: str,
    source,
    cancel=lambda: False,
    clock=time.monotonic,
) -> dict:
    """Read-only source metadata; no business COPY, candidates or DG writes."""
    with _operation(staging_root, operation_id, cutoff, cancel, clock) as (
        root,
        store,
        control,
        identity,
    ):
        manifest, _ = _freeze(root, store, control, identity, source)
        return manifest


def _units(plans):
    return [(plan, unit.unit_id) for plan in plans for unit in plan.units]


def _hash_file(path, check):
    if path.is_symlink() or not path.is_file():
        raise MoneyflowContractError("history_checkpoint_files")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            check()
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _closed_prefix(root, control, plans, snapshots):
    closed = control.budget.get("closed_units", [])
    units = _units(plans)
    if (
        not isinstance(closed, list)
        or len(closed) != control.budget["completed_units"]
        or len(closed) > len(units)
    ):
        raise MoneyflowContractError("history_checkpoint_progress")
    # Hash verification uses bounded steps; it never decodes old Parquet again.
    for index, entry in enumerate(closed):
        plan, unit_id = units[index]
        directory = (
            root
            / plan.dataset
            / plan.cutoff
            / "history_candidates"
            / f"unit-{unit_id:06d}"
        )
        checkpoint = directory / "checkpoint.json"
        control.progress(
            dataset=plan.dataset,
            current_unit=unit_id,
            global_unit=index,
            stage="closed_prefix_audit",
        )
        control.start("closed_prefix_audit")
        try:
            if (
                not isinstance(entry, dict)
                or entry.get("dataset") != plan.dataset
                or entry.get("unit_id") != unit_id
                or _hash_file(checkpoint, control.check)
                != entry.get("checkpoint_sha256")
            ):
                raise MoneyflowContractError("history_closed_checkpoint_changed")
            receipt = _read_json(checkpoint)
            _validate_receipt(receipt, _receipt_scope(plan, unit_id, _identity(plan)))
            expected_dates = [
                [f.trade_date, f.row_count]
                for f in plan.date_counts
                if f.trade_date in plan.units[unit_id].dates
            ]
            expected_scopes = expected_history_scopes(
                snapshots[plan.dataset], plan.units[unit_id].dates
            )
            if (
                entry.get("date_counts") != expected_dates
                or receipt["stage"] != "verified"
                or receipt.get("difference_count") != 0
            ):
                raise MoneyflowContractError("history_closed_checkpoint_changed")
            for proof_name in ("source_proof", "verification_proof"):
                proof = receipt.get(proof_name, {})
                if (
                    proof.get("date_counts") != expected_dates
                    or proof.get("scope_counts") != expected_scopes
                    or proof.get("rows") != plan.units[unit_id].row_count
                ):
                    raise MoneyflowContractError("history_closed_checkpoint_changed")
            files = receipt.get("files")
            if not isinstance(files, list) or len(files) != len(expected_dates):
                raise MoneyflowContractError("history_checkpoint_files")
            attempt = _attempt_path(directory, receipt.get("attempt"))
            for item, (day, rows) in zip(files, expected_dates, strict=True):
                if (
                    item.get("trade_date") != day
                    or item.get("rows") != rows
                    or (attempt / day).is_symlink()
                ):
                    raise MoneyflowContractError("history_checkpoint_files")
                for layer in ("raw", "silver"):
                    if _hash_file(
                        attempt / day / (layer + ".parquet"), control.check
                    ) != item.get(layer + "_sha256"):
                        raise MoneyflowContractError("history_candidate_changed")
        finally:
            control.finish()
    return units, list(closed)


def build_moneyflow_history_cohort_candidates(
    *,
    staging_root: Path,
    operation_id: str,
    cutoff: str,
    source,
    cancel=lambda: False,
    clock=time.monotonic,
) -> dict:
    """Freeze/revalidate sources and build seven plans under one durable budget."""
    with _operation(staging_root, operation_id, cutoff, cancel, clock) as (
        root,
        store,
        control,
        identity,
    ):
        manifest, plans = _freeze(root, store, control, identity, source)
        units, closed = _closed_prefix(root, control, plans, manifest["snapshots"])
        for index in range(len(closed), len(units)):
            plan, unit_id = units[index]
            control.check()
            control.expected_scopes = expected_history_scopes(
                manifest["snapshots"][plan.dataset], plan.units[unit_id].dates
            )
            control.progress(
                dataset=plan.dataset,
                current_unit=unit_id,
                global_unit=index,
                percentage=100 * len(closed) / len(units),
            )
            directory = root / plan.dataset / plan.cutoff / "history_candidates"
            directory.mkdir(parents=True, exist_ok=True)
            receipt = _build_unit(
                directory,
                plan,
                unit_id,
                source,
                cancel,
                clock,
                store=store,
                control=control,
            )
            checkpoint = directory / f"unit-{unit_id:06d}" / "checkpoint.json"
            if receipt["stage"] != "verified":
                raise MoneyflowContractError("history_unit_not_verified")
            closed.append(
                {
                    "dataset": plan.dataset,
                    "unit_id": unit_id,
                    "checkpoint_sha256": _hash_file(checkpoint, control.check),
                    "date_counts": receipt["source_proof"]["date_counts"],
                }
            )
            control.progress(
                stage="unit_closed",
                closed_units=closed,
                completed_units=len(closed),
                percentage=100 * len(closed) / len(units),
            )
        control.progress(
            stage="candidates_verified", percentage=100, retained_bytes=store.used
        )
        return {"cohort_hash": manifest["cohort_hash"], **control.budget}
