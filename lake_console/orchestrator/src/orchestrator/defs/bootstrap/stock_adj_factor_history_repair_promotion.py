"""One approved repair chain: immutable proofs, atomic promotion and recovery.

This module never requests source data, computes business SQL or reports DG events.
"""

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path

from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    RepairBudget,
    check_repair_cancel,
    check_repair_path,
    repair_hash,
    sync_repair_directory,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_candidates import (
    read_repair_candidate_record,
    repair_record_path,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
    RepairRuntime,
    RepairStorageLedger,
    current_repair_runtime,
    use_repair_runtime,
    write_repair_json,
)


def promotion_record_path(plan, target):
    relative = Path(target).relative_to(Path(plan["lake_root"])).as_posix()
    return (
        Path(plan["run_root"])
        / "checkpoints/promotions"
        / (hashlib.sha256(relative.encode()).hexdigest() + ".json")
    )


def _checkpoint(plan):
    path = check_repair_path(Path(plan["run_root"]) / "checkpoint.json")
    return json.loads(path.read_text()) if path.exists() else {}


@contextmanager
def repair_writer_lock(root):
    """Capability-wide lock; it does not lock ordinary Dagster jobs."""
    path = check_repair_path(Path(root).parent / "writer.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise FactorRepairError("repair_candidate_writer_busy") from error
        yield lock


def _ordered_targets(plan):
    def order(unit):
        asset = unit["asset_key"]
        if asset == "raw_tushare_adj_factor":
            return 0
        if asset == "silver_adj_factor":
            return 1
        if asset == "gold_stock_daily_qfq" or asset in {
            f"gold_stk_mins_qfq_{f}m" for f in (1, 5, 15, 30, 60, 90, 120)
        }:
            return 2
        return 4 if "state" in asset else 3

    return [
        (unit, Path(name))
        for unit in sorted(plan["units"], key=lambda u: (order(u), u["asset_key"]))
        for name in sorted(unit["target_paths"])
    ]


def _read_record(plan, runtime, unit, target):
    record = json.loads(
        check_repair_path(
            repair_record_path(runtime.root, target, runtime.lake_root)
        ).read_text()
    )
    relative = target.relative_to(runtime.lake_root).as_posix()
    preimage = runtime.preimages[str(target)]
    if (
        record.get("format_version") != 2
        or record.get("commit_pending")
        or record.get("business_pending")
        or record.get("validated") is not True
        or record.get("plan_hash") != plan["plan_hash"]
        or record.get("asset_key") != unit["asset_key"]
        or record.get("target_relative_path") != relative
        or record.get("unit_id")
        != repair_hash([plan["plan_hash"], unit["asset_key"], str(target)])
        or record.get("preimage_sha256") != preimage["sha256"]
        or record.get("record_hash")
        != repair_hash({k: v for k, v in record.items() if k != "record_hash"})
        or type(record.get("no_op")) is not bool
        or any(
            type(record.get(k)) is not int or record[k] < 0
            for k in (
                "original_rows",
                "replacement_rows",
                "changed_stock_rows",
                "candidate_rows",
                "candidate_bytes",
            )
        )
        or record["candidate_rows"] != record["original_rows"]
        or record["changed_stock_rows"] > record["replacement_rows"]
        or record["no_op"] != (record["changed_stock_rows"] == 0)
        or str(target) not in record.get("input_paths", [])
    ):
        raise FactorRepairError("repair_candidate_record_invalid")
    expected_path = None if record["no_op"] else "candidates/" + relative
    if record.get("candidate_relative_path") != expected_path:
        raise FactorRepairError("repair_candidate_path_invalid")
    if record["no_op"] and (
        record["candidate_sha256"] != preimage["sha256"]
        or record["candidate_bytes"] != 0
    ):
        raise FactorRepairError("repair_candidate_record_invalid")
    runtime.restore_binding(record, restore_inputs=False)
    return record


def _promotion_binding(plan, runtime, record, chain_hash):
    return {
        "version": 2,
        "run_id": plan["run_id"],
        "plan_hash": plan["plan_hash"],
        "implementation_binding": runtime.binding,
        "asset_key": record["asset_key"],
        "unit_id": record["unit_id"],
        "target_relative_path": record["target_relative_path"],
        "candidate_record_hash": record["record_hash"],
        "candidate_chain": chain_hash,
        **{
            k: record[k]
            for k in (
                "preimage_sha256",
                "candidate_sha256",
                "candidate_relative_path",
                "candidate_bytes",
                "no_op",
            )
        },
    }


def _load_promotion(plan, runtime, target, record, chain_hash):
    path = promotion_record_path(plan, target)
    if not path.exists():
        return None
    value = json.loads(check_repair_path(path).read_text())
    binding = _promotion_binding(plan, runtime, record, chain_hash)
    if (
        any(value.get(k) != v for k, v in binding.items())
        or value.get("status") not in {"PREPARED", "COMMITTED", "SKIPPED"}
        or value.get("checkpoint_hash")
        != repair_hash({k: v for k, v in value.items() if k != "checkpoint_hash"})
        or (value["status"] == "SKIPPED") != record["no_op"]
    ):
        raise FactorRepairError("repair_promotion_record_invalid")
    if value["status"] in {"COMMITTED", "SKIPPED"}:
        readback = value.get("readback", {})
        if (
            value.get("accounting_settled") is not True
            or not value.get("completed_at")
            or readback.get("path") != str(target)
            or readback.get("sha256") != record["candidate_sha256"]
            or (
                value["status"] == "COMMITTED"
                and (
                    value.get("directory_sync") is not True
                    or readback.get("size") != record["candidate_bytes"]
                )
            )
        ):
            raise FactorRepairError("repair_promotion_readback_required")
    return value


def _output_location(plan, runtime, target, record, promotion, *, cancel=None, progress=None):
    """Keep the candidate reader strict; promoted outputs have a separate resolver."""
    observed = runtime.identity(check_repair_path(target), cancel=cancel, progress=progress)
    old, new = record["preimage_sha256"], record["candidate_sha256"]
    if record["no_op"]:
        if observed.sha256 != old:
            raise FactorRepairError("target_drift")
        return target, "SKIPPED" if promotion else "PENDING"
    candidate = check_repair_path(runtime.root / record["candidate_relative_path"])
    if promotion and promotion["status"] == "COMMITTED":
        if observed.sha256 != new or candidate.exists():
            raise FactorRepairError("repair_promotion_output_drift")
        return target, "COMMITTED"
    if observed.sha256 == old and candidate.is_file():
        identity = runtime.identity(candidate, cancel=cancel, progress=progress)
        if identity.sha256 != new or identity.size != record["candidate_bytes"]:
            raise FactorRepairError("repair_candidate_drift")
        return candidate, "PENDING"
    if (
        promotion
        and promotion["status"] == "PREPARED"
        and observed.sha256 == new
        and not candidate.exists()
        and observed.size == record["candidate_bytes"]
    ):
        return target, "RECOVER"
    raise FactorRepairError("repair_promotion_output_drift")


def _chain_evidence(plan, records):
    body = {
        "version": 2,
        "plan_hash": plan["plan_hash"],
        "implementation_hash": repair_hash(plan["implementation_fingerprints"]),
        "records_hash": repair_hash(
            [(r["target_relative_path"], r["record_hash"]) for r in records]
        ),
        "assets": sorted({r["asset_key"] for r in records}),
        "targets": len(records),
        "candidate_files": sum(not r["no_op"] for r in records),
        "no_op_files": sum(r["no_op"] for r in records),
        "candidate_bytes": sum(r["candidate_bytes"] for r in records),
    }
    return {**body, "chain_hash": repair_hash(body)}


def seal_repair_candidate_chain(plan, *, cancel=None):
    """One metadata/physical aggregation; no repeated formula or business validation."""
    runtime = current_repair_runtime(plan)
    if runtime is None:
        with use_repair_runtime(RepairRuntime(plan, admitted=True)):
            return seal_repair_candidate_chain(plan, cancel=cancel)
    if _checkpoint(plan).get("promotion"):
        raise FactorRepairError("repair_promotion_resume_required")
    records = []
    for unit, target in _ordered_targets(plan):
        check_repair_cancel(cancel)
        records.append(read_repair_candidate_record(plan, target))
    for phase in ("factor", "price", "indicator"):
        summary = json.loads(
            check_repair_path(runtime.root / (phase + "-audit.json")).read_text()
        )
        if (
            summary.get("plan_hash") != plan["plan_hash"]
            or summary.get("sample") is not False
            or summary.get("status") != phase.upper() + "_CANDIDATES_VERIFIED"
        ):
            raise FactorRepairError("repair_chain_incomplete")
    chain = _chain_evidence(plan, records)
    write_repair_json(
        runtime.root / "checkpoint.json",
        {**_checkpoint(plan), "candidate_chain": chain},
    )
    return chain


def audit_repair_chain_for_promotion(plan, *, cancel=None, progress=None):
    """Read-only, including partial promotion; never repairs a missing seal."""
    runtime = current_repair_runtime(plan)
    if runtime is None:
        with use_repair_runtime(RepairRuntime(plan, admitted=True)):
            return audit_repair_chain_for_promotion(plan, cancel=cancel, progress=progress)
    chain = _checkpoint(plan).get("candidate_chain")
    if not isinstance(chain, dict):
        raise FactorRepairError("repair_chain_seal_required")
    rows = []
    targets = _ordered_targets(plan)
    last_emit = 0.0
    target = None
    def identity_progress(read=0, total=0, *, force=False):
        nonlocal last_emit
        now = time.monotonic()
        if progress and (force or now - last_emit >= RepairBudget().progress_interval * 5 / 6):
            last_emit = now
            progress({"phase": "promotion_admission", "verified_targets": len(rows),
                "total_targets": len(targets), "current_target": str(target) if target else None,
                "identity_bytes_read": read, "identity_total_bytes": total, "updated_at": time.time()})
    identity_progress(force=True)
    for unit, target in targets:
        check_repair_cancel(cancel)
        record = _read_record(plan, runtime, unit, target)
        promotion = _load_promotion(
            plan, runtime, target, record, chain.get("chain_hash")
        )
        location, status = _output_location(plan, runtime, target, record, promotion,
            cancel=cancel, progress=identity_progress)
        rows.append((target, record, promotion, location, status))
        identity_progress()
    identity_progress(force=True)
    if _chain_evidence(plan, [r for _, r, _, _, _ in rows]) != chain:
        raise FactorRepairError("repair_chain_binding_invalid")
    by_target = {str(target): record for target, record, _, _, _ in rows}
    for target, record, _, _, _ in rows:
        check_repair_cancel(cancel)
        for name, digest in record.get("overlay_hashes", {}).items():
            if name not in by_target or by_target[name]["candidate_sha256"] != digest:
                raise FactorRepairError("repair_overlay_drift")
        # Immutable task/fragment identities were already admitted by the chain seal.
        # Reuse the seal only while the referenced evidence still has the same version.
        for identity in record.get("replay_files", []):
            if (
                asdict(runtime.identity(check_repair_path(Path(identity["path"])),
                    cancel=cancel, progress=identity_progress))
                != identity
            ):
                raise FactorRepairError("repair_indicator_fragment_drift")
        for task in record.get("replay_tasks", []):
            marker = task["marker"]
            if (
                asdict(runtime.identity(check_repair_path(Path(marker["path"])),
                    cancel=cancel, progress=identity_progress))
                != marker
            ):
                raise FactorRepairError("repair_indicator_fragment_drift")
    assets = {}
    for _, record, _, _, status in rows:
        summary = assets.setdefault(
            record["asset_key"],
            {"targets": 0, "completed": 0, "remaining": 0, "no_op": 0, "bytes": 0},
        )
        summary["targets"] += 1
        summary["bytes"] += record["candidate_bytes"]
        summary["no_op"] += int(record["no_op"])
        summary["completed" if status in {"COMMITTED", "SKIPPED"} else "remaining"] += 1
    return {
        "plan_hash": plan["plan_hash"],
        "chain": chain,
        "assets": assets,
        "rows": rows,
        "manifest_reference": str(runtime.root / "reports/promotion_manifest.csv"),
        "completed": all(status in {"COMMITTED", "SKIPPED"} for *_, status in rows),
    }


def _write_promotion(plan, target, value):
    value = {k: v for k, v in value.items() if k != "checkpoint_hash"}
    value["checkpoint_hash"] = repair_hash(value)
    write_repair_json(promotion_record_path(plan, target), value)
    return value


def _commit_file(plan, runtime, target, record, previous, location, status, chain_hash):
    binding = _promotion_binding(plan, runtime, record, chain_hash)
    if status in {"COMMITTED", "SKIPPED"}:
        return previous
    value = previous or {
        **binding,
        "status": "SKIPPED" if record["no_op"] else "PREPARED",
        "prepared_at": time.time(),
    }
    if record["no_op"]:
        return _write_promotion(
            plan,
            target,
            {
                **value,
                "completed_at": time.time(),
                "readback": asdict(runtime.identity(target)),
                "accounting_settled": True,
            },
        )
    if previous is None:
        value = _write_promotion(plan, target, value)
    candidate = check_repair_path(runtime.root / record["candidate_relative_path"])
    if status == "PENDING":
        before = candidate.stat()
        admitted = runtime.identity(candidate)
        preimage = runtime.identity(target)
        actual_target = target.stat()
        if (before.st_size, before.st_mtime_ns) != (
            admitted.size,
            admitted.mtime_ns,
        ) or (actual_target.st_size, actual_target.st_mtime_ns) != (
            preimage.size,
            preimage.mtime_ns,
        ):
            raise FactorRepairError("repair_promotion_output_drift")
        if before.st_dev != target.parent.stat().st_dev:
            raise FactorRepairError("repair_filesystem_mismatch")
        with candidate.open("rb") as handle:
            source = os.fstat(handle.fileno())
            if (source.st_dev, source.st_ino, source.st_size, source.st_mtime_ns) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ):
                raise FactorRepairError("repair_candidate_drift")
            identity = runtime.identity(candidate)
            with runtime.storage.writing(candidate):
                os.replace(candidate, target)
                sync_repair_directory(target.parent)
                sync_repair_directory(candidate.parent)
                output = target.stat()
                runtime.forget(target)
                if (
                    output.st_dev,
                    output.st_ino,
                    output.st_size,
                    output.st_mtime_ns,
                ) == (source.st_dev, source.st_ino, source.st_size, source.st_mtime_ns):
                    runtime.identities[str(target)] = replace(
                        identity, path=str(target)
                    )
                else:
                    observed = runtime.identity(target)
                    if observed.sha256 != record["candidate_sha256"]:
                        raise FactorRepairError("repair_promotion_output_drift")
            runtime.forget(candidate)
    else:
        # PREPARED + new formal output: settle metadata only, never rename again.
        sync_repair_directory(target.parent)
        sync_repair_directory(candidate.parent)
    identity = runtime.identity(target)
    return _write_promotion(
        plan,
        target,
        {
            **value,
            "status": "COMMITTED",
            "completed_at": time.time(),
            "readback": asdict(identity),
            "accounting_settled": True,
            "directory_sync": True,
            "device": target.stat().st_dev,
            "inode": target.stat().st_ino,
        },
    )


def _write_reports(plan, runtime, entries, *, failure=None):
    fields = [
        "asset_key",
        "target_relative_path",
        "status",
        "checkpoint_status",
        "preimage_sha256",
        "candidate_sha256",
        "candidate_record_hash",
        "changed_stock_rows",
        "approved_scope",
        "completed_at",
        "reason_code",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for record, promotion in entries:
        writer.writerow(
            {
                **{k: promotion.get(k, "") for k in fields},
                "checkpoint_status": promotion["status"],
                "changed_stock_rows": record["changed_stock_rows"],
                "approved_scope": record["business_proof"]["approved_keys"],
                "reason_code": "",
            }
        )
    failed = io.StringIO(newline="")
    failure_writer = csv.DictWriter(failed, fieldnames=fields)
    failure_writer.writeheader()
    if failure is not None:
        record, error = failure
        target = runtime.lake_root / record["target_relative_path"]
        saved_path = check_repair_path(promotion_record_path(plan, target))
        saved = json.loads(saved_path.read_text()) if saved_path.is_file() else {}
        failure_writer.writerow({**{k: record.get(k, "") for k in fields},
            "status": "ATTEMPT_FAILED", "checkpoint_status": saved.get("status", "NOT_PREPARED"),
            "candidate_record_hash": record["record_hash"],
            "approved_scope": record["business_proof"]["approved_keys"],
            "reason_code": str(error)[:300]})
    for name, text in (
        ("promotion_manifest.csv", stream.getvalue()),
        ("failures.csv", failed.getvalue()),
    ):
        path = check_repair_path(runtime.root / "reports" / name)
        temporary = Path(str(path) + ".partial")
        path.parent.mkdir(parents=True, exist_ok=True)
        with runtime.storage.writing(
            path, reserve_bytes=len(text.encode()), temporary=temporary
        ):
            with temporary.open("w", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            sync_repair_directory(path.parent)


def promote_repair_files(
    plan_path,
    expected_hash,
    *,
    dry_run=False,
    maintenance_confirmed=False,
    writer_guard=None,
    cancel=None,
    progress=None,
):
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
        load_repair_plan,
        repair_coordinator_termination_guard,
        repair_storage_totals,
    )

    if dry_run == maintenance_confirmed:
        raise FactorRepairError("repair_promotion_mode_required")
    plan = load_repair_plan(Path(plan_path), expected_hash, cancel=cancel, progress=progress)
    runtime = RepairRuntime(plan, admitted=True)
    with use_repair_runtime(runtime):
        audit = audit_repair_chain_for_promotion(plan, cancel=cancel, progress=progress)
        public = {k: v for k, v in audit.items() if k != "rows"}
        finalized = _checkpoint(plan).get("promotion", {}).get("status") == "FILES_COMPLETE_EVENTS_PENDING"
        if finalized and any(not (runtime.root / "reports" / name).is_file()
                             for name in ("promotion_manifest.csv", "failures.csv")):
            raise FactorRepairError("repair_promotion_report_missing")
        if dry_run or audit["completed"] and finalized:
            return public
        if not audit["completed"] and not callable(writer_guard):
            raise FactorRepairError("repair_writer_guard_required")
        with (
            repair_coordinator_termination_guard(),
            repair_writer_lock(runtime.root),
            Path(plan_path).open("rb") as lock,
        ):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise FactorRepairError("repair_candidate_writer_busy") from error
            if not audit["completed"]:
                writer_guard(plan)
            from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
                indicator_replay_tasks,
            )

            indicator_replay_tasks(plan)
            runtime.storage = RepairStorageLedger(
                runtime.root, scan=repair_storage_totals, plan=plan, promotion_only=True
            )
            runtime.storage.persist(
                {
                    "promotion": {"status": "PROMOTING", "plan_hash": expected_hash},
                }
            )
            entries = []
            for target, record, previous, location, status in audit["rows"]:
                check_repair_cancel(cancel)
                try:
                    result = _commit_file(plan, runtime, target, record, previous,
                        location, status, audit["chain"]["chain_hash"])
                except Exception as error:
                    try:
                        _write_reports(plan, runtime, entries, failure=(record, error))
                    except (OSError, FactorRepairError, ValueError) as report_error:
                        error.add_note(f"repair_failure_report_unavailable:{report_error}")
                    raise
                entries.append((record, result))
                if progress:
                    progress(
                        {
                            "phase": "promotion",
                            "current_target": str(target),
                            "completed": len(entries),
                            "total": len(audit["rows"]),
                            "updated_at": time.time(),
                        }
                    )
            _write_reports(plan, runtime, entries)
            runtime.storage.reconcile()
            runtime.storage.persist(
                {
                    "promotion": {
                        "status": "FILES_COMPLETE_EVENTS_PENDING",
                        "plan_hash": expected_hash,
                        "completed": len(entries),
                    }
                }
            )
            public.update(
                completed=True,
                status="FILES_COMPLETE_EVENTS_PENDING",
                counters=dict(runtime.counters),
            )
            return public
