from __future__ import annotations

import argparse
import sys
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stk_mins_history_cli_contract import (
    parse_optional_partition_keys,
)
from orchestrator.defs.bootstrap.stk_mins_silver_bootstrap_events import (
    audit_stk_mins_silver_final_state,
    register_stock_mins_silver_partitions,
    report_stk_mins_silver_bootstrap_events,
)
from orchestrator.defs.bootstrap.stk_mins_silver_history import (
    STK_MINS_SILVER_HISTORY_START_DATE,
    all_raw_stk_mins_partition_keys,
    all_silver_partition_keys,
    generate_stk_mins_silver_history,
    plan_stk_mins_silver_history,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="stk mins silver history helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_silver = subparsers.add_parser("plan-silver")
    plan_silver.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_silver_history_range(plan_silver)
    plan_silver.add_argument("--partition-keys")
    generate_silver = subparsers.add_parser("generate-silver")
    generate_silver.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    generate_silver.add_argument("--partition-keys")
    generate_silver.add_argument("--all-from-raw-files", action="store_true")
    _add_silver_history_range(generate_silver)
    generate_silver.add_argument("--skip-existing", action="store_true")
    generate_silver.add_argument("--overwrite", action="store_true")
    register_silver = subparsers.add_parser("register-silver-partitions")
    register_silver.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    register_silver.add_argument("--partition-keys")
    register_silver.add_argument("--all-from-silver-files", action="store_true")
    _add_silver_history_range(register_silver)
    register_silver.add_argument("--dry-run", action="store_true")
    silver_events = subparsers.add_parser("report-silver-events")
    silver_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    silver_events.add_argument("--partition-keys")
    silver_events.add_argument("--all-from-silver-files", action="store_true")
    _add_silver_history_range(silver_events)
    silver_events.add_argument("--dry-run", action="store_true")
    silver_events.add_argument("--skip-existing-materialized", action="store_true")
    silver_audit_final = subparsers.add_parser("audit-silver-final")
    silver_audit_final.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_silver_history_range(silver_audit_final)
    args = parser.parse_args(argv)
    # argparse would otherwise accept the removed token as a file-selector prefix.
    if "--all" in (sys.argv[1:] if argv is None else argv):
        parser.error("unrecognized arguments: --all")
    if args.command == "plan-silver":
        report = plan_stk_mins_silver_history(
            lake_root=Path(args.lake_root),
            partition_keys=parse_optional_partition_keys(args.partition_keys),
            start_date=args.start_date,
            end_date=args.end_date,
        )
        print(
            {
                "selected_partition_count": len(report.selected_partition_keys),
                "raw_partition_counts": dict(report.raw_partition_counts),
                "existing_silver_partition_counts": dict(
                    report.existing_silver_partition_counts
                ),
                "planned_write_count": report.planned_write_count,
                "planned_event_count": report.planned_event_count,
                "missing_input_count": report.missing_input_count,
                "missing_input_samples": list(report.missing_input_samples),
                "sample_partition_keys": list(report.sample_partition_keys),
            }
        )
    elif args.command == "generate-silver":
        report = generate_stk_mins_silver_history(
            lake_root=Path(args.lake_root),
            duckdb=DuckDBResource(),
            partition_keys=_selected_raw_partition_keys(args),
            skip_existing=args.skip_existing,
            overwrite=args.overwrite,
        )
        print(
            {
                "selected_partition_count": len(report.selected_partition_keys),
                "written_asset_partition_count": len(report.written_asset_partitions),
                "skipped_existing_asset_partition_count": len(
                    report.skipped_existing_asset_partitions
                ),
            }
        )
    elif args.command == "register-silver-partitions":
        selected_keys = _selected_silver_partition_keys(args)
        if selected_keys is None:
            raise ValueError(
                "Pass --partition-keys or --all-from-silver-files."
            )
        report = register_stock_mins_silver_partitions(
            instance=dg.DagsterInstance.get(),
            partition_keys=selected_keys,
            dry_run=args.dry_run,
        )
        print(
            {
                "dry_run": report.dry_run,
                "requested_partition_count": len(report.requested_partition_keys),
                "existing_partition_count": len(report.existing_partition_keys),
                "registered_partition_count": len(report.registered_partition_keys),
            }
        )
    elif args.command == "report-silver-events":
        report = report_stk_mins_silver_bootstrap_events(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            duckdb=DuckDBResource(),
            partition_keys=_selected_silver_partition_keys(args),
            dry_run=args.dry_run,
            skip_existing_materialized=args.skip_existing_materialized,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        print(
            {
                "dry_run": report.dry_run,
                "selected_partition_count": len(report.plan.selected_partition_keys),
                "failed_partition_count": report.plan.failed_partition_count,
                "planned_event_count": report.plan.planned_event_count,
                "reported_asset_partition_count": len(report.reported_asset_partitions),
                "skipped_materialized_asset_partition_count": len(
                    report.skipped_materialized_asset_partitions
                ),
                "reported_event_count": report.reported_event_count,
            }
        )
    elif args.command == "audit-silver-final":
        report = audit_stk_mins_silver_final_state(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            start_date=args.start_date,
            end_date=args.end_date,
        )
        print(report)


def _add_silver_history_range(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start-date", default=STK_MINS_SILVER_HISTORY_START_DATE)
    parser.add_argument("--end-date")


def _selected_raw_partition_keys(args: argparse.Namespace) -> tuple[str, ...]:
    keys = parse_optional_partition_keys(args.partition_keys)
    if keys is not None:
        return keys
    if args.all_from_raw_files:
        keys = all_raw_stk_mins_partition_keys(Path(args.lake_root))
        return tuple(
            key
            for key in keys
            if key >= args.start_date
            and (args.end_date is None or key <= args.end_date)
        )
    raise ValueError("Pass --partition-keys or --all-from-raw-files.")


def _selected_silver_partition_keys(
    args: argparse.Namespace,
) -> tuple[str, ...] | None:
    keys = parse_optional_partition_keys(args.partition_keys)
    if keys is not None:
        return keys
    if args.all_from_silver_files:
        return all_silver_partition_keys(
            Path(args.lake_root), start_date=args.start_date, end_date=args.end_date
        )
    return None


if __name__ == "__main__":
    main()
