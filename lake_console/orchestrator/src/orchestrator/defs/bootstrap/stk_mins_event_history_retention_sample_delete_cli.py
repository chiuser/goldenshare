from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import psycopg2

from orchestrator.defs.bootstrap.stk_mins_event_history_retention import (
    STK_MINS_RETENTION_KEEP_TRADE_DAY_COUNT,
)
from orchestrator.defs.bootstrap.stk_mins_event_history_retention_sample_delete import (
    STK_MINS_RETENTION_DEFAULT_SAMPLE_DELETE_ASSET,
    execute_stk_mins_event_history_retention_sample_delete,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sample-delete executor for stock-mins Dagster event history retention. "
            "This command writes to Dagster Postgres only when --confirm-sample-delete "
            "is present."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    sample_delete_parser = subparsers.add_parser(
        "sample-delete",
        help="Delete old event history for exactly one approved stock-mins sample asset.",
    )
    _add_sample_delete_args(sample_delete_parser)
    args = parser.parse_args(argv)

    if args.command != "sample-delete":
        parser.error(f"Unsupported command: {args.command}")

    with psycopg2.connect(args.postgres_url) as connection:
        report = execute_stk_mins_event_history_retention_sample_delete(
            connection,
            sample_asset=args.sample_asset,
            confirm_sample_delete=args.confirm_sample_delete,
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


def _add_sample_delete_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--postgres-url",
        required=True,
        help="Dagster Postgres URL. Formal execution requires a prior backup.",
    )
    parser.add_argument(
        "--sample-asset",
        default=STK_MINS_RETENTION_DEFAULT_SAMPLE_DELETE_ASSET,
        help="Exactly one stock-mins asset key. Plain one-segment keys are accepted.",
    )
    parser.add_argument(
        "--confirm-sample-delete",
        action="store_true",
        help="Required guard that confirms this command may delete the sample rows.",
    )
    parser.add_argument(
        "--keep-trade-day-count",
        type=int,
        default=STK_MINS_RETENTION_KEEP_TRADE_DAY_COUNT,
        help="Number of recent cn_a_stock_mins_trade_days partitions to protect.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path. Prefer /private/tmp for formal reports.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
