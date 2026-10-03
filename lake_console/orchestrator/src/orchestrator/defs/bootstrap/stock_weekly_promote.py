"""Whole-audit preflight and recoverable single-file atomic Raw promotion."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    fingerprint,
    partition_path,
    validate_root,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    _atomic_json,
    _sync_directory,
    check_capture_path,
    check_weekly_cancel,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_weekly_raw import (
    load_relation,
    relation_hashes,
    validate_relation,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    WeeklyBudget,
    stable_weekly_hash,
    weekly_dataset_id,
    weekly_schema_hash,
)


def read_audit(path):
    check_capture_path(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise WeeklyCaptureError("audit_size_exceeded")
    audit = json.loads(path.read_text())
    digest = audit.pop("audit_hash")
    if (
        stable_weekly_hash(audit) != digest
        or audit["version"] != 1
        or audit["value_difference_rows"] != 0
    ):
        raise WeeklyCaptureError("audit_hash_mismatch")
    if (
        audit["candidate_manifest_hash"] != stable_weekly_hash(audit["files"])
        or audit["target_baseline_hash"]
        != stable_weekly_hash([(f["target"], f["baseline"]) for f in audit["files"]])
        or audit["source_evidence_hash"] != stable_weekly_hash(audit["source_evidence"])
    ):
        raise WeeklyCaptureError("audit_component_hash_mismatch")
    audit["audit_hash"] = digest
    source = StockWeeklySource(audit["source"])
    root = Path(audit["capture_root"])
    target_root = Path(audit["target_root"])
    validate_root(root, staging=True)
    validate_root(target_root, staging=False)
    assembly = Path(audit["assembly"])
    if assembly != path.parent or not assembly.is_relative_to(
        root / "stock_weekly_raw" / audit["plan_hash"] / "assemblies"
    ):
        raise WeeklyCaptureError("assembly_path_mismatch")
    if audit["schema_hash"] != weekly_schema_hash(source):
        raise WeeklyCaptureError("audit_schema_mismatch")
    if len(audit["files"]) > 54 or len({f["week"] for f in audit["files"]}) != len(
        audit["files"]
    ):
        raise WeeklyCaptureError("audit_file_budget_exceeded")
    for item in audit["files"]:
        candidate = Path(item["candidate"])
        target = Path(item["target"])
        check_capture_path(candidate)
        if (
            candidate.parent != assembly / "candidate" / f"week_end={item['week']}"
            or target != partition_path(target_root, source, item["week"])
        ):
            raise WeeklyCaptureError("audit_file_path_mismatch")
        if item["week"][:4] != str(audit["year"]):
            raise WeeklyCaptureError("audit_year_mismatch")
    return audit


def checkpoint_path(audit, item):
    return Path(audit["assembly"]) / "checkpoints" / f"{item['week']}.json"


def preflight(audit):
    outcomes = audit.get("source_key_outcomes")
    if outcomes and fingerprint(Path(outcomes["path"])) != outcomes["sha256"]:
        raise WeeklyCaptureError("source_key_outcomes_changed")
    for evidence in audit["source_evidence"]:
        if fingerprint(Path(evidence["path"])) != evidence["sha256"]:
            raise WeeklyCaptureError("source_evidence_changed")
    result = {}
    for item in audit["files"]:
        checkpoint = checkpoint_path(audit, item)
        check_capture_path(checkpoint)
        state = json.loads(checkpoint.read_text()) if checkpoint.exists() else None
        if state and (
            state["audit_hash"] != audit["audit_hash"]
            or state["sha256"] != item["sha256"]
        ):
            raise WeeklyCaptureError("promote_checkpoint_mismatch")
        target = Path(item["target"])
        if target.parent.exists() and any(
            p != target for p in target.parent.glob("*.parquet")
        ):
            raise WeeklyCaptureError("target_layout_changed")
        observed = fingerprint(target)
        recovered = bool(
            state
            and state["status"] in ("promoting", "verified")
            and observed == item["sha256"]
        )
        if not recovered and observed != item["baseline"]:
            raise WeeklyCaptureError("target_baseline_changed")
        if not recovered and fingerprint(Path(item["candidate"])) != item["sha256"]:
            raise WeeklyCaptureError("candidate_changed")
        if recovered and state["status"] == "verified" and observed != item["sha256"]:
            raise WeeklyCaptureError("verified_target_changed")
        if not recovered:
            parent = target.parent
            while not parent.exists():
                parent = parent.parent
            if Path(item["candidate"]).stat().st_dev != parent.stat().st_dev:
                raise WeeklyCaptureError("cross_device_promotion_forbidden")
        result[item["week"]] = recovered
    return result


def readback(connection, audit, item):
    source = StockWeeklySource(audit["source"])
    budget = WeeklyBudget(**audit["budget"])
    load_relation(connection, "weekly_promoted", [Path(item["target"])], source)
    validate_relation(connection, "weekly_promoted", source, budget, unique=True)
    if relation_hashes(connection, "weekly_promoted", source, budget) != {
        item["week"]: {"rows": item["rows"], "logical_hash": item["logical_hash"]}
    }:
        raise WeeklyCaptureError("promoted_readback_mismatch")
    if fingerprint(Path(item["target"])) != item["sha256"]:
        raise WeeklyCaptureError("promoted_hash_mismatch")


def promote_weekly_candidates(
    audit_path,
    *,
    apply=False,
    cancel=lambda: False,
    progress=lambda payload: None,
    fault_probe=lambda stage, week: None,
):
    """Default is read-only preflight; apply requires the caller's write authorization.

    fault_probe is an injected crash seam for isolated tests, never a force option.
    """
    audit = read_audit(audit_path)
    preflight(audit)
    if not apply:
        return {
            "status": "preflight",
            "files": len(audit["files"]),
            "partial_scope": audit["partial_scope"],
        }
    root = Path(audit["capture_root"])
    assembly = Path(audit["assembly"])
    source = StockWeeklySource(audit["source"])
    budget = WeeklyBudget(**audit["budget"])
    locks = root / "stock_weekly_raw" / "writer_locks" / weekly_dataset_id(source)
    check_capture_path(locks)
    locks.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        for item in sorted(audit["files"], key=lambda i: i["week"]):
            check_weekly_cancel(cancel)
            lock = locks / f"{item['week']}.lock"
            check_capture_path(lock)
            stream = stack.enter_context(lock.open("a"))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WeeklyCaptureError("weekly_writer_active") from None
        recovered = preflight(audit)
        checkpoints = assembly / "checkpoints"
        check_capture_path(checkpoints)
        checkpoints.mkdir(exist_ok=True)
        settings = DuckDBConnectionSettings(
            temp_directory=assembly / "promote_spill",
            memory_limit=budget.duckdb_memory_limit,
            threads=budget.duckdb_threads,
            max_temp_directory_size=budget.duckdb_max_temp,
        )
        with connect_configured_duckdb(settings) as connection:
            connection.execute("SET autoinstall_known_extensions=false")
            connection.execute("SET autoload_known_extensions=false")
            for index, item in enumerate(audit["files"]):
                check_weekly_cancel(cancel)
                target = Path(item["target"])
                if not recovered[item["week"]]:
                    candidate = Path(item["candidate"])
                    # Verify filesystem before creating any target directories.
                    parent = target.parent
                    while not parent.exists():
                        parent = parent.parent
                    check_capture_path(parent)
                    if candidate.stat().st_dev != parent.stat().st_dev:
                        raise WeeklyCaptureError("cross_device_promotion_forbidden")
                    if (
                        fingerprint(target) != item["baseline"]
                        or fingerprint(candidate) != item["sha256"]
                    ):
                        raise WeeklyCaptureError("promotion_fingerprint_changed")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    state = {
                        "audit_hash": audit["audit_hash"],
                        "sha256": item["sha256"],
                        "status": "promoting",
                    }
                    _atomic_json(checkpoint_path(audit, item), state)
                    fault_probe("before_replace", item["week"])
                    check_weekly_cancel(cancel)
                    os.replace(candidate, target)
                    _sync_directory(target.parent)
                    _sync_directory(candidate.parent)
                    fault_probe("after_replace", item["week"])
                readback(connection, audit, item)
                _atomic_json(
                    checkpoint_path(audit, item),
                    {
                        "audit_hash": audit["audit_hash"],
                        "sha256": item["sha256"],
                        "status": "verified",
                        "updated_at": datetime.now(UTC).isoformat(),
                    },
                )
                progress(
                    {
                        "stage": "verified",
                        "week": item["week"],
                        "completed_files": index + 1,
                        "total_files": len(audit["files"]),
                    }
                )
    return {
        "status": "verified",
        "files": len(audit["files"]),
        "partial_scope": audit["partial_scope"],
    }
