"""Controlled partition and runless-event phases for ``idx_factor_pro``."""

from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_events import (
    post_audit_idx_factor_pro_events,
    register_idx_factor_pro_partitions,
    report_idx_factor_pro_events,
    write_idx_factor_pro_event_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("dry-run", "register-partitions", "sample", "apply", "post-audit"),
    )
    parser.add_argument("--plan-report", type=Path, required=True)
    parser.add_argument("--promote-report", type=Path, required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--sample-date")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-partition-write", action="store_true")
    parser.add_argument("--confirm-event-write", action="store_true")
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.command in {"dry-run", "post-audit"} and (
        args.confirm_partition_write or args.confirm_event_write
    ):
        parser.error(f"{args.command} does not accept write confirmations")
    if args.command == "register-partitions":
        if not args.confirm_partition_write:
            parser.error("register-partitions requires --confirm-partition-write")
        if args.confirm_event_write or args.sample_date:
            parser.error("register-partitions only accepts partition confirmation")
    if args.command in {"sample", "apply"}:
        if not args.confirm_event_write:
            parser.error(f"{args.command} requires --confirm-event-write")
        if args.confirm_partition_write:
            parser.error(f"{args.command} does not accept partition confirmation")
    if args.command == "sample" and not args.sample_date:
        parser.error("sample requires --sample-date")
    if args.command != "sample" and args.sample_date:
        parser.error("--sample-date is only valid for sample")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    instance = dg.DagsterInstance.get()
    if args.command == "register-partitions":
        report = register_idx_factor_pro_partitions(
            instance=instance,
            plan_report_path=args.plan_report,
            promote_report_path=args.promote_report,
            expected_plan_hash=args.expected_plan_hash,
            apply=True,
            confirm_partition_write=True,
        )
    elif args.command == "post-audit":
        report = post_audit_idx_factor_pro_events(
            instance=instance,
            plan_report_path=args.plan_report,
            promote_report_path=args.promote_report,
            expected_plan_hash=args.expected_plan_hash,
        )
    else:
        report = report_idx_factor_pro_events(
            instance=instance,
            plan_report_path=args.plan_report,
            promote_report_path=args.promote_report,
            expected_plan_hash=args.expected_plan_hash,
            dry_run=args.command == "dry-run",
            confirm_event_write=args.confirm_event_write,
            sample_only=args.command == "sample",
            sample_date=args.sample_date,
        )
    write_idx_factor_pro_event_report(report, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
