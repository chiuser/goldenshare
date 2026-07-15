"""CLI for the read-only dc board Bootstrap dry-run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.dc_board_bootstrap_plan import (
    DcBoardBootstrapPlanError,
    run_dry_run,
    write_report,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource, TushareResource


def _default_output() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"/private/tmp/dc_board_m7_bootstrap_dry_run_{stamp}.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only dc board Bootstrap planner; it has no apply path."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run", help="audit source and target state without writing")
    dry_run.add_argument("--lake-root", required=True, type=Path)
    dry_run.add_argument("--start-date", default=None)
    dry_run.add_argument("--end-date", default=None)
    dry_run.add_argument(
        "--dataset",
        action="append",
        choices=("dc_index", "dc_member", "dc_daily"),
        dest="datasets",
        help="limit the audit; repeat for multiple datasets",
    )
    dry_run.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "dry-run":
        raise AssertionError(f"unsupported command: {args.command}")
    output_path = args.output or _default_output()
    datasets = tuple(args.datasets) if args.datasets else ("dc_index", "dc_member", "dc_daily")
    try:
        report = run_dry_run(
            lake_root=args.lake_root,
            duckdb_resource=DuckDBResource(),
            tushare=TushareResource(token=os.environ.get("TUSHARE_TOKEN", "")),
            prod_postgres=ProdPostgresResource(),
            start_date=args.start_date,
            end_date=args.end_date,
            datasets=datasets,
        )
    except (DcBoardBootstrapPlanError, RuntimeError, ValueError) as exc:
        print(f"dc board Bootstrap dry-run stopped: {exc}", file=sys.stderr)
        return 2
    write_report(report, output_path)
    print(output_path)
    print(f"should_stop={report.should_stop}")
    if report.stop_reason_codes:
        print("stop_reason_codes=" + ",".join(report.stop_reason_codes))
    return 0 if not report.should_stop else 3


if __name__ == "__main__":
    raise SystemExit(main())
