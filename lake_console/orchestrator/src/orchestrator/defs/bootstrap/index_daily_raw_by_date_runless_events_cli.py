from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.index_daily_raw_by_date_runless_events import (
    RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT,
    audit_raw_index_daily_recent_window_events,
    report_raw_index_daily_recent_window_events,
    write_report_json,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Runless event helper for raw_index_daily recent-window bootstrap."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_events = subparsers.add_parser(
        "plan-events",
        help="Read lake files and Dagster state, then report the recent-window plan.",
    )
    _add_common_args(plan_events)

    report_sample = subparsers.add_parser(
        "report-sample-events",
        help="Report runless events for up to five explicit sample partitions.",
    )
    _add_common_args(report_sample)
    _add_partition_keys(report_sample, required=True)
    report_sample.add_argument("--apply", action="store_true")

    audit_sample = subparsers.add_parser(
        "audit-sample-events",
        help="Audit sample partitions after runless event reporting.",
    )
    _add_common_args(audit_sample)
    _add_partition_keys(audit_sample, required=True)
    _add_forbidden_partition_keys(audit_sample)

    report_recent = subparsers.add_parser(
        "report-recent-window-events",
        help="Report runless events for the latest recent-window partitions.",
    )
    _add_common_args(report_recent)
    report_recent.add_argument("--apply", action="store_true")

    audit_recent = subparsers.add_parser(
        "audit-recent-window-events",
        help="Audit recent-window runless event readiness.",
    )
    _add_common_args(audit_recent)
    _add_forbidden_partition_keys(audit_recent)

    args = parser.parse_args(argv)
    instance = dg.DagsterInstance.get()
    duckdb = DuckDBResource()
    lake_root = Path(args.lake_root)
    p3_report_path = Path(args.p3_final_audit_report)

    if args.command == "plan-events":
        report = report_raw_index_daily_recent_window_events(
            instance=instance,
            lake_root=lake_root,
            duckdb=duckdb,
            p3_final_audit_report_path=p3_report_path,
            window_limit=args.window_limit,
            dry_run=True,
        )
        payload = report.to_payload()
    elif args.command == "report-sample-events":
        _validate_sample_partition_keys(args.partition_key)
        report = report_raw_index_daily_recent_window_events(
            instance=instance,
            lake_root=lake_root,
            duckdb=duckdb,
            p3_final_audit_report_path=p3_report_path,
            partition_keys=args.partition_key,
            window_limit=args.window_limit,
            dry_run=not args.apply,
        )
        payload = report.to_payload()
    elif args.command == "audit-sample-events":
        _validate_sample_partition_keys(args.partition_key)
        audit = audit_raw_index_daily_recent_window_events(
            instance=instance,
            lake_root=lake_root,
            duckdb=duckdb,
            p3_final_audit_report_path=p3_report_path,
            partition_keys=args.partition_key,
            window_limit=args.window_limit,
            forbidden_partition_keys=args.forbidden_partition_key,
        )
        payload = audit.to_payload()
    elif args.command == "report-recent-window-events":
        report = report_raw_index_daily_recent_window_events(
            instance=instance,
            lake_root=lake_root,
            duckdb=duckdb,
            p3_final_audit_report_path=p3_report_path,
            window_limit=args.window_limit,
            dry_run=not args.apply,
        )
        payload = report.to_payload()
    elif args.command == "audit-recent-window-events":
        audit = audit_raw_index_daily_recent_window_events(
            instance=instance,
            lake_root=lake_root,
            duckdb=duckdb,
            p3_final_audit_report_path=p3_report_path,
            window_limit=args.window_limit,
            forbidden_partition_keys=args.forbidden_partition_key,
        )
        payload = audit.to_payload()
    else:
        parser.error(f"Unsupported command: {args.command}")

    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        write_report_json(payload, Path(args.output))
    print(text)
    return 2 if payload.get("should_stop") else 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument(
        "--p3-final-audit-report",
        required=True,
        help="Path to the P3 final audit JSON report. This command fails closed if it is missing or stale.",
    )
    parser.add_argument(
        "--window-limit",
        type=int,
        default=RAW_INDEX_DAILY_RECENT_WINDOW_LIMIT,
        help="Recent-window partition count. Must not exceed 20.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path. Prefer /private/tmp for formal reports.",
    )


def _add_partition_keys(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument(
        "--partition-key",
        action="append",
        required=required,
        help="Explicit ISO trade date partition key. Repeat for multiple dates.",
    )


def _add_forbidden_partition_keys(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--forbidden-partition-key",
        action="append",
        default=[],
        help="Partition that must have no raw_index_daily materialization/check events.",
    )


def _validate_sample_partition_keys(partition_keys: Sequence[str]) -> None:
    if len(set(partition_keys)) > 5:
        raise ValueError("sample runless event reporting allows at most five partitions.")


if __name__ == "__main__":
    raise SystemExit(main())

