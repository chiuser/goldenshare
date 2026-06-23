from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import psycopg2

from orchestrator.defs.bootstrap.stk_mins_event_history_retention import (
    STK_MINS_RETENTION_KEEP_TRADE_DAY_COUNT,
    collect_stk_mins_event_history_retention_dry_run,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run audit for stock-mins Dagster event history retention. "
            "This command never deletes rows."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Read Dagster Postgres storage and produce stock-mins cleanup candidates.",
    )
    _add_dry_run_args(dry_run_parser)
    args = parser.parse_args(argv)

    if args.command != "dry-run":
        parser.error(f"Unsupported command: {args.command}")

    with psycopg2.connect(args.postgres_url) as connection:
        report = collect_stk_mins_event_history_retention_dry_run(
            connection,
            sample_limit=args.sample_limit,
            keep_trade_day_count=args.keep_trade_day_count,
        )

    payload = report.to_payload()
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n")
    print(text)
    return 2 if report.should_stop else 0


def _add_dry_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--postgres-url",
        required=True,
        help="Dagster Postgres URL. The CLI opens a read-only session and performs no writes.",
    )
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument(
        "--keep-trade-day-count",
        type=int,
        default=STK_MINS_RETENTION_KEEP_TRADE_DAY_COUNT,
        help="Number of recent cn_a_stock_mins_trade_days partitions to protect.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path. Prefer /private/tmp for formal dry-run reports.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
