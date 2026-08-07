"""Register major-index minute partitions and report verified runless events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_events import (
    register_major_index_mins_partitions,
    report_major_index_mins_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


DEFAULT_DATE_PLAN_REPORT = Path(
    "/private/tmp/major_index_mins_p6_dry_run_20260805.json"
)
DEFAULT_PROMOTE_REPORT = Path(
    "/private/tmp/major_index_mins_p7e_formal_lake_promote_20260806.json"
)
DEFAULT_FALLBACK_REPORT = Path(
    "/private/tmp/major_index_mins_p7d_temporary_lake_build_20260806_fallback.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("dry-run", "register-partitions", "sample", "apply", "post-audit"),
    )
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument(
        "--date-plan-report",
        type=Path,
        default=DEFAULT_DATE_PLAN_REPORT,
    )
    parser.add_argument(
        "--promote-report",
        type=Path,
        default=DEFAULT_PROMOTE_REPORT,
    )
    parser.add_argument(
        "--fallback-report",
        type=Path,
        default=DEFAULT_FALLBACK_REPORT,
    )
    parser.add_argument("--asset-key", action="append")
    parser.add_argument("--sample-date")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-partition-write", action="store_true")
    parser.add_argument("--confirm-event-write", action="store_true")
    args = parser.parse_args(argv)

    if args.command in {"dry-run", "post-audit"} and (
        args.confirm_partition_write or args.confirm_event_write
    ):
        parser.error(f"{args.command} does not accept write confirmations")
    if args.command == "register-partitions":
        if not args.confirm_partition_write:
            parser.error("register-partitions requires --confirm-partition-write")
        if args.confirm_event_write:
            parser.error("register-partitions does not accept --confirm-event-write")
        if args.asset_key or args.sample_date:
            parser.error("register-partitions does not accept asset/sample filters")
    if args.command in {"sample", "apply"}:
        if not args.confirm_event_write:
            parser.error(f"{args.command} requires --confirm-event-write")
        if args.confirm_partition_write:
            parser.error(f"{args.command} does not accept --confirm-partition-write")
    if args.command != "sample" and args.sample_date:
        parser.error("--sample-date is only valid for sample")

    instance = dg.DagsterInstance.get()
    if args.command == "register-partitions":
        report = register_major_index_mins_partitions(
            instance=instance,
            lake_root=args.lake_root,
            date_plan_report_path=args.date_plan_report,
            promote_report_path=args.promote_report,
            fallback_report_path=args.fallback_report,
            duckdb_resource=DuckDBResource(),
            confirm_partition_write=True,
        )
    else:
        report = report_major_index_mins_events(
            instance=instance,
            lake_root=args.lake_root,
            date_plan_report_path=args.date_plan_report,
            promote_report_path=args.promote_report,
            fallback_report_path=args.fallback_report,
            duckdb_resource=DuckDBResource(),
            dry_run=args.command in {"dry-run", "post-audit"},
            confirm_event_write=args.confirm_event_write,
            sample_only=args.command == "sample",
            sample_date=args.sample_date,
            selected_asset_keys=args.asset_key,
            report_mode="post-audit" if args.command == "post-audit" else None,
        )
    payload = report.to_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
