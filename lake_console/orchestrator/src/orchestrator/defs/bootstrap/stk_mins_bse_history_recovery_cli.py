"""Explicit CLI for the staged BSE stock-minute history recovery."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_bse_history_recovery import (
    DEFAULT_RECOVERY_STAGING_ROOT,
    BseMinuteRecoveryError,
    audit_bse_raw_recovery_candidates,
    build_bse_raw_recovery_candidates,
    parse_scope_file,
    plan_bse_stk_mins_history_recovery,
    promote_bse_raw_recovery_candidates,
    stage_bse_stk_mins_source_pages,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource, TushareResource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an explicit stage of the bounded BSE minute-history recovery."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Build the R0A scope plan.")
    plan.add_argument("--scope-file", type=Path, required=True)
    plan.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    plan.add_argument(
        "--staging-root",
        type=Path,
        default=DEFAULT_RECOVERY_STAGING_ROOT,
    )
    plan.add_argument("--output", type=Path, required=True)

    source = subparsers.add_parser(
        "stage-source",
        help="Request and freeze the R0B source bundle under staging.",
    )
    source.add_argument("--plan", type=Path, required=True)
    source.add_argument("--output", type=Path, required=True)
    source.add_argument("--max-window-count", type=int)
    source.add_argument("--confirm-source-request", action="store_true")

    candidate = subparsers.add_parser(
        "build-raw-candidates",
        help="Build R1 Raw candidates from the frozen source bundle.",
    )
    candidate.add_argument("--plan", type=Path, required=True)
    candidate.add_argument("--bundle", type=Path, required=True)
    candidate.add_argument("--output", type=Path, required=True)
    candidate.add_argument("--confirm-candidate-write", action="store_true")

    audit = subparsers.add_parser(
        "audit-raw-candidates",
        help="Audit R1 Raw candidates without changing formal Raw.",
    )
    audit.add_argument("--plan", type=Path, required=True)
    audit.add_argument("--bundle", type=Path, required=True)
    audit.add_argument("--candidate-report", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)

    promote = subparsers.add_parser(
        "promote-raw",
        help="Promote audited R1 candidates into formal Raw.",
    )
    promote.add_argument("--plan", type=Path, required=True)
    promote.add_argument("--bundle", type=Path, required=True)
    promote.add_argument("--audit-report", type=Path, required=True)
    promote.add_argument("--checkpoint", type=Path, required=True)
    promote.add_argument("--output", type=Path, required=True)
    promote.add_argument("--confirm-raw-promote", action="store_true")
    return parser


def _print_result(payload: dict[str, object]) -> int:
    print(
        {
            "stage": payload.get("stage"),
            "should_stop": payload.get("should_stop"),
            "plan_hash": payload.get("plan_hash"),
            "bundle_hash": payload.get("bundle_hash"),
        }
    )
    return 3 if payload.get("should_stop") else 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    resource = DuckDBResource()
    try:
        if args.command == "plan":
            payload = plan_bse_stk_mins_history_recovery(
                lake_root=args.lake_root,
                staging_root=args.staging_root,
                scopes=parse_scope_file(args.scope_file),
                duckdb_resource=resource,
                output_path=args.output,
            )
        elif args.command == "stage-source":
            if not args.confirm_source_request:
                print(
                    "source request requires --confirm-source-request",
                    file=sys.stderr,
                )
                return 2
            payload = stage_bse_stk_mins_source_pages(
                plan_path=args.plan,
                tushare=TushareResource(token=os.environ.get("TUSHARE_TOKEN", "")),
                duckdb_resource=resource,
                output_path=args.output,
                max_window_count=args.max_window_count,
            )
        elif args.command == "build-raw-candidates":
            if not args.confirm_candidate_write:
                print(
                    "candidate write requires --confirm-candidate-write",
                    file=sys.stderr,
                )
                return 2
            payload = build_bse_raw_recovery_candidates(
                plan_path=args.plan,
                bundle_path=args.bundle,
                duckdb_resource=resource,
                output_path=args.output,
            )
        elif args.command == "audit-raw-candidates":
            payload = audit_bse_raw_recovery_candidates(
                plan_path=args.plan,
                bundle_path=args.bundle,
                candidate_report_path=args.candidate_report,
                duckdb_resource=resource,
                output_path=args.output,
            )
        elif args.command == "promote-raw":
            if not args.confirm_raw_promote:
                print(
                    "formal Raw promotion requires --confirm-raw-promote",
                    file=sys.stderr,
                )
                return 2
            payload = promote_bse_raw_recovery_candidates(
                plan_path=args.plan,
                bundle_path=args.bundle,
                audit_report_path=args.audit_report,
                confirm=True,
                checkpoint_path=args.checkpoint,
                output_path=args.output,
            )
        else:  # pragma: no cover - argparse owns the command domain.
            raise AssertionError(f"unsupported command: {args.command}")
    except (BseMinuteRecoveryError, OSError, RuntimeError, ValueError) as error:
        print(f"BSE minute-history recovery stopped: {error}", file=sys.stderr)
        return 3
    return _print_result(payload)


if __name__ == "__main__":
    raise SystemExit(main())
