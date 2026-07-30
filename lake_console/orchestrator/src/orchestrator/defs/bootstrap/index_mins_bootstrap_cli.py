"""CLI for the read-only index_mins P6 Bootstrap dry-run."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.index_mins_bootstrap_plan import (
    IndexMinsBootstrapPlanError,
    run_dry_run,
    write_report,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import ProdPostgresResource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only index_mins Bootstrap planner; no apply path exists."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    dry_run.add_argument("--end-date")
    dry_run.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "dry-run":
        raise AssertionError(f"unsupported command: {args.command}")
    output = args.output or (
        Path("/private/tmp")
        / f"index_mins_bootstrap_dry_run_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    try:
        report = run_dry_run(
            lake_root=args.lake_root,
            prod_postgres=ProdPostgresResource(),
            end_date=args.end_date,
        )
        write_report(report, output)
    except (IndexMinsBootstrapPlanError, OSError, RuntimeError, ValueError) as exc:
        print(f"index_mins bootstrap dry-run stopped: {exc}", file=sys.stderr)
        return 2
    print(output)
    print(f"should_stop={report.should_stop}")
    return 0 if not report.should_stop else 3


if __name__ == "__main__":
    raise SystemExit(main())
