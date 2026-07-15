"""Explicitly confirmed M7 Raw/Silver Bootstrap CLI.

Unlike the read-only planner CLI, this entrypoint has a separate command for
lake writes and requires ``--confirm-lake-write``.  It never writes Dagster
events or touches the Dagster instance.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.dc_board_bootstrap_apply import (
    DATASETS,
    DcBoardBootstrapApplyError,
    run_final_reconciliation,
    run_raw_bootstrap,
    run_raw_reconciliation,
    run_silver_bootstrap,
    run_silver_reconciliation,
    write_phase_report,
    write_reconciliation_report,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource, TushareResource


def _default_output(phase: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"/private/tmp/dc_board_m7_{phase}_{stamp}.json")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", required=True, type=Path)
    parser.add_argument("--baseline-report", required=True, type=Path)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument(
        "--dataset",
        action="append",
        choices=DATASETS,
        dest="datasets",
        help="limit the phase; repeat for multiple datasets",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=Path("/private/tmp"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Controlled M7 direct lake Bootstrap; no Dagster event path."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    raw = subparsers.add_parser("raw", help="write Raw partitions")
    _common(raw)
    raw.add_argument("--confirm-lake-write", action="store_true", required=True)

    raw_audit = subparsers.add_parser("raw-audit", help="audit Raw partitions without writing")
    _common(raw_audit)
    raw_audit.add_argument("--batch-report", required=True, type=Path)

    silver = subparsers.add_parser("silver", help="write Silver partitions")
    _common(silver)
    silver.add_argument("--raw-audit-report", required=True, type=Path)
    silver.add_argument("--confirm-lake-write", action="store_true", required=True)

    silver_audit = subparsers.add_parser("silver-audit", help="audit Silver partitions without writing")
    _common(silver_audit)
    silver_audit.add_argument("--batch-report", required=True, type=Path)

    final = subparsers.add_parser("final-audit", help="write a local final reconciliation report")
    final.add_argument("--lake-root", required=True, type=Path)
    final.add_argument("--raw-report", required=True, type=Path)
    final.add_argument("--silver-report", required=True, type=Path)
    final.add_argument("--output", type=Path, default=None)
    return parser


def _datasets(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(args.datasets) if args.datasets else DATASETS


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "raw":
            report = run_raw_bootstrap(
                lake_root=args.lake_root,
                duckdb_resource=DuckDBResource(),
                tushare=TushareResource(token=os.environ.get("TUSHARE_TOKEN", "")),
                prod_postgres=ProdPostgresResource(),
                baseline_report=args.baseline_report,
                report_dir=args.report_dir,
                datasets=_datasets(args),
                start_date=args.start_date,
                end_date=args.end_date,
                batch_size=args.batch_size,
            )
            output = args.output or _default_output("raw")
            write_phase_report(report, output)
            print(output)
            print(f"should_stop={report.should_stop}")
            return 0

        if args.command == "raw-audit":
            report = run_raw_reconciliation(
                lake_root=args.lake_root,
                duckdb_resource=DuckDBResource(),
                baseline_report=args.baseline_report,
                batch_report=args.batch_report,
                datasets=_datasets(args),
                start_date=args.start_date,
                end_date=args.end_date,
            )
            output = args.output or _default_output("raw_audit")
            write_reconciliation_report(report, output)
            print(output)
            print(f"should_stop={report.should_stop}")
            return 0 if not report.should_stop else 3

        if args.command == "silver":
            report = run_silver_bootstrap(
                lake_root=args.lake_root,
                duckdb_resource=DuckDBResource(),
                baseline_report=args.baseline_report,
                raw_audit_report=args.raw_audit_report,
                report_dir=args.report_dir,
                datasets=_datasets(args),
                start_date=args.start_date,
                end_date=args.end_date,
                batch_size=args.batch_size,
            )
            output = args.output or _default_output("silver")
            write_phase_report(report, output)
            print(output)
            print(f"should_stop={report.should_stop}")
            return 0

        if args.command == "silver-audit":
            report = run_silver_reconciliation(
                lake_root=args.lake_root,
                duckdb_resource=DuckDBResource(),
                baseline_report=args.baseline_report,
                batch_report=args.batch_report,
                datasets=_datasets(args),
                start_date=args.start_date,
                end_date=args.end_date,
            )
            output = args.output or _default_output("silver_audit")
            write_reconciliation_report(report, output)
            print(output)
            print(f"should_stop={report.should_stop}")
            return 0 if not report.should_stop else 3

        if args.command == "final-audit":
            output = args.output or _default_output("final_reconciliation")
            report = run_final_reconciliation(
                lake_root=args.lake_root,
                raw_report=args.raw_report,
                silver_report=args.silver_report,
                output_path=output,
            )
            print(output)
            print(f"should_stop={report['should_stop']}")
            return 0 if not report["should_stop"] else 3
    except (DcBoardBootstrapApplyError, RuntimeError, ValueError, OSError) as exc:
        print(f"dc board M7 phase stopped: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
