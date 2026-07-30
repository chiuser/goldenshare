"""CLI for the explicit, bounded ``index_mins`` Bootstrap write."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.index_mins_bootstrap_apply import (
    IndexMinsBootstrapApplyError,
    run_bootstrap_apply,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply the approved index_mins Raw/Silver Bootstrap."
    )
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--fallback-report", type=Path, required=True)
    parser.add_argument("--end-date", required=True)
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
            prod_postgres=ProdPostgresResource(),
            source_report_path=args.source_report,
            fallback_report_path=args.fallback_report,
            output_dir=args.output_dir,
            end_date=args.end_date,
            batch_size=args.batch_size,
        )
    except (IndexMinsBootstrapApplyError, OSError, RuntimeError, ValueError) as error:
        print(f"index_mins Bootstrap stopped: {error}", file=sys.stderr)
        return 3
    print(report["report_paths"])
    print("should_stop=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
