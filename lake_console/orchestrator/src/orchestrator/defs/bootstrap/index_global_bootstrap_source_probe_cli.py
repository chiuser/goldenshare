"""CLI for the read-only full index_global Tushare source probe."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.index_global_bootstrap_source_probe import (
    run_source_probe,
    write_report,
)
from orchestrator.defs.resources import TushareResource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only full index_global Tushare source probe."
    )
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.output or (
        Path("/private/tmp")
        / f"index_global_p7b_source_probe_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    try:
        report = run_source_probe(
            tushare=TushareResource(token=os.environ.get("TUSHARE_TOKEN", "")),
            start_date=args.start_date,
            end_date=args.end_date,
        )
        write_report(report, output)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"index_global source probe stopped: {exc}", file=sys.stderr)
        return 2
    print(output)
    print(f"should_stop={report.should_stop}")
    print(f"attempted_phase_count={report.attempted_phase_count}")
    print(f"request_count={report.request_count}")
    return 0 if not report.should_stop else 3


if __name__ == "__main__":
    raise SystemExit(main())
