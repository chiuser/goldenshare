"""Controlled P6 Bootstrap for canonical ordinary and major index Gold bars."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator.defs.bootstrap.cn_a_minute_gold_history import (
    CnAMinuteGoldHistoryError,
    audit_cn_a_minute_gold_history_candidates,
    audit_cn_a_minute_gold_history_formal,
    audit_major_index_gold_silver_equivalence,
    build_cn_a_minute_gold_history_candidates,
    build_cn_a_minute_gold_history_plan,
    promote_cn_a_minute_gold_history,
)
from orchestrator.defs.resources import DuckDBResource


def _frozen_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan-report", type=Path, required=True)
    parser.add_argument("--expected-plan-hash", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--dataset", choices=("index_mins", "major_index_mins"), required=True)

    build = subparsers.add_parser("build-candidates")
    _frozen_args(build)
    build.add_argument("--confirm-staging-write", action="store_true")

    audit = subparsers.add_parser("audit-candidates")
    _frozen_args(audit)
    audit.add_argument("--candidate-report", type=Path, required=True)

    promote = subparsers.add_parser("promote")
    _frozen_args(promote)
    promote.add_argument("--candidate-report", type=Path, required=True)
    promote.add_argument("--audit-report", type=Path, required=True)
    promote.add_argument("--confirm-lake-write", action="store_true")

    formal_audit = subparsers.add_parser("audit-formal")
    _frozen_args(formal_audit)
    formal_audit.add_argument("--candidate-report", type=Path, required=True)
    formal_audit.add_argument("--audit-report", type=Path, required=True)

    equivalence = subparsers.add_parser("audit-major-equivalence")
    _frozen_args(equivalence)
    equivalence.add_argument(
        "--frequencies", nargs="+", type=int, default=[1, 90, 120]
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            report = build_cn_a_minute_gold_history_plan(dataset=args.dataset)
        elif args.command == "build-candidates":
            if not args.confirm_staging_write:
                print("build-candidates requires --confirm-staging-write", file=sys.stderr)
                return 2
            report = build_cn_a_minute_gold_history_candidates(
                plan_report_path=args.plan_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
                apply=True,
            )
        elif args.command == "audit-candidates":
            report = audit_cn_a_minute_gold_history_candidates(
                plan_report_path=args.plan_report,
                candidate_report_path=args.candidate_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
            )
        elif args.command == "promote":
            if not args.confirm_lake_write:
                print("promote requires --confirm-lake-write", file=sys.stderr)
                return 2
            report = promote_cn_a_minute_gold_history(
                plan_report_path=args.plan_report,
                candidate_report_path=args.candidate_report,
                audit_report_path=args.audit_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
                apply=True,
            )
        elif args.command == "audit-formal":
            report = audit_cn_a_minute_gold_history_formal(
                plan_report_path=args.plan_report,
                candidate_report_path=args.candidate_report,
                audit_report_path=args.audit_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
            )
        elif args.command == "audit-major-equivalence":
            report = audit_major_index_gold_silver_equivalence(
                plan_report_path=args.plan_report,
                expected_plan_hash=args.expected_plan_hash,
                frequencies=args.frequencies,
                duckdb_resource=DuckDBResource(),
            )
        else:
            raise AssertionError(f"unsupported command: {args.command}")
        print(report)
        return 0
    except CnAMinuteGoldHistoryError as error:
        print(f"P6 Gold Bootstrap stopped: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
