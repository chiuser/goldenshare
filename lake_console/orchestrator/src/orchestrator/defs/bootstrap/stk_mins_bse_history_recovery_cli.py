"""Explicit CLI for the staged BSE stock-minute history recovery."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stk_mins_bse_history_recovery import (
    DEFAULT_RECOVERY_STAGING_ROOT,
    BseMinuteRecoveryError,
    audit_bse_raw_recovery_candidates,
    audit_bse_silver_recovery_candidates,
    build_bse_raw_recovery_candidates,
    build_bse_silver_recovery_candidates,
    parse_scope_file,
    plan_bse_stk_mins_history_recovery,
    promote_bse_raw_recovery_candidates,
    promote_bse_silver_recovery_candidates,
    stage_bse_stk_mins_source_pages,
)
from orchestrator.defs.bootstrap.stk_mins_bse_qfq_recovery import (
    audit_bse_qfq_recovery_candidates,
    build_bse_qfq_recovery_candidates,
    plan_bse_qfq_recovery,
    promote_bse_qfq_recovery_candidates,
)
from orchestrator.defs.bootstrap.stk_mins_bse_recursive_recovery import (
    audit_bse_recursive_recovery_candidates,
    build_bse_recursive_recovery_candidates,
    plan_bse_recursive_recovery,
    promote_bse_recursive_recovery_candidates,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
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
    source.add_argument("--reuse-plan", type=Path)
    source.add_argument("--reuse-source-bundle", type=Path)
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

    silver_candidate = subparsers.add_parser(
        "build-silver-candidates",
        help="Build resumable R2 five-frequency Silver candidates.",
    )
    silver_candidate.add_argument("--plan", type=Path, required=True)
    silver_candidate.add_argument("--bundle", type=Path, required=True)
    silver_candidate.add_argument("--raw-promote-report", type=Path, required=True)
    silver_candidate.add_argument("--max-date-count", type=int)
    silver_candidate.add_argument("--output", type=Path, required=True)
    silver_candidate.add_argument(
        "--confirm-silver-candidate-write", action="store_true"
    )

    silver_audit = subparsers.add_parser(
        "audit-silver-candidates",
        help="Audit resumable R2 Silver candidates and freeze real changes.",
    )
    silver_audit.add_argument("--plan", type=Path, required=True)
    silver_audit.add_argument("--bundle", type=Path, required=True)
    silver_audit.add_argument("--raw-promote-report", type=Path, required=True)
    silver_audit.add_argument("--candidate-report", type=Path, required=True)
    silver_audit.add_argument("--max-candidate-count", type=int)
    silver_audit.add_argument("--output", type=Path, required=True)

    silver_promote = subparsers.add_parser(
        "promote-silver",
        help="Promote changed R2 Silver candidates and freeze the changed manifest.",
    )
    silver_promote.add_argument("--plan", type=Path, required=True)
    silver_promote.add_argument("--bundle", type=Path, required=True)
    silver_promote.add_argument("--raw-promote-report", type=Path, required=True)
    silver_promote.add_argument("--audit-report", type=Path, required=True)
    silver_promote.add_argument("--checkpoint", type=Path, required=True)
    silver_promote.add_argument("--changed-manifest", type=Path, required=True)
    silver_promote.add_argument("--output", type=Path, required=True)
    silver_promote.add_argument("--confirm-silver-promote", action="store_true")

    qfq_plan = subparsers.add_parser(
        "plan-qfq",
        help="Freeze the exact R3 QFQ scope from the R2 changed manifest.",
    )
    qfq_plan.add_argument("--changed-silver-manifest", type=Path, required=True)
    qfq_plan.add_argument("--output", type=Path, required=True)

    qfq_candidate = subparsers.add_parser(
        "build-qfq-candidates",
        help="Build resumable R3 QFQ candidates under formal staging.",
    )
    qfq_candidate.add_argument("--plan", type=Path, required=True)
    qfq_candidate.add_argument("--max-batch-count", type=int)
    qfq_candidate.add_argument("--output", type=Path, required=True)
    qfq_candidate.add_argument(
        "--confirm-qfq-candidate-write", action="store_true"
    )

    qfq_audit = subparsers.add_parser(
        "audit-qfq-candidates",
        help="Audit R3 QFQ candidates without changing formal Gold.",
    )
    qfq_audit.add_argument("--plan", type=Path, required=True)
    qfq_audit.add_argument("--candidate-report", type=Path, required=True)
    qfq_audit.add_argument("--max-candidate-count", type=int)
    qfq_audit.add_argument("--output", type=Path, required=True)

    qfq_promote = subparsers.add_parser(
        "promote-qfq",
        help="Promote audited R3 QFQ candidates into formal Gold.",
    )
    qfq_promote.add_argument("--plan", type=Path, required=True)
    qfq_promote.add_argument("--candidate-report", type=Path, required=True)
    qfq_promote.add_argument("--audit-report", type=Path, required=True)
    qfq_promote.add_argument("--checkpoint", type=Path, required=True)
    qfq_promote.add_argument("--changed-manifest", type=Path, required=True)
    qfq_promote.add_argument("--output", type=Path, required=True)
    qfq_promote.add_argument("--confirm-qfq-promote", action="store_true")

    recursive_plan = subparsers.add_parser(
        "plan-recursive",
        help="Freeze the exact recursive indicator scope from the R3 manifest.",
    )
    recursive_plan.add_argument("--changed-qfq-manifest", type=Path, required=True)
    recursive_plan.add_argument("--output", type=Path, required=True)

    recursive_candidate = subparsers.add_parser(
        "build-recursive-candidates",
        help="Build resumable recursive indicator candidates under staging.",
    )
    recursive_candidate.add_argument("--plan", type=Path, required=True)
    recursive_candidate.add_argument("--max-macd-batch-count", type=int)
    recursive_candidate.add_argument("--max-nineturn-date-count", type=int)
    recursive_candidate.add_argument("--output", type=Path, required=True)
    recursive_candidate.add_argument(
        "--confirm-recursive-candidate-write", action="store_true"
    )

    recursive_audit = subparsers.add_parser(
        "audit-recursive-candidates",
        help="Audit recursive candidates without changing formal Gold.",
    )
    recursive_audit.add_argument("--plan", type=Path, required=True)
    recursive_audit.add_argument("--candidate-report", type=Path, required=True)
    recursive_audit.add_argument("--max-candidate-count", type=int)
    recursive_audit.add_argument("--output", type=Path, required=True)

    recursive_promote = subparsers.add_parser(
        "promote-recursive",
        help="Promote audited recursive candidates into formal Gold.",
    )
    recursive_promote.add_argument("--plan", type=Path, required=True)
    recursive_promote.add_argument("--candidate-report", type=Path, required=True)
    recursive_promote.add_argument("--audit-report", type=Path, required=True)
    recursive_promote.add_argument("--checkpoint", type=Path, required=True)
    recursive_promote.add_argument("--changed-manifest", type=Path, required=True)
    recursive_promote.add_argument("--output", type=Path, required=True)
    recursive_promote.add_argument("--confirm-recursive-promote", action="store_true")
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
                reuse_plan_path=args.reuse_plan,
                reuse_source_bundle_path=args.reuse_source_bundle,
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
        elif args.command == "build-silver-candidates":
            if not args.confirm_silver_candidate_write:
                print(
                    "Silver candidate write requires --confirm-silver-candidate-write",
                    file=sys.stderr,
                )
                return 2
            payload = build_bse_silver_recovery_candidates(
                plan_path=args.plan,
                bundle_path=args.bundle,
                raw_promote_report_path=args.raw_promote_report,
                duckdb_resource=resource,
                max_date_count=args.max_date_count,
                output_path=args.output,
            )
        elif args.command == "audit-silver-candidates":
            payload = audit_bse_silver_recovery_candidates(
                plan_path=args.plan,
                bundle_path=args.bundle,
                raw_promote_report_path=args.raw_promote_report,
                candidate_report_path=args.candidate_report,
                duckdb_resource=resource,
                max_candidate_count=args.max_candidate_count,
                output_path=args.output,
            )
        elif args.command == "promote-silver":
            if not args.confirm_silver_promote:
                print(
                    "formal Silver promotion requires --confirm-silver-promote",
                    file=sys.stderr,
                )
                return 2
            payload = promote_bse_silver_recovery_candidates(
                plan_path=args.plan,
                bundle_path=args.bundle,
                raw_promote_report_path=args.raw_promote_report,
                audit_report_path=args.audit_report,
                confirm=True,
                checkpoint_path=args.checkpoint,
                changed_manifest_path=args.changed_manifest,
                duckdb_resource=resource,
                output_path=args.output,
            )
        elif args.command == "plan-qfq":
            payload = plan_bse_qfq_recovery(
                changed_silver_manifest_path=args.changed_silver_manifest,
                duckdb_resource=resource,
                output_path=args.output,
            )
        elif args.command == "build-qfq-candidates":
            if not args.confirm_qfq_candidate_write:
                print(
                    "QFQ candidate write requires --confirm-qfq-candidate-write",
                    file=sys.stderr,
                )
                return 2
            payload = build_bse_qfq_recovery_candidates(
                plan_path=args.plan,
                duckdb_resource=resource,
                output_path=args.output,
                confirm=True,
                max_batch_count=args.max_batch_count,
            )
        elif args.command == "audit-qfq-candidates":
            payload = audit_bse_qfq_recovery_candidates(
                plan_path=args.plan,
                candidate_report_path=args.candidate_report,
                duckdb_resource=resource,
                output_path=args.output,
                max_candidate_count=args.max_candidate_count,
            )
        elif args.command == "promote-qfq":
            if not args.confirm_qfq_promote:
                print(
                    "formal QFQ promotion requires --confirm-qfq-promote",
                    file=sys.stderr,
                )
                return 2
            payload = promote_bse_qfq_recovery_candidates(
                plan_path=args.plan,
                candidate_report_path=args.candidate_report,
                audit_report_path=args.audit_report,
                checkpoint_path=args.checkpoint,
                changed_manifest_path=args.changed_manifest,
                output_path=args.output,
                confirm=True,
            )
        elif args.command == "plan-recursive":
            with dg.DagsterInstance.get() as instance:
                registered = instance.get_dynamic_partitions(
                    cn_a_stock_mins_silver_trade_days.name
                )
            payload = plan_bse_recursive_recovery(
                changed_qfq_manifest_path=args.changed_qfq_manifest,
                registered_partition_keys=registered,
                output_path=args.output,
            )
        elif args.command == "build-recursive-candidates":
            if not args.confirm_recursive_candidate_write:
                print(
                    "recursive candidate write requires "
                    "--confirm-recursive-candidate-write",
                    file=sys.stderr,
                )
                return 2
            payload = build_bse_recursive_recovery_candidates(
                plan_path=args.plan,
                duckdb_resource=resource,
                output_path=args.output,
                confirm=True,
                max_macd_batch_count=args.max_macd_batch_count,
                max_nineturn_date_count=args.max_nineturn_date_count,
            )
        elif args.command == "audit-recursive-candidates":
            payload = audit_bse_recursive_recovery_candidates(
                plan_path=args.plan,
                candidate_report_path=args.candidate_report,
                duckdb_resource=resource,
                output_path=args.output,
                max_candidate_count=args.max_candidate_count,
            )
        elif args.command == "promote-recursive":
            if not args.confirm_recursive_promote:
                print(
                    "formal recursive promotion requires --confirm-recursive-promote",
                    file=sys.stderr,
                )
                return 2
            payload = promote_bse_recursive_recovery_candidates(
                plan_path=args.plan,
                candidate_report_path=args.candidate_report,
                audit_report_path=args.audit_report,
                checkpoint_path=args.checkpoint,
                changed_manifest_path=args.changed_manifest,
                output_path=args.output,
                confirm=True,
            )
        else:  # pragma: no cover - argparse owns the command domain.
            raise AssertionError(f"unsupported command: {args.command}")
    except (BseMinuteRecoveryError, OSError, RuntimeError, ValueError) as error:
        print(f"BSE minute-history recovery stopped: {error}", file=sys.stderr)
        return 3
    return _print_result(payload)


if __name__ == "__main__":
    raise SystemExit(main())
