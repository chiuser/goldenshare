"""CLI for the read-only physical 000680.SH supplement audit."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_apply import (
    IndexDaily000680HistorySupplementApplyError,
)
from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_audit import (
    IndexDaily000680HistorySupplementAuditError,
    audit_formal_lake,
    write_report,
)
from orchestrator.defs.resources import DuckDBResource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only physical audit for the 000680.SH supplement."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--source-plan", type=Path, required=True)
    parser.add_argument("--expected-source-plan-hash", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.output or Path(
        "/private/tmp/index_daily_000680_history_supplement_audit_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    try:
        report = audit_formal_lake(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            source_plan_path=args.source_plan,
            expected_source_plan_hash=args.expected_source_plan_hash,
            expected_source_sha256=args.expected_source_sha256,
            duckdb_resource=DuckDBResource(),
        )
        write_report(report, output)
    except (
        IndexDaily000680HistorySupplementApplyError,
        IndexDaily000680HistorySupplementAuditError,
        OSError,
        RuntimeError,
    ) as error:
        print(f"000680.SH supplement audit stopped: {error}", file=sys.stderr)
        return 2
    print(output)
    print(f"passed={report.passed}")
    return 0 if report.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
