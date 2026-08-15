"""CLI for QFQ nine-turn runless materialization and recent check events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.qfq_nineturn_events import (
    load_qfq_nineturn_event_plan,
    plan_qfq_nineturn_runless_events,
    report_qfq_nineturn_runless_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    lake_root = Path(args.lake_root)
    output_dir = Path(args.output_dir)
    resource = DuckDBResource()
    with dg.DagsterInstance.get() as instance:
        if args.command == "plan":
            plan = plan_qfq_nineturn_runless_events(
                instance=instance,
                history_plan_path=Path(args.history_plan),
                history_audit_report_path=Path(args.history_audit),
                lake_root=lake_root,
                duckdb_resource=resource,
                output_dir=output_dir,
                force_materialization_refresh=args.force_materialization_refresh,
                event_revision=args.event_revision,
                asset_keys=tuple(args.asset_key) if args.asset_key else None,
            )
            print(json.dumps(dict(plan.report), ensure_ascii=False, indent=2))
            return int(plan.should_stop)

        if not args.apply:
            parser.error("report is read-only unless explicit --apply is supplied")
        plan = load_qfq_nineturn_event_plan(Path(args.plan_report))
        report = report_qfq_nineturn_runless_events(
            instance=instance,
            plan=plan,
            expected_plan_fingerprint=args.plan_fingerprint,
            lake_root=lake_root,
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

    plan = subparsers.add_parser("plan", help="build a read-only runless event plan")
    plan.add_argument("--history-plan", required=True)
    plan.add_argument("--history-audit", required=True)
    plan.add_argument("--force-materialization-refresh", action="store_true")
    plan.add_argument("--event-revision")
    plan.add_argument(
        "--asset-key",
        action="append",
        choices=(
            "gold_stock_daily_qfq_nineturn",
            "gold_stk_mins_qfq_nineturn_30m",
            "gold_stk_mins_qfq_nineturn_60m",
            "gold_stk_mins_qfq_nineturn_90m",
            "gold_stk_mins_qfq_nineturn_120m",
        ),
        help="Repeat to limit the reviewed event plan to explicit assets.",
    )

    report = subparsers.add_parser("report", help="append events from a fresh plan")
    report.add_argument("--plan-report", required=True)
    report.add_argument("--plan-fingerprint", required=True)
    report.add_argument("--apply", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
