"""CLI for reviewed stock daily QFQ nine-turn serving history publication."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history import (
    load_stock_daily_qfq_nineturn_serving_history_plan,
    plan_stock_daily_qfq_nineturn_serving_history,
    publish_stock_daily_qfq_nineturn_serving_history,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import DuckDBResource, ProdPostgresWriteResource


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.command == "plan":
        plan = plan_stock_daily_qfq_nineturn_serving_history(
            lake_root=Path(args.lake_root),
            staging_root=Path(args.staging_root),
            duckdb_resource=DuckDBResource(),
            start_date=args.start_date,
            end_date=args.end_date,
            batch_partition_limit=args.batch_partition_limit,
            output_dir=Path(args.output_dir),
        )
        print(json.dumps(plan.to_summary_dict(), ensure_ascii=False, indent=2))
        return int(plan.should_stop)
    if not args.apply:
        parser.error("publish requires explicit --apply after plan review")
    plan = load_stock_daily_qfq_nineturn_serving_history_plan(Path(args.plan_report))
    report = publish_stock_daily_qfq_nineturn_serving_history(
        plan=plan,
        expected_plan_fingerprint=args.plan_fingerprint,
        duckdb_resource=DuckDBResource(),
        prod_postgres_write=ProdPostgresWriteResource(),
        checkpoint_path=Path(args.checkpoint_path),
        mode=args.mode,
        sample_partition_keys=tuple(args.sample_partitions or ()),
        batch_count_limit=args.batch_count_limit,
        progress_callback=_print_progress,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--staging-root", default=DEFAULT_LAKE_STAGING_ROOT)
    parser.add_argument("--output-dir", default="/private/tmp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="write a read-only publication plan")
    plan.add_argument("--start-date")
    plan.add_argument("--end-date")
    plan.add_argument("--batch-partition-limit", type=int, default=20)

    publish = subparsers.add_parser(
        "publish",
        help="publish one reviewed sample or one bounded resumable batch",
    )
    publish.add_argument("--plan-report", required=True)
    publish.add_argument("--plan-fingerprint", required=True)
    publish.add_argument("--checkpoint-path", required=True)
    publish.add_argument("--mode", choices=("sample", "batch"), default="batch")
    publish.add_argument("--sample-partitions", nargs="*")
    publish.add_argument("--batch-count-limit", type=int, default=1)
    publish.add_argument("--apply", action="store_true")
    return parser


def _print_progress(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
