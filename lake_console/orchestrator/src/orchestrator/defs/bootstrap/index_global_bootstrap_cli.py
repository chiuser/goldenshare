"""CLI for the read-only P7 index_global Bootstrap dry-run."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.index_global_bootstrap_plan import (
    IndexGlobalBootstrapPlanError,
    run_dry_run,
    write_report,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only index_global Bootstrap planner; no apply path exists."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    dry_run.add_argument("--start-date")
    dry_run.add_argument("--end-date")
    dry_run.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "dry-run":
        raise AssertionError(f"unsupported command: {args.command}")
    output = args.output or (
        Path("/private/tmp")
        / f"index_global_bootstrap_dry_run_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    try:
        report = run_dry_run(
            lake_root=args.lake_root,
            duckdb_resource=DuckDBResource(),
            start_date=args.start_date,
            end_date=args.end_date,
        )
        write_report(report, output)
    except (IndexGlobalBootstrapPlanError, OSError, RuntimeError) as exc:
        print(f"index_global bootstrap dry-run stopped: {exc}", file=sys.stderr)
        return 2
    print(output)
    print(f"should_stop={report.should_stop}")
    return 0 if not report.should_stop else 3


if __name__ == "__main__":
    raise SystemExit(main())
