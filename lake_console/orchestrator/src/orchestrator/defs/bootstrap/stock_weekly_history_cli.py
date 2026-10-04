"""Explicit direct-bootstrap phases. Dry-run never creates capture or Lake paths."""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
from dataclasses import asdict
from pathlib import Path
from threading import Event

from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    build_weekly_partition_candidates,
    validate_root,
    verified_empty_inventory_intervals,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    capture_file_hash,
    check_capture_path,
    verify_weekly_plan_evidence,
)
from orchestrator.defs.bootstrap.stock_weekly_history import capture_weekly_history
from orchestrator.defs.bootstrap.stock_weekly_promote import promote_weekly_candidates
from orchestrator.defs.prod_db.stock_weekly import PsqlWeeklyExporter
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyScope,
    ProdYearInventory,
    StockWeeklySource,
    WeeklyAvailability,
    WeeklyBudget,
    WeeklyCandidate,
    WeeklyHistoryScope,
)
from orchestrator.defs.stock_weekly_planner import (
    freeze_prod_weekly_plan,
    freeze_weekly_history_plan,
)
from orchestrator.defs.stock_weekly_source import WeeklySdkWorker


def read_inventory_csv(reference, columns):
    path = Path(reference["path"])
    check_capture_path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise WeeklyCaptureError("inventory_evidence_budget_exceeded")
    if capture_file_hash(path) != reference["sha256"]:
        raise WeeklyCaptureError("source_evidence_hash_mismatch")
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(columns):
            raise WeeklyCaptureError("inventory_columns_invalid")
        rows = []
        for row in reader:
            if len(rows) >= WeeklyBudget().max_candidate_keys:
                raise WeeklyCaptureError("candidate_key_budget_exceeded")
            if None in row or any(value is None for value in row.values()):
                raise WeeklyCaptureError("inventory_row_invalid")
            rows.append(row)
    return rows


def load_weekly_inventory(payload):
    rows = read_inventory_csv(
        payload["candidates"],
        (
            "ts_code",
            "week_key",
            "availability",
            "source_evidence_ref",
            "source_evidence_hash",
        ),
    )
    candidates = tuple(
        WeeklyCandidate(
            row["ts_code"],
            row["week_key"],
            row["availability"],
            row["source_evidence_ref"] or None,
            row["source_evidence_hash"] or None,
        )
        for row in rows
    )
    for reference, digest in {
        (candidate.source_evidence_ref, candidate.source_evidence_hash)
        for candidate in candidates
        if candidate.source_evidence_ref or candidate.source_evidence_hash
    }:
        if not reference or not digest:
            raise WeeklyCaptureError("inventory_source_reference_invalid")
        proof = Path(reference)
        check_capture_path(proof)
        if not proof.is_file() or capture_file_hash(proof) != digest:
            raise WeeklyCaptureError("source_evidence_hash_mismatch")
    expected = read_inventory_csv(payload["expected"], ("ts_code", "week_key"))
    keys = [(row["ts_code"], row["week_key"]) for row in expected]
    available = {
        (candidate.ts_code, candidate.week_key)
        for candidate in candidates
        if candidate.availability is WeeklyAvailability.AVAILABLE
        and candidate.week_key not in payload["excluded_week_keys"]
    }
    if len(keys) != len(set(keys)) or set(keys) != available:
        raise WeeklyCaptureError("expected_key_identity_mismatch")
    manifest = freeze_weekly_history_plan(
        WeeklyHistoryScope(
            payload["anchor_start"],
            payload["anchor_end"],
            candidates,
            payload["expected"]["path"],
            payload["expected"]["sha256"],
            tuple(payload["excluded_week_keys"]),
        )
    )
    verify_weekly_plan_evidence(manifest)
    return manifest


def load_inventory(path: Path):
    check_capture_path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise WeeklyCaptureError("inventory_evidence_budget_exceeded")
    payload = json.loads(path.read_text())
    if payload.get("version") != 1:
        raise WeeklyCaptureError("inventory_evidence_invalid")
    if payload.get("kind") == "weekly_history_inventory":
        return load_weekly_inventory(payload)
    if payload.get("kind") != "prod_weekly_inventory":
        raise WeeklyCaptureError("inventory_evidence_invalid")
    source = StockWeeklySource(payload["source"])
    if source is StockWeeklySource.ALTERNATE_WEEKLY:
        raise WeeklyCaptureError("alternate_has_no_prod_bootstrap")
    manifest = freeze_prod_weekly_plan(
        ProdWeeklyScope(
            source,
            tuple(
                ProdYearInventory(
                    item["year"], tuple(item["codes"]), item["source_rows"]
                )
                for item in payload["inventories"]
            ),
            str(path),
            capture_file_hash(path),
        )
    )
    verify_weekly_plan_evidence(manifest)
    verified_empty_inventory_intervals(manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("dry-run", "capture", "build", "promote"), default="dry-run"
    )
    parser.add_argument("--year", type=int)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    manifest = load_inventory(args.inventory)
    if args.mode != "dry-run" and args.plan is None:
        parser.error("mutating/preflight stages require explicit frozen --plan")
    if args.plan is not None:
        check_capture_path(args.plan)
        if args.plan.stat().st_size > 16 * 1024 * 1024:
            raise WeeklyCaptureError("plan_size_exceeded")
        if json.loads(args.plan.read_text()) != json.loads(
            json.dumps(asdict(manifest), default=str)
        ):
            raise WeeklyCaptureError("cli_frozen_plan_mismatch")
    validate_root(args.capture_root, staging=True)
    validate_root(args.target_root, staging=False)
    if (
        args.capture_root == args.target_root
        or args.capture_root.is_relative_to(args.target_root)
        or args.target_root.is_relative_to(args.capture_root)
    ):
        parser.error("capture/target roots overlap")
    if args.mode in ("capture", "build") and not args.apply:
        parser.error("capture/build require explicit --apply")
    if args.mode != "build" and args.year is not None:
        parser.error("--year is only valid for build")
    if args.mode == "dry-run" and args.apply:
        parser.error("dry-run cannot apply")
    if args.mode == "build" and args.year not in {
        unit.source_date_start.year
        if manifest.source is not StockWeeklySource.ALTERNATE_WEEKLY
        else int(unit.anchor_start[:4])
        for unit in manifest.units
    }:
        parser.error("--year must be in frozen anchor years")
    if args.mode == "promote" and args.audit is None:
        parser.error("promote requires --audit")
    if args.mode != "promote" and args.audit is not None:
        parser.error("--audit is only valid for promote")
    canceled = Event()
    old_handlers = {
        number: signal.signal(number, lambda *_: canceled.set())
        for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        if args.mode == "dry-run":
            result = {
                "status": "dry-run",
                "manifest": asdict(manifest),
                "capture_root": str(args.capture_root),
                "target_root": str(args.target_root),
                "formal_writes": 0,
                "instance_writes": 0,
            }
        elif args.mode == "capture":
            alternate = manifest.source is StockWeeklySource.ALTERNATE_WEEKLY
            token = os.environ.get("TUSHARE_TOKEN", "").strip() if alternate else ""
            if alternate and not token:
                raise WeeklyCaptureError("weekly_token_required")
            result = capture_weekly_history(
                manifest,
                capture_root=args.capture_root,
                prod_exporter=None if alternate else PsqlWeeklyExporter(),
                worker=WeeklySdkWorker(token) if alternate else None,
                cancel=canceled.is_set,
            )
        elif args.mode == "build":
            result = build_weekly_partition_candidates(
                manifest,
                year=args.year,
                capture_root=args.capture_root,
                target_root=args.target_root,
                cancel=canceled.is_set,
            )
        else:
            from orchestrator.defs.bootstrap.stock_weekly_promote import read_audit

            audit = read_audit(args.audit)
            if (
                audit["plan_hash"] != manifest.plan_hash
                or Path(audit["capture_root"]) != args.capture_root
                or Path(audit["target_root"]) != args.target_root
            ):
                raise WeeklyCaptureError("cli_audit_scope_mismatch")
            result = promote_weekly_candidates(
                args.audit, apply=args.apply, cancel=canceled.is_set
            )
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    finally:
        for number, handler in old_handlers.items():
            signal.signal(number, handler)


if __name__ == "__main__":
    raise SystemExit(main())
