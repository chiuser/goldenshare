"""Runless event dry-run, sample, and explicit apply for Gold dc_daily technical."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.dc_daily_technical_events import (
    report_gold_dc_daily_technical_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


DEFAULT_AUDIT_REPORT = Path(
    "/private/tmp/dc_daily_technical_p8_full_bootstrap_audit_20260715_180211.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dry-run", "sample", "apply"))
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--audit-report", type=Path, default=DEFAULT_AUDIT_REPORT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-event-write", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "dry-run" and args.confirm_event_write:
        parser.error("--confirm-event-write is only valid for sample/apply")
    if args.command in {"sample", "apply"} and not args.confirm_event_write:
        parser.error(f"{args.command} requires --confirm-event-write")

    report = report_gold_dc_daily_technical_events(
        instance=dg.DagsterInstance.get(),
        lake_root=args.lake_root,
        audit_report_path=args.audit_report,
        duckdb_resource=DuckDBResource(),
        mode="sample" if args.command == "sample" else "full",
        dry_run=args.command == "dry-run",
        confirm_event_write=args.confirm_event_write,
    )
    payload = report.to_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
