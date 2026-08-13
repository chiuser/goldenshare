"""CLI for offline QFQ nine-turn history planning and controlled writes."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from orchestrator.defs.bootstrap.qfq_nineturn_history import (
    build_qfq_nineturn_history,
    load_qfq_nineturn_history_plan,
    load_qfq_nineturn_scoped_rebuild_plan,
    plan_qfq_nineturn_history,
    plan_qfq_nineturn_scoped_rebuild,
    rebuild_qfq_nineturn_scope,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import DuckDBResource


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    lake_root = Path(args.lake_root)
    output_dir = Path(args.output_dir)
    staging_root = Path(args.staging_root)
    resource = DuckDBResource()

    if args.command == "plan":
        plan = plan_qfq_nineturn_history(
            lake_root=lake_root,
            duckdb_resource=resource,
            output_dir=output_dir,
        )
        print(json.dumps(dict(plan.report), ensure_ascii=False, indent=2))
        return int(plan.should_stop)

    if args.command == "build":
        if not args.apply:
            parser.error("build is read-only unless explicit --apply is supplied")
        plan = load_qfq_nineturn_history_plan(Path(args.plan_report))
        report = build_qfq_nineturn_history(
            plan=plan,
            expected_plan_fingerprint=args.plan_fingerprint,
            duckdb_resource=resource,
            staging_root=staging_root,
            output_dir=output_dir,
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "plan-rebuild":
        stock_codes = tuple(
            line.strip()
            for line in Path(args.stock_codes_file)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
        plan = plan_qfq_nineturn_scoped_rebuild(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb_resource=resource,
            asset_family=args.asset_family,
            freqs=tuple(args.freqs or ()),
            stock_codes=stock_codes,
            start_date=args.start_date,
            end_date=args.end_date,
            batch_partition_limit=args.batch_partition_limit,
            output_dir=output_dir,
        )
        print(json.dumps(dict(plan.report), ensure_ascii=False, indent=2))
        return int(plan.should_stop)

    if not args.apply:
        parser.error("rebuild is read-only unless explicit --apply is supplied")
    plan = load_qfq_nineturn_scoped_rebuild_plan(Path(args.plan_report))
    report = rebuild_qfq_nineturn_scope(
        plan=plan,
        expected_plan_fingerprint=args.plan_fingerprint,
        duckdb_resource=resource,
        checkpoint_path=Path(args.checkpoint_path),
        mode=args.mode,
        sample_partition_keys=tuple(args.sample_partitions or ()),
        batch_count_limit=args.batch_count_limit,
        progress_callback=_print_progress,
        output_dir=output_dir,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--output-dir", default="/private/tmp")
    parser.add_argument("--staging-root", default=DEFAULT_LAKE_STAGING_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("plan", help="write a read-only history profiling plan")

    build = subparsers.add_parser("build", help="apply a fresh reviewed history plan")
    build.add_argument("--plan-report", required=True)
    build.add_argument("--plan-fingerprint", required=True)
    build.add_argument("--apply", action="store_true")

    scoped_plan = subparsers.add_parser(
        "plan-rebuild",
        help="freeze an approved code/date scope without writing Lake",
    )
    scoped_plan.add_argument(
        "--asset-family", choices=("daily", "minute"), required=True
    )
    scoped_plan.add_argument("--freqs", nargs="*", type=int)
    scoped_plan.add_argument("--stock-codes-file", required=True)
    scoped_plan.add_argument("--start-date", required=True)
    scoped_plan.add_argument("--end-date", required=True)
    scoped_plan.add_argument("--batch-partition-limit", type=int, default=20)

    rebuild = subparsers.add_parser(
        "rebuild",
        help="apply a fresh reviewed scoped rebuild plan",
    )
    rebuild.add_argument("--plan-report", required=True)
    rebuild.add_argument("--plan-fingerprint", required=True)
    rebuild.add_argument("--checkpoint-path", required=True)
    rebuild.add_argument("--mode", choices=("sample", "batch"), default="batch")
    rebuild.add_argument("--sample-partitions", nargs="*")
    rebuild.add_argument("--batch-count-limit", type=int, default=1)
    rebuild.add_argument("--apply", action="store_true")
    return parser


def _print_progress(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
