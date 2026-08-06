"""CLI for the read-only major-index minute P6 Bootstrap dry-run."""

import argparse
from datetime import datetime
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsBootstrapPlanError,
    run_dry_run,
    write_report,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    dry_run.add_argument("--end-date")
    dry_run.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "dry-run":
        raise AssertionError("unsupported command")
    output = args.output or Path(
        f"/private/tmp/major_index_mins_p6_dry_run_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    try:
        report = run_dry_run(
            lake_root=args.lake_root,
            end_date=args.end_date,
        )
    except (MajorIndexMinsBootstrapPlanError, RuntimeError) as error:
        print(f"major_index_mins dry-run failed: {error}", file=sys.stderr)
        return 2
    write_report(report, output)
    print(output)
    print(f"should_stop={report.should_stop}")
    return 0 if not report.should_stop else 3


if __name__ == "__main__":
    raise SystemExit(main())
