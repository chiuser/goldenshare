"""CLI for the M8 board event dry-run and explicitly confirmed apply."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.dc_board_events import (
    report_dc_board_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


DEFAULT_BASELINE_REPORT = Path(
    "/private/tmp/dc_board_m7_bootstrap_dry_run_20260715_v7.json"
)
DEFAULT_RAW_AUDIT_REPORT = Path("/private/tmp/dc_board_m7_raw_audit_20260715.json")
DEFAULT_SILVER_AUDIT_REPORT = Path(
    "/private/tmp/dc_board_m7_silver_audit_20260715.json"
)
DEFAULT_FINAL_REPORT = Path(
    "/private/tmp/dc_board_m7_final_reconciliation_20260715.json"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("dry-run", "apply"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
        subparser.add_argument("--baseline-report", type=Path, default=DEFAULT_BASELINE_REPORT)
        subparser.add_argument("--raw-audit-report", type=Path, default=DEFAULT_RAW_AUDIT_REPORT)
        subparser.add_argument(
            "--silver-audit-report",
            type=Path,
            default=DEFAULT_SILVER_AUDIT_REPORT,
        )
        subparser.add_argument("--final-report", type=Path, default=DEFAULT_FINAL_REPORT)
        subparser.add_argument("--output", type=Path, required=True)
        subparser.add_argument(
            "--confirm-event-write",
            action="store_true",
            help="Required by apply; omitted for dry-run.",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dry_run = args.command == "dry-run"
    if dry_run and args.confirm_event_write:
        raise SystemExit("--confirm-event-write is only valid for apply")
    instance = dg.DagsterInstance.get()
    report = report_dc_board_events(
        instance=instance,
        lake_root=args.lake_root,
        duckdb_resource=DuckDBResource(),
        baseline_report_path=args.baseline_report,
        raw_audit_report_path=args.raw_audit_report,
        silver_audit_report_path=args.silver_audit_report,
        final_reconciliation_report_path=args.final_report,
        dry_run=dry_run,
        confirm_event_write=args.confirm_event_write,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
