"""CLI for the stock-daily QFQ nine-turn no-price D4 event recovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_events import (
    apply_stock_daily_qfq_nineturn_no_price_events,
    load_stock_daily_qfq_nineturn_no_price_event_plan,
    plan_stock_daily_qfq_nineturn_no_price_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    resource = DuckDBResource()
    with dg.DagsterInstance.get() as instance:
        if args.command == "plan":
            plan = plan_stock_daily_qfq_nineturn_no_price_events(
                instance=instance,
                lake_plan_report_path=Path(args.lake_plan_report),
                formal_audit_report_path=Path(args.formal_audit_report),
                expected_lake_plan_hash=args.lake_plan_hash,
                expected_partition_count=args.expected_partition_count,
                expected_row_count=args.expected_row_count,
                lake_root=Path(args.lake_root),
                duckdb_resource=resource,
                output_dir=output_dir,
            )
            print(json.dumps(plan.to_summary_dict(), ensure_ascii=False, indent=2))
            return int(plan.should_stop)

        if not args.apply:
            parser.error("apply is disabled unless explicit --apply is supplied")
        plan = load_stock_daily_qfq_nineturn_no_price_event_plan(Path(args.plan_report))
        report = apply_stock_daily_qfq_nineturn_no_price_events(
            instance=instance,
            plan=plan,
            expected_plan_fingerprint=args.plan_fingerprint,
            confirm_apply=True,
            duckdb_resource=resource,
            output_dir=output_dir,
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--output-dir", default="/private/tmp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="build the read-only D4 event plan")
    plan.add_argument("--lake-plan-report", required=True)
    plan.add_argument("--formal-audit-report", required=True)
    plan.add_argument("--lake-plan-hash", required=True)
    plan.add_argument("--expected-partition-count", type=int, required=True)
    plan.add_argument("--expected-row-count", type=int, required=True)

    apply = subparsers.add_parser(
        "apply", help="append events from an unchanged reviewed D4 plan"
    )
    apply.add_argument("--plan-report", required=True)
    apply.add_argument("--plan-fingerprint", required=True)
    apply.add_argument("--apply", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
