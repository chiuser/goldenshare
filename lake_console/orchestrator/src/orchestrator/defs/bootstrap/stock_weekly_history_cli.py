"""Explicit direct-bootstrap phases. Dry-run never creates capture or Lake paths."""

from __future__ import annotations

import argparse
import json
import signal
from dataclasses import asdict
from pathlib import Path
from threading import Event

from orchestrator.defs.bootstrap.stock_weekly_adj_bootstrap import (
    AdjustedWeeklyBootstrapGuard,
    bootstrap_header_for_manifest,
    validate_bootstrap_inventory,
)
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
)
from orchestrator.defs.stock_weekly_planner import freeze_prod_weekly_plan


def load_inventory(path: Path):
    check_capture_path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise WeeklyCaptureError("inventory_evidence_budget_exceeded")
    payload = json.loads(path.read_text())
    if payload.get("version") != 1:
        raise WeeklyCaptureError("inventory_evidence_invalid")
    if payload.get("kind") != "prod_weekly_inventory":
        raise WeeklyCaptureError("inventory_evidence_invalid")
    source = StockWeeklySource(payload["source"])
    validate_bootstrap_inventory(payload)
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
    boundary = bootstrap_header_for_manifest(manifest)
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
            result = capture_weekly_history(
                manifest,
                capture_root=args.capture_root,
                prod_exporter=PsqlWeeklyExporter(),
                cancel=canceled.is_set,
                bootstrap_guard=AdjustedWeeklyBootstrapGuard(manifest)
                if boundary is not None
                else None,
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
