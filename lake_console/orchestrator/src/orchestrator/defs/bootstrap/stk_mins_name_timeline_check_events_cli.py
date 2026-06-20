from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stk_mins_name_timeline_check_events import (
    MAX_TARGET_EVENT_COUNT,
    TARGET_LAST_TRADE_DATE,
    TARGET_TS_CODE,
    dry_run_silver_name_timeline_check_event_correction,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run audit for silver stk_mins name timeline check event correction."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Read lake files and Dagster event history without writing events.",
    )
    _add_dry_run_args(dry_run_parser)
    args = parser.parse_args(argv)

    if args.command != "dry-run":
        parser.error(f"Unsupported command: {args.command}")

    instance = dg.DagsterInstance.get()
    with connect_configured_duckdb() as connection:
        report = dry_run_silver_name_timeline_check_event_correction(
            instance=instance,
            connection=connection,
            lake_root=Path(args.lake_root),
            ts_code=args.ts_code,
            end_date=args.end_date,
            max_expected_events=args.max_expected_events,
            history_page_limit=args.history_page_limit,
            max_history_records_per_check_key=args.max_history_records_per_check_key,
            sample_limit=args.sample_limit,
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
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--ts-code", default=TARGET_TS_CODE)
    parser.add_argument("--end-date", default=TARGET_LAST_TRADE_DATE)
    parser.add_argument("--max-expected-events", type=int, default=MAX_TARGET_EVENT_COUNT)
    parser.add_argument("--history-page-limit", type=int, default=5_000)
    parser.add_argument(
        "--max-history-records-per-check-key",
        type=int,
        default=100_000,
    )
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path. Prefer /private/tmp for formal dry-run reports.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
