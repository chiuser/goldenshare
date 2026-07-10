"""CLI for bounded stock nine-turn runless event dry-runs and reporting."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stk_nineturn_events import (
    report_stk_nineturn_runless_events,
)
from orchestrator.defs.bootstrap.stk_nineturn_history import (
    load_stk_nineturn_prod_export_manifest,
)
from orchestrator.defs.resources import DuckDBResource


def _optional_keys(values: list[str] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    return tuple(values)


def main() -> None:
    parser = argparse.ArgumentParser(prog="stk_nineturn_events")
    parser.add_argument("command", choices=("dry-run", "report"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--lake-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--materialization-partitions", nargs="*")
    parser.add_argument("--check-partitions", nargs="*")
    parser.add_argument("--check-window-size", type=int, default=20)
    parser.add_argument("--history-audit-report")
    parser.add_argument("--confirm-write", action="store_true")
    args = parser.parse_args()

    if args.command == "report" and not args.confirm_write:
        parser.error("report requires --confirm-write")
    manifest = load_stk_nineturn_prod_export_manifest(
        manifest_path=args.manifest,
        run_id=args.run_id,
    )
    instance = dg.DagsterInstance.get()
    report = report_stk_nineturn_runless_events(
        instance=instance,
        manifest=manifest,
        lake_root=args.lake_root,
        duckdb_resource=DuckDBResource(),
        materialization_partition_keys=_optional_keys(args.materialization_partitions),
        check_partition_keys=_optional_keys(args.check_partitions),
        check_window_size=args.check_window_size,
        history_audit_report_path=args.history_audit_report,
        dry_run=args.command == "dry-run",
        confirm_write=args.confirm_write,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
