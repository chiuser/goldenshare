"""CLI for the stock daily QFQ nine-turn six-column projection migration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_history import (
    audit_stock_daily_qfq_nineturn_no_price_candidates,
    audit_stock_daily_qfq_nineturn_no_price_formal,
    build_stock_daily_qfq_nineturn_no_price_candidates,
    load_stock_daily_qfq_nineturn_no_price_plan,
    plan_stock_daily_qfq_nineturn_no_price_history,
    promote_stock_daily_qfq_nineturn_no_price_candidates,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import DuckDBResource


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    resource = DuckDBResource()

    if args.command == "plan":
        plan = plan_stock_daily_qfq_nineturn_no_price_history(
            lake_root=Path(args.lake_root),
            staging_root=Path(args.staging_root),
            duckdb_resource=resource,
            writer_stopped=args.writer_stopped,
            output_dir=Path(args.output_dir),
        )
        print(json.dumps(dict(plan.report), ensure_ascii=False, indent=2))
        return int(plan.should_stop)

    plan = load_stock_daily_qfq_nineturn_no_price_plan(Path(args.plan_report))
    sample_partitions = tuple(getattr(args, "sample_partition", None) or ())
    if args.command == "build-candidates":
        if not args.apply:
            parser.error("build-candidates requires explicit --apply")
        report = build_stock_daily_qfq_nineturn_no_price_candidates(
            plan=plan,
            expected_plan_hash=args.plan_hash,
            duckdb_resource=resource,
            mode=args.mode,
            sample_partition_keys=sample_partitions,
            confirm_build=True,
        )
    elif args.command == "audit-candidates":
        report = audit_stock_daily_qfq_nineturn_no_price_candidates(
            plan=plan,
            expected_plan_hash=args.plan_hash,
            duckdb_resource=resource,
            mode=args.mode,
            sample_partition_keys=sample_partitions,
        )
    elif args.command == "promote":
        if not args.apply:
            parser.error("promote requires explicit --apply")
        report = promote_stock_daily_qfq_nineturn_no_price_candidates(
            plan=plan,
            expected_plan_hash=args.plan_hash,
            audit_report_path=Path(args.audit_report),
            writer_stopped=args.writer_stopped,
            reader_stopped=args.reader_stopped,
            confirm_promote=True,
        )
    else:
        report = audit_stock_daily_qfq_nineturn_no_price_formal(
            plan=plan,
            expected_plan_hash=args.plan_hash,
            candidate_audit_report_path=Path(args.audit_report),
            duckdb_resource=resource,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(report.get("should_stop", False)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--staging-root", default=DEFAULT_LAKE_STAGING_ROOT)
    parser.add_argument("--output-dir", default="/private/tmp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="write the read-only migration plan")
    plan.add_argument("--writer-stopped", action="store_true")

    build = subparsers.add_parser(
        "build-candidates",
        help="project reviewed partitions into the staging Lake",
    )
    _frozen_plan_args(build, include_mode=True)
    build.add_argument("--apply", action="store_true")

    audit = subparsers.add_parser(
        "audit-candidates",
        help="audit staged six-column candidates without formal writes",
    )
    _frozen_plan_args(audit, include_mode=True)

    promote = subparsers.add_parser(
        "promote",
        help="atomically replace the formal files after full audit",
    )
    _frozen_plan_args(promote, include_mode=False)
    promote.add_argument("--audit-report", required=True)
    promote.add_argument("--writer-stopped", action="store_true")
    promote.add_argument("--reader-stopped", action="store_true")
    promote.add_argument("--apply", action="store_true")

    formal_audit = subparsers.add_parser(
        "audit-formal",
        help="audit the promoted formal six-column files",
    )
    _frozen_plan_args(formal_audit, include_mode=False)
    formal_audit.add_argument("--audit-report", required=True)
    return parser


def _frozen_plan_args(
    parser: argparse.ArgumentParser,
    *,
    include_mode: bool,
) -> None:
    parser.add_argument("--plan-report", required=True)
    parser.add_argument("--plan-hash", required=True)
    if include_mode:
        parser.add_argument("--mode", choices=("sample", "full"), required=True)
        parser.add_argument("--sample-partition", action="append")


if __name__ == "__main__":
    raise SystemExit(main())
