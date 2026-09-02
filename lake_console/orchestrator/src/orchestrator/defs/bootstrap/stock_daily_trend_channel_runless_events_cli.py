"""CLI for controlled stock daily trend-channel runless event backfill."""

from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stock_daily_trend_channel_runless_events import (
    final_audit_stock_daily_trend_channel_runless_events,
    report_stock_daily_trend_channel_runless_events,
    write_stock_daily_trend_channel_runless_event_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    instance = dg.DagsterInstance.get()
    kwargs = {
        "instance": instance,
        "plan_report_path": args.plan_report,
        "expected_plan_id": args.plan_id,
        "expected_plan_hash": args.plan_hash,
        "promote_report_path": args.promote_report,
        "expected_promote_hash": args.promote_hash,
        "final_audit_report_path": args.final_audit_report,
        "expected_final_audit_hash": args.final_audit_hash,
    }
    if args.command == "final-audit":
        report = final_audit_stock_daily_trend_channel_runless_events(**kwargs)
    else:
        report = report_stock_daily_trend_channel_runless_events(
            **kwargs,
            dry_run=args.command == "dry-run",
            confirm_event_write=args.confirm_event_write,
            sample_only=args.command == "sample",
            sample_trade_date=args.sample_trade_date,
            checkpoint_path=args.checkpoint,
        )
    write_stock_daily_trend_channel_runless_event_report(report, args.output)
    print(args.output)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("dry-run", "sample", "apply", "final-audit"),
    )
    parser.add_argument("--plan-report", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--promote-report", type=Path, required=True)
    parser.add_argument("--promote-hash", required=True)
    parser.add_argument("--final-audit-report", type=Path, required=True)
    parser.add_argument("--final-audit-hash", required=True)
    parser.add_argument("--sample-trade-date")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-event-write", action="store_true")
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.command in {"dry-run", "final-audit"} and args.confirm_event_write:
        parser.error(f"{args.command} does not accept --confirm-event-write")
    if args.command in {"sample", "apply"} and not args.confirm_event_write:
        parser.error(f"{args.command} requires --confirm-event-write")
    if args.command == "sample" and not args.sample_trade_date:
        parser.error("sample requires --sample-trade-date")
    if args.command != "sample" and args.sample_trade_date:
        parser.error("--sample-trade-date is only valid for sample")
    if args.command == "apply" and args.checkpoint is None:
        parser.error("apply requires --checkpoint")
    if args.command != "apply" and args.checkpoint is not None:
        parser.error("--checkpoint is only valid for apply")


if __name__ == "__main__":
    raise SystemExit(main())
