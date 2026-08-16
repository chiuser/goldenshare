"""CLI for the reviewed stock-daily no-price D5 serving event recovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_serving_events import (
    PsqlRemoteStockDailyQfqNineTurnServingAuditReader,
    apply_stock_daily_qfq_nineturn_no_price_serving_events,
    capture_stock_daily_qfq_nineturn_serving_contract_snapshot,
    load_stock_daily_qfq_nineturn_no_price_serving_event_plan,
    plan_stock_daily_qfq_nineturn_no_price_serving_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    repo_root = Path(__file__).resolve().parents[6]
    reader = PsqlRemoteStockDailyQfqNineTurnServingAuditReader(
        repo_root=repo_root,
    )
    if args.command == "snapshot":
        report_path = capture_stock_daily_qfq_nineturn_serving_contract_snapshot(
            audit_reader=reader,
            output_dir=output_dir,
        )
        print(
            json.dumps(
                {"read_only": True, "report_path": str(report_path)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    with dg.DagsterInstance.get() as instance:
        if args.command == "plan":
            plan = plan_stock_daily_qfq_nineturn_no_price_serving_events(
                instance=instance,
                baseline_snapshot_report_path=Path(args.baseline_snapshot_report),
                d4_event_plan_report_path=Path(args.d4_event_plan_report),
                expected_d4_plan_fingerprint=args.d4_plan_fingerprint,
                deployed_revision=args.deployed_revision,
                audit_reader=reader,
                lake_root=Path(args.lake_root),
                duckdb_resource=DuckDBResource(),
                output_dir=output_dir,
            )
            print(json.dumps(plan.to_summary_dict(), ensure_ascii=False, indent=2))
            return int(plan.should_stop)

        if not args.apply:
            parser.error("apply is disabled unless explicit --apply is supplied")
        plan = load_stock_daily_qfq_nineturn_no_price_serving_event_plan(
            Path(args.plan_report)
        )
        report = apply_stock_daily_qfq_nineturn_no_price_serving_events(
            instance=instance,
            plan=plan,
            expected_plan_fingerprint=args.plan_fingerprint,
            confirm_apply=True,
            audit_reader=reader,
            duckdb_resource=DuckDBResource(),
            output_dir=output_dir,
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--output-dir", default="/private/tmp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "snapshot",
        help="capture the read-only pre-migration production contract",
    )

    plan = subparsers.add_parser(
        "plan",
        help="build the read-only post-migration D5 event plan",
    )
    plan.add_argument("--baseline-snapshot-report", required=True)
    plan.add_argument("--d4-event-plan-report", required=True)
    plan.add_argument("--d4-plan-fingerprint", required=True)
    plan.add_argument("--deployed-revision", required=True)

    apply = subparsers.add_parser(
        "apply",
        help="append events from an unchanged reviewed D5 plan",
    )
    apply.add_argument("--plan-report", required=True)
    apply.add_argument("--plan-fingerprint", required=True)
    apply.add_argument("--apply", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
