"""CLI for offline QFQ nine-turn history planning and controlled writes."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from orchestrator.defs.bootstrap.qfq_nineturn_history import (
    CANONICAL_REBUILD_FREQS,
    audit_qfq_nineturn_canonical_candidates,
    audit_qfq_nineturn_canonical_formal,
    build_qfq_nineturn_canonical_candidates,
    build_qfq_nineturn_history,
    load_qfq_nineturn_history_plan,
    load_qfq_nineturn_scoped_rebuild_plan,
    plan_qfq_nineturn_canonical_rebuild,
    plan_qfq_nineturn_history,
    plan_qfq_nineturn_scoped_rebuild,
    promote_qfq_nineturn_canonical_candidates,
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

    if args.command == "plan-canonical-rebuild":
        report = plan_qfq_nineturn_canonical_rebuild(
            lake_root=lake_root,
            staging_root=staging_root,
            report_root=output_dir,
            duckdb_resource=resource,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(report["should_stop"])

    if args.command == "build-canonical-candidates":
        if not args.confirm_staging_write:
            parser.error(
                "build-canonical-candidates requires --confirm-staging-write"
            )
        report = build_qfq_nineturn_canonical_candidates(
            plan_path=Path(args.plan_report),
            expected_plan_hash=args.plan_fingerprint,
            freq=args.freq,
            duckdb_resource=resource,
            confirm_build=True,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(report["should_stop"])

    if args.command == "audit-canonical-candidates":
        report = audit_qfq_nineturn_canonical_candidates(
            plan_path=Path(args.plan_report),
            expected_plan_hash=args.plan_fingerprint,
            freq=args.freq,
            duckdb_resource=resource,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(report["should_stop"])

    if args.command == "promote-canonical-rebuild":
        if not args.confirm_lake_write:
            parser.error("promote-canonical-rebuild requires --confirm-lake-write")
        report = promote_qfq_nineturn_canonical_candidates(
            plan_path=Path(args.plan_report),
            expected_plan_hash=args.plan_fingerprint,
            freq=args.freq,
            confirm_promote=True,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "audit-canonical-formal":
        report = audit_qfq_nineturn_canonical_formal(
            plan_path=Path(args.plan_report),
            expected_plan_hash=args.plan_fingerprint,
            freq=args.freq,
            duckdb_resource=resource,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(report["should_stop"])

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

    subparsers.add_parser(
        "plan-canonical-rebuild",
        help="freeze the four minute assets for candidate-first rebuild",
    )

    canonical_build = subparsers.add_parser(
        "build-canonical-candidates",
        help="build one complete minute frequency in staging",
    )
    _canonical_frozen_args(canonical_build)
    canonical_build.add_argument("--confirm-staging-write", action="store_true")

    canonical_audit = subparsers.add_parser(
        "audit-canonical-candidates",
        help="audit and hash one staged minute frequency",
    )
    _canonical_frozen_args(canonical_audit)

    canonical_promote = subparsers.add_parser(
        "promote-canonical-rebuild",
        help="atomically promote one audited minute frequency",
    )
    _canonical_frozen_args(canonical_promote)
    canonical_promote.add_argument("--confirm-lake-write", action="store_true")

    canonical_formal_audit = subparsers.add_parser(
        "audit-canonical-formal",
        help="audit one promoted minute frequency",
    )
    _canonical_frozen_args(canonical_formal_audit)

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


def _canonical_frozen_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan-report", required=True)
    parser.add_argument("--plan-fingerprint", required=True)
    parser.add_argument("--freq", type=int, choices=CANONICAL_REBUILD_FREQS, required=True)


def _print_progress(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
