"""Controlled P7 rebuild for canonical stock QFQ minute bars."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.bootstrap.stk_mins_qfq_canonical_history import (
    DEFAULT_REBUILD_STAGING_ROOT,
    DEFAULT_REPORT_ROOT,
    DERIVED_EQUIVALENCE_FREQS,
    DERIVED_EQUIVALENCE_SAMPLE_YEARS,
    StkMinsQfqCanonicalHistoryError,
    audit_stk_mins_qfq_canonical_candidates,
    audit_stk_mins_qfq_canonical_formal,
    audit_stk_mins_qfq_derived_equivalence_to_report,
    build_stk_mins_qfq_canonical_candidates,
    plan_stk_mins_qfq_canonical_history,
    promote_stk_mins_qfq_canonical_candidates,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def _frozen_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-hash", required=True)


def _frequency_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--freq", type=int, choices=(1, 5, 15, 30, 60), required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan")
    plan.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    plan.add_argument(
        "--staging-root", type=Path, default=DEFAULT_REBUILD_STAGING_ROOT
    )
    plan.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    plan.add_argument("--start-date", default=STK_MINS_QFQ_HISTORY_START_DATE)
    plan.add_argument("--end-date", required=True)

    build = commands.add_parser("build-candidates")
    _frozen_args(build)
    _frequency_arg(build)
    build.add_argument("--confirm-staging-write", action="store_true")

    candidate_audit = commands.add_parser("audit-candidates")
    _frozen_args(candidate_audit)
    _frequency_arg(candidate_audit)

    promote = commands.add_parser("promote")
    _frozen_args(promote)
    _frequency_arg(promote)
    promote.add_argument("--confirm-lake-write", action="store_true")

    formal_audit = commands.add_parser("audit-formal")
    _frozen_args(formal_audit)
    _frequency_arg(formal_audit)

    equivalence = commands.add_parser("audit-derived-equivalence")
    _frozen_args(equivalence)
    equivalence.add_argument(
        "--freq", type=int, choices=DERIVED_EQUIVALENCE_FREQS, required=True
    )
    equivalence.add_argument(
        "--year", type=int, choices=DERIVED_EQUIVALENCE_SAMPLE_YEARS, required=True
    )
    return parser


def _registered_partitions() -> tuple[str, ...]:
    return tuple(
        sorted(
            dg.DagsterInstance.get().get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "report_type",
        "plan_hash",
        "freq",
        "year",
        "phase_root",
        "candidate_lake_root",
        "manifest_path",
        "planned_target_file_count",
        "one_minute_affected_pair_count",
        "candidate_file_count",
        "formal_file_count",
        "promoted_file_count",
        "completed_batch_count",
        "elapsed_seconds",
        "ready",
        "should_stop",
        "stop_reason_code",
    )
    return {key: report[key] for key in keys if key in report}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            report = plan_stk_mins_qfq_canonical_history(
                registered_partition_keys=_registered_partitions(),
                lake_root=args.lake_root,
                staging_root=args.staging_root,
                report_root=args.report_root,
                start_date=args.start_date,
                end_date=args.end_date,
                duckdb_resource=DuckDBResource(),
            )
        elif args.command == "build-candidates":
            if not args.confirm_staging_write:
                print(
                    "build-candidates requires --confirm-staging-write",
                    file=sys.stderr,
                )
                return 2
            report = build_stk_mins_qfq_canonical_candidates(
                plan_path=args.plan,
                expected_plan_hash=args.plan_hash,
                freq=args.freq,
                duckdb_resource=DuckDBResource(),
                confirm_build=True,
            )
        elif args.command == "audit-candidates":
            report = audit_stk_mins_qfq_canonical_candidates(
                plan_path=args.plan,
                expected_plan_hash=args.plan_hash,
                freq=args.freq,
                duckdb_resource=DuckDBResource(),
            )
        elif args.command == "promote":
            if not args.confirm_lake_write:
                print("promote requires --confirm-lake-write", file=sys.stderr)
                return 2
            report = promote_stk_mins_qfq_canonical_candidates(
                plan_path=args.plan,
                expected_plan_hash=args.plan_hash,
                freq=args.freq,
                confirm_promote=True,
            )
        elif args.command == "audit-formal":
            report = audit_stk_mins_qfq_canonical_formal(
                plan_path=args.plan,
                expected_plan_hash=args.plan_hash,
                freq=args.freq,
                duckdb_resource=DuckDBResource(),
            )
        elif args.command == "audit-derived-equivalence":
            report = audit_stk_mins_qfq_derived_equivalence_to_report(
                plan_path=args.plan,
                expected_plan_hash=args.plan_hash,
                freq=args.freq,
                year=args.year,
                duckdb_resource=DuckDBResource(),
            )
        else:
            raise AssertionError(f"Unsupported command: {args.command}.")
        print(json.dumps(_summary(report), sort_keys=True))
        return 0 if report.get("should_stop") is not True else 4
    except StkMinsQfqCanonicalHistoryError as error:
        print(f"P7 canonical QFQ rebuild stopped: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
