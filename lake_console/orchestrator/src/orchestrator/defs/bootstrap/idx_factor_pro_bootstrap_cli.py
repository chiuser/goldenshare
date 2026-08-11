"""Controlled phase runner for the ``idx_factor_pro`` historical Bootstrap."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_plan import (
    BOOTSTRAP_REPORT_ROOT,
    BOOTSTRAP_STAGING_ROOT,
    FORMAL_LAKE_ROOT,
    IdxFactorProBootstrapPlanError,
    build_idx_factor_pro_bootstrap_plan,
)
from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_promote import (
    IdxFactorProBootstrapPromoteError,
    promote_idx_factor_pro_candidates,
)
from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_stage import (
    IdxFactorProBootstrapStageError,
    build_idx_factor_pro_candidates,
    stage_idx_factor_pro_source,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource


def _add_frozen_plan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan-report", type=Path, required=True)
    parser.add_argument("--expected-plan-hash", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--end-date", required=True)
    plan.add_argument("--lake-root", type=Path, default=FORMAL_LAKE_ROOT)
    plan.add_argument("--staging-root", type=Path, default=BOOTSTRAP_STAGING_ROOT)
    plan.add_argument("--report-root", type=Path, default=BOOTSTRAP_REPORT_ROOT)

    stage = subparsers.add_parser("stage-source")
    _add_frozen_plan_args(stage)
    stage.add_argument("--ts-code", action="append")
    stage.add_argument("--confirm-source-request", action="store_true")

    candidates = subparsers.add_parser("build-candidates")
    _add_frozen_plan_args(candidates)
    candidates.add_argument("--source-report", type=Path, required=True)
    candidates.add_argument("--confirm-staging-write", action="store_true")

    promote = subparsers.add_parser("promote")
    _add_frozen_plan_args(promote)
    promote.add_argument("--candidate-report", type=Path, required=True)
    promote.add_argument("--confirm-lake-write", action="store_true")
    return parser


def _confirmation_error(args: argparse.Namespace) -> str | None:
    if args.command == "stage-source" and not args.confirm_source_request:
        return "stage-source requires --confirm-source-request"
    if args.command == "build-candidates" and not args.confirm_staging_write:
        return "build-candidates requires --confirm-staging-write"
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
            plan = build_idx_factor_pro_bootstrap_plan(
                end_date=args.end_date,
                lake_root=args.lake_root,
                staging_root=args.staging_root,
                report_root=args.report_root,
            )
            print(plan.report_path)
            print(f"plan_hash={plan.plan_hash}")
            print(f"disk_budget_passed={plan.disk_budget.passed}")
            return 0 if plan.disk_budget.passed else 3
        if args.command == "stage-source":
            report = stage_idx_factor_pro_source(
                plan_report_path=args.plan_report,
                expected_plan_hash=args.expected_plan_hash,
                tushare=TushareResource(token=os.environ.get("TUSHARE_TOKEN", "")),
                duckdb_resource=DuckDBResource(),
                apply=True,
                selected_codes=args.ts_code,
            )
        elif args.command == "build-candidates":
            report = build_idx_factor_pro_candidates(
                plan_report_path=args.plan_report,
                source_report_path=args.source_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
                apply=True,
            )
        elif args.command == "promote":
            report = promote_idx_factor_pro_candidates(
                plan_report_path=args.plan_report,
                candidate_report_path=args.candidate_report,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=DuckDBResource(),
                apply=True,
            )
        else:
            raise AssertionError(f"unsupported command: {args.command}")
        print(report)
        return 0
    except (
        IdxFactorProBootstrapPlanError,
        IdxFactorProBootstrapPromoteError,
        IdxFactorProBootstrapStageError,
    ) as error:
        print(f"idx_factor_pro Bootstrap stopped: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
