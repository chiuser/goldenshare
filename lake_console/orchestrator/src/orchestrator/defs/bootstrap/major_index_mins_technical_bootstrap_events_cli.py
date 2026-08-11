"""Controlled runless-event phases for minute technical history."""

from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.major_index_mins_technical_bootstrap_events import (
    post_audit_major_index_mins_technical_events,
    report_major_index_mins_technical_events,
    write_major_index_mins_technical_event_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dry-run", "sample", "apply", "post-audit"))
    parser.add_argument("--plan-report", type=Path, required=True)
    parser.add_argument("--promote-report", type=Path, required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--sample-date")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-event-write", action="store_true")
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.command in {"dry-run", "post-audit"} and args.confirm_event_write:
        parser.error(f"{args.command} does not accept --confirm-event-write")
    if args.command in {"sample", "apply"} and not args.confirm_event_write:
        parser.error(f"{args.command} requires --confirm-event-write")
    if args.command == "sample" and not args.sample_date:
        parser.error("sample requires --sample-date")
    if args.command != "sample" and args.sample_date:
        parser.error("--sample-date is only valid for sample")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    instance = dg.DagsterInstance.get()
    if args.command == "post-audit":
        report = post_audit_major_index_mins_technical_events(
            instance=instance,
            plan_report_path=args.plan_report,
            promote_report_path=args.promote_report,
            expected_plan_hash=args.expected_plan_hash,
        )
    else:
        report = report_major_index_mins_technical_events(
            instance=instance,
            plan_report_path=args.plan_report,
            promote_report_path=args.promote_report,
            expected_plan_hash=args.expected_plan_hash,
            dry_run=args.command == "dry-run",
            confirm_event_write=args.confirm_event_write,
            sample_only=args.command == "sample",
            sample_date=args.sample_date,
        )
    write_major_index_mins_technical_event_report(report, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
