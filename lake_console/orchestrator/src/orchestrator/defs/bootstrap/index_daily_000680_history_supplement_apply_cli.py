"""CLI for explicit 000680.SH source staging and bounded Lake writes."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_apply import (
    IndexDaily000680HistorySupplementApplyError,
    load_frozen_plan,
    run_gold_batch,
    run_raw_batch,
    run_silver_batch,
    run_source_staging,
    write_report,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply one approved 000680.SH history-supplement stage."
    )
    parser.add_argument("stage", choices=("source", "raw", "silver", "gold"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.apply:
        print("supplement writes require --apply", file=sys.stderr)
        return 2
    output = args.output or Path(
        "/private/tmp/"
        + f"index_daily_000680_history_supplement_{args.stage}_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    try:
        plan = load_frozen_plan(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
            require_green=True,
        )
        duckdb_resource = DuckDBResource()
        if args.stage == "source":
            report = run_source_staging(
                plan=plan,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=duckdb_resource,
                prod_postgres=ProdPostgresResource(),
                apply=True,
            )
        elif args.stage == "raw":
            report = run_raw_batch(
                plan=plan,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=duckdb_resource,
                start_date=args.start_date,
                end_date=args.end_date,
                apply=True,
            )
        elif args.stage == "silver":
            report = run_silver_batch(
                plan=plan,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=duckdb_resource,
                start_date=args.start_date,
                end_date=args.end_date,
                apply=True,
            )
        else:
            report = run_gold_batch(
                plan=plan,
                expected_plan_hash=args.expected_plan_hash,
                duckdb_resource=duckdb_resource,
                start_date=args.start_date,
                end_date=args.end_date,
                apply=True,
            )
        write_report(report, output)
    except (IndexDaily000680HistorySupplementApplyError, OSError, RuntimeError) as error:
        print(f"000680.SH supplement apply stopped: {error}", file=sys.stderr)
        return 3
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
