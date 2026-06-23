from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import psycopg2

from orchestrator.defs.bootstrap.event_history_retention_dry_run import (
    DEFAULT_RETIRED_CHECK_NAME_CANDIDATES,
    DEFAULT_SAMPLE_ASSET_KEYS,
    PROTECTED_STATUS_CHECK_NAMES,
    collect_event_history_retention_dry_run,
    collect_event_history_retention_sample_dry_run,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run audit for Dagster event history retention cleanup."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Read Dagster Postgres storage and produce cleanup candidates without deleting anything.",
    )
    _add_dry_run_args(dry_run_parser)
    sample_dry_run_parser = subparsers.add_parser(
        "sample-dry-run",
        help="Read-only cleanup candidate audit for a small asset whitelist.",
    )
    _add_sample_dry_run_args(sample_dry_run_parser)
    args = parser.parse_args(argv)

    if args.command == "dry-run":
        with psycopg2.connect(args.postgres_url) as connection:
            report = collect_event_history_retention_dry_run(
                connection,
                sample_limit=args.sample_limit,
                protected_check_names=tuple(args.protected_check_name),
                retired_check_name_candidates=tuple(args.retired_check_name),
            )
    elif args.command == "sample-dry-run":
        with psycopg2.connect(args.postgres_url) as connection:
            report = collect_event_history_retention_sample_dry_run(
                connection,
                asset_keys=_selected_sample_assets(args.sample_asset),
                sample_limit=args.sample_limit,
                protected_check_names=tuple(args.protected_check_name),
            )
    else:
        parser.error(f"Unsupported command: {args.command}")

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
        "--protected-check-name",
        action="append",
        default=list(PROTECTED_STATUS_CHECK_NAMES),
        help="Check name that must never enter cleanup candidates.",
    )
    parser.add_argument(
        "--retired-check-name",
        action="append",
        default=list(DEFAULT_RETIRED_CHECK_NAME_CANDIDATES),
        help="Retired check name candidate to report separately.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path. Prefer /private/tmp for formal dry-run reports.",
    )


def _add_sample_dry_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--postgres-url",
        required=True,
        help="Dagster Postgres URL. The CLI opens a read-only session and performs no writes.",
    )
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument(
        "--sample-asset",
        action="append",
        default=None,
        help="Sample asset key to audit. Plain one-segment keys are accepted.",
    )
    parser.add_argument(
        "--protected-check-name",
        action="append",
        default=list(PROTECTED_STATUS_CHECK_NAMES),
        help="Check name that must never enter cleanup candidates.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path. Prefer /private/tmp for formal sample reports.",
    )


def _selected_sample_assets(sample_assets: Sequence[str] | None) -> tuple[str, ...]:
    if sample_assets:
        return tuple(sample_assets)
    return tuple(DEFAULT_SAMPLE_ASSET_KEYS)


if __name__ == "__main__":
    raise SystemExit(main())
