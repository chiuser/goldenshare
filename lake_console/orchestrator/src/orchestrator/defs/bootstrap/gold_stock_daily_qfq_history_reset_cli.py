from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import psycopg2

from orchestrator.defs.bootstrap.gold_stock_daily_qfq_history_reset import (
    execute_gold_stock_daily_qfq_history_reset,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reset old gold_stock_daily_qfq history files/events before P8 "
            "as-of bootstrap rebuild. Defaults to dry-run."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="List old lake files and Dagster event candidates without deleting.",
    )
    _add_common_args(dry_run_parser)
    apply_parser = subparsers.add_parser(
        "apply",
        help=(
            "Delete one scoped old target after backup and explicit confirmation. "
            "Run lake files and Dagster events as separate approved steps."
        ),
    )
    _add_common_args(apply_parser)
    _add_apply_args(apply_parser)
    args = parser.parse_args(argv)

    apply = args.command == "apply"
    with psycopg2.connect(args.postgres_url) as connection:
        report = execute_gold_stock_daily_qfq_history_reset(
            connection,
            lake_root=Path(args.lake_root),
            apply=apply,
            confirm_reset=getattr(args, "confirm_reset", False),
            backup_path=getattr(args, "backup_path", None),
            delete_lake_files=getattr(args, "delete_lake_files", True),
            delete_dagster_events=getattr(args, "delete_dagster_events", True),
            sample_limit=args.sample_limit,
        )

    payload = report.to_payload()
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 2 if report.should_stop else 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--postgres-url",
        required=True,
        help="Dagster Postgres URL. Apply requires a verified backup path.",
    )
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--output")


def _add_apply_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--confirm-reset",
        action="store_true",
        help="Required guard before deleting old gold_stock_daily_qfq files/events.",
    )
    parser.add_argument(
        "--backup-path",
        required=True,
        help="Path to a verified Dagster Postgres backup or restore marker.",
    )
    parser.add_argument(
        "--delete-lake-files",
        action="store_true",
        help="Delete only scoped gold_stock_daily_qfq lake files.",
    )
    parser.add_argument(
        "--delete-dagster-events",
        action="store_true",
        help="Delete only scoped gold_stock_daily_qfq materialization/check events.",
    )
    parser.set_defaults(delete_lake_files=False, delete_dagster_events=False)


if __name__ == "__main__":
    raise SystemExit(main())
