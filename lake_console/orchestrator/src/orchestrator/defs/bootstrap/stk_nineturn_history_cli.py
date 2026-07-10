"""CLI for stock nine-turn Raw bootstrap; writes require explicit confirmation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestrator.defs.bootstrap.stk_nineturn_history import (
    build_stk_nineturn_raw_history,
    build_stk_nineturn_silver_history,
    audit_stk_nineturn_formal_files,
    load_stk_nineturn_prod_export_manifest,
    plan_stk_nineturn_raw_history,
)
from orchestrator.defs.resources import DuckDBResource


def main() -> None:
    parser = argparse.ArgumentParser(prog="stk_nineturn_history")
    parser.add_argument("command", choices=("dry-run", "build-raw", "build-silver", "audit"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--lake-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-write", action="store_true")
    args = parser.parse_args()
    manifest = load_stk_nineturn_prod_export_manifest(
        manifest_path=args.manifest, run_id=args.run_id
    )
    plan = plan_stk_nineturn_raw_history(manifest=manifest, lake_root=args.lake_root)
    if args.command == "build-raw":
        if not args.confirm_write:
            parser.error("build-raw requires --confirm-write")
        plan = build_stk_nineturn_raw_history(
            manifest=manifest,
            lake_root=args.lake_root,
            duckdb=DuckDBResource(),
            confirm_write=True,
        )
    elif args.command == "build-silver":
        if not args.confirm_write:
            parser.error("build-silver requires --confirm-write")
        plan = build_stk_nineturn_silver_history(
            manifest=manifest,
            lake_root=args.lake_root,
            duckdb=DuckDBResource(),
            confirm_write=True,
        )
    elif args.command == "audit":
        report = audit_stk_nineturn_formal_files(
            manifest=manifest,
            lake_root=args.lake_root,
            duckdb=DuckDBResource(),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
