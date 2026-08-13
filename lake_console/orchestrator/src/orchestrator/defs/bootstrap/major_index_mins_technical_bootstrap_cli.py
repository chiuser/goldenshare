"""Controlled plan, candidate, and promotion phases for minute technical history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator.defs.bootstrap.major_index_mins_technical_history import (
    BOOTSTRAP_REPORT_ROOT,
    BOOTSTRAP_STAGING_ROOT,
    FORMAL_LAKE_ROOT,
    MajorIndexMinsTechnicalBootstrapError,
    audit_major_index_mins_technical_candidates,
    audit_major_index_mins_technical_formal,
    build_major_index_mins_technical_bootstrap_plan,
    build_major_index_mins_technical_candidates,
    build_major_index_mins_technical_performance_sample,
    promote_major_index_mins_technical_candidates,
)
from orchestrator.defs.resources import DuckDBResource


def _add_frozen_plan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan-report", type=Path, required=True)
    parser.add_argument("--expected-plan-hash", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--end-date", required=True)
    plan.add_argument("--source-lake-root", type=Path, default=FORMAL_LAKE_ROOT)
    plan.add_argument("--staging-root", type=Path, default=BOOTSTRAP_STAGING_ROOT)
    plan.add_argument("--report-root", type=Path, default=BOOTSTRAP_REPORT_ROOT)
    plan.add_argument(
        "--frequencies",
        nargs="+",
        type=int,
        default=[1, 5, 15, 30, 60, 90, 120],
    )

    candidates = subparsers.add_parser("build-candidates")
    _add_frozen_plan_args(candidates)
    candidates.add_argument("--confirm-staging-write", action="store_true")

    sample = subparsers.add_parser("sample-candidates")
    _add_frozen_plan_args(sample)
    sample.add_argument(
        "--sample-date-count", type=int, choices=(20, 60), required=True
    )
    sample.add_argument("--confirm-sample-staging-write", action="store_true")

    audit = subparsers.add_parser("audit-candidates")
    _add_frozen_plan_args(audit)
    audit.add_argument("--candidate-report", type=Path, required=True)

    promote = subparsers.add_parser("promote")
    _add_frozen_plan_args(promote)
    promote.add_argument("--candidate-report", type=Path, required=True)
    promote.add_argument("--candidate-audit-report", type=Path)
    promote.add_argument("--confirm-existing-replacement", action="store_true")
    promote.add_argument("--confirm-lake-write", action="store_true")

    formal_audit = subparsers.add_parser("audit-formal")
    _add_frozen_plan_args(formal_audit)
    formal_audit.add_argument("--candidate-report", type=Path, required=True)
    formal_audit.add_argument("--candidate-audit-report", type=Path, required=True)
    formal_audit.add_argument("--promote-report", type=Path, required=True)
    return parser


def _confirmation_error(args: argparse.Namespace) -> str | None:
    if args.command == "build-candidates" and not args.confirm_staging_write:
        return "build-candidates requires --confirm-staging-write"
    if args.command == "sample-candidates" and not args.confirm_sample_staging_write:
        return "sample-candidates requires --confirm-sample-staging-write"
    if args.command == "promote" and not args.confirm_lake_write:
        return "promote requires --confirm-lake-write"
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    confirmation_error = _confirmation_error(args)
    if confirmation_error:
        print(confirmation_error, file=sys.stderr)
        return 2
    try:
        if args.command == "plan":
            plan = build_major_index_mins_technical_bootstrap_plan(
                end_date=args.end_date,
                source_lake_root=args.source_lake_root,
                staging_root=args.staging_root,
                report_root=args.report_root,
                frequencies=args.frequencies,
            )
            print(plan.report_path)
            print(f"plan_hash={plan.plan_hash}")
            print(f"disk_budget_passed={plan.disk_budget_passed}")
            return 0 if plan.disk_budget_passed else 3
        if args.command == "build-candidates":
            report = build_major_index_mins_technical_candidates(
                plan_report_path=args.plan_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
                apply=True,
            )
        elif args.command == "sample-candidates":
            report = build_major_index_mins_technical_performance_sample(
                plan_report_path=args.plan_report,
                expected_plan_hash=args.expected_plan_hash,
                sample_date_count=args.sample_date_count,
                duckdb_resource=DuckDBResource(),
                apply=True,
            )
        elif args.command == "audit-candidates":
            report = audit_major_index_mins_technical_candidates(
                plan_report_path=args.plan_report,
                candidate_report_path=args.candidate_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
            )
        elif args.command == "promote":
            report = promote_major_index_mins_technical_candidates(
                plan_report_path=args.plan_report,
                candidate_report_path=args.candidate_report,
                candidate_audit_report_path=args.candidate_audit_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
                replace_existing=args.confirm_existing_replacement,
                apply=True,
            )
        elif args.command == "audit-formal":
            report = audit_major_index_mins_technical_formal(
                plan_report_path=args.plan_report,
                candidate_report_path=args.candidate_report,
                candidate_audit_report_path=args.candidate_audit_report,
                promote_report_path=args.promote_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
            )
        else:
            raise AssertionError(f"unsupported command: {args.command}")
        print(report)
        return 0
    except MajorIndexMinsTechnicalBootstrapError as error:
        print(f"minute technical Bootstrap stopped: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
