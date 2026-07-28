"""CLI for the approved, bounded index_global Bootstrap write."""

from __future__ import annotations

import argparse
from datetime import date
import os
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.index_global_bootstrap_apply import (
    IndexGlobalBootstrapApplyError,
    run_bootstrap_apply,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply the approved index_global Bootstrap.")
    parser.add_argument("--lake-root", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--output-dir", type=Path, default=Path("/private/tmp"))
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--confirm-lake-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_lake_write:
        print("formal lake write requires --confirm-lake-write", file=sys.stderr)
        return 2
    try:
        report = run_bootstrap_apply(
            lake_root=args.lake_root,
            duckdb_resource=DuckDBResource(),
            tushare=TushareResource(token=os.environ.get("TUSHARE_TOKEN", "")),
            source_report_path=args.source_report,
            output_dir=args.output_dir,
            start_date=args.start_date,
            end_date=args.end_date,
            batch_size=args.batch_size,
        )
    except (IndexGlobalBootstrapApplyError, OSError, RuntimeError, ValueError) as exc:
        print(f"index_global Bootstrap stopped: {exc}", file=sys.stderr)
        return 3
    print(report["report_paths"])
    print("should_stop=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
