"""CLI for the reviewed single-day stock trend-channel event reconciliation."""

from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stock_daily_trend_channel_event_reconciliation import (
    apply_stock_daily_trend_channel_check_reconciliation,
    apply_stock_daily_trend_channel_materialization_reconciliation,
    audit_stock_daily_trend_channel_event_reconciliation,
    audit_stock_daily_trend_channel_materialization_reconciliation,
    build_stock_daily_trend_channel_event_reconciliation_plan,
    load_stock_daily_trend_channel_event_reconciliation_plan,
    write_stock_daily_trend_channel_event_reconciliation_report,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    lake_root = LakeRootResource()
    if lake_root.root().resolve() != Path(DEFAULT_LAKE_ROOT).resolve():
        parser.error("production reconciliation must use the formal Lake root")
    duckdb = DuckDBResource()
    with dg.DagsterInstance.get() as instance:
        if args.stage == "plan":
            report = build_stock_daily_trend_channel_event_reconciliation_plan(
                instance=instance,
                partition_date=args.partition_date,
                incident_run_id=args.incident_run_id,
                current_file_producer_run_id=args.current_file_producer_run_id,
                lake_root=lake_root,
                duckdb=duckdb,
            )
        else:
            plan = load_stock_daily_trend_channel_event_reconciliation_plan(
                args.plan_report,
                expected_plan_id=args.plan_id,
                expected_plan_hash=args.plan_hash,
            )
            if args.stage == "apply-materializations":
                report = apply_stock_daily_trend_channel_materialization_reconciliation(
                    instance=instance,
                    plan=plan,
                    lake_root=lake_root,
                    duckdb=duckdb,
                    confirm_event_write=args.confirm_event_write,
                )
            elif args.stage == "audit-materializations":
                report = audit_stock_daily_trend_channel_materialization_reconciliation(
                    instance=instance,
                    plan=plan,
                    lake_root=lake_root,
                    duckdb=duckdb,
                )
            elif args.stage == "apply-checks":
                report = apply_stock_daily_trend_channel_check_reconciliation(
                    instance=instance,
                    plan=plan,
                    lake_root=lake_root,
                    duckdb=duckdb,
                    confirm_event_write=args.confirm_event_write,
                )
            else:
                report = audit_stock_daily_trend_channel_event_reconciliation(
                    instance=instance,
                    plan=plan,
                    lake_root=lake_root,
                    duckdb=duckdb,
                )
    output = write_stock_daily_trend_channel_event_reconciliation_report(
        report,
        args.output,
    )
    print(output)
    if args.stage == "plan":
        return int(report.should_stop)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="stage", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--partition-date", required=True)
    plan.add_argument("--incident-run-id", required=True)
    plan.add_argument("--current-file-producer-run-id", required=True)
    plan.add_argument("--output", type=Path, required=True)

    for stage_name in (
        "apply-materializations",
        "audit-materializations",
        "apply-checks",
        "final-audit",
    ):
        stage = subparsers.add_parser(stage_name)
        stage.add_argument("--plan-report", type=Path, required=True)
        stage.add_argument("--plan-id", required=True)
        stage.add_argument("--plan-hash", required=True)
        stage.add_argument("--output", type=Path, required=True)
        if stage_name in {"apply-materializations", "apply-checks"}:
            stage.add_argument(
                "--confirm-event-write",
                action="store_true",
                required=True,
            )
    return parser


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
