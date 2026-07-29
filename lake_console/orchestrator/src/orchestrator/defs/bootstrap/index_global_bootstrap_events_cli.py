"""Explicit partition registration and runless event backfill for index_global."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.index_global_bootstrap_events import (
    register_index_global_partitions,
    report_index_global_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


DEFAULT_RECONCILIATION_REPORT = Path(
    "/private/tmp/index_global_m7_final_reconciliation_20260728_233746.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dry-run", "register-partitions", "apply"))
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--reconciliation-report", type=Path, default=DEFAULT_RECONCILIATION_REPORT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-partition-write", action="store_true")
    parser.add_argument("--confirm-event-write", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "dry-run" and (args.confirm_partition_write or args.confirm_event_write):
        parser.error("dry-run does not accept write confirmations")
    if args.command == "register-partitions":
        if args.confirm_event_write:
            parser.error("register-partitions does not accept --confirm-event-write")
        if not args.confirm_partition_write:
            parser.error("register-partitions requires --confirm-partition-write")
    if args.command == "apply":
        if args.confirm_partition_write:
            parser.error("apply does not accept --confirm-partition-write")
        if not args.confirm_event_write:
            parser.error("apply requires --confirm-event-write")

    instance = dg.DagsterInstance.get()
    if args.command == "register-partitions":
        report = register_index_global_partitions(
            instance=instance,
            lake_root=args.lake_root,
            reconciliation_report_path=args.reconciliation_report,
            duckdb_resource=DuckDBResource(),
            confirm_partition_write=True,
        )
    else:
        report = report_index_global_events(
            instance=instance,
            lake_root=args.lake_root,
            reconciliation_report_path=args.reconciliation_report,
            duckdb_resource=DuckDBResource(),
            dry_run=args.command == "dry-run",
            confirm_event_write=args.confirm_event_write,
        )
    payload = report.to_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
