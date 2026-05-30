from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.specs.stk_mins import BACKUP_STK_MINS_ROOT
from orchestrator.defs.bootstrap.specs.stock_identity_map import OLD_TUSHARE_LAKE_ROOT
from orchestrator.defs.bootstrap.stk_mins_migration import (
    SAMPLE_PARTITION_KEYS,
    all_backup_partition_keys,
    all_raw_partition_keys,
    audit_stk_mins_final_state,
    migrate_stk_mins_raw_history,
    migrate_stock_identity_map_snapshot,
    plan_stk_mins_migration,
    register_stock_mins_partitions,
    report_stk_mins_raw_bootstrap_events,
    report_stock_identity_map_bootstrap_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main() -> None:
    parser = argparse.ArgumentParser(description="stk_mins historical migration helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_common_paths(subparsers.add_parser("dry-run"))
    migrate_raw = subparsers.add_parser("migrate-raw")
    _add_lake_and_backup(migrate_raw)
    _add_partition_selection(migrate_raw)
    migrate_raw.add_argument("--skip-existing", action="store_true")
    migrate_raw.add_argument("--overwrite", action="store_true")

    migrate_identity = subparsers.add_parser("migrate-identity-map")
    _add_lake_and_old_lake(migrate_identity)
    migrate_identity.add_argument("--overwrite", action="store_true")

    register = subparsers.add_parser("register-partitions")
    register.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_partition_selection(register, include_raw_files=True)

    raw_events = subparsers.add_parser("report-raw-events")
    raw_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_partition_selection(raw_events)
    raw_events.add_argument("--dry-run", action="store_true")
    raw_events.add_argument("--skip-existing-ready", action="store_true")

    identity_events = subparsers.add_parser("report-identity-map-events")
    identity_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    identity_events.add_argument("--dry-run", action="store_true")
    identity_events.add_argument("--skip-existing-ready", action="store_true")

    audit_final = subparsers.add_parser("audit-final")
    _add_lake_and_backup(audit_final)

    args = parser.parse_args()
    if args.command == "dry-run":
        _print_plan(args)
    elif args.command == "migrate-raw":
        report = migrate_stk_mins_raw_history(
            lake_root=Path(args.lake_root),
            backup_root=Path(args.backup_root),
            partition_keys=_selected_partition_keys(args),
            duckdb=DuckDBResource(),
            skip_existing=args.skip_existing,
            overwrite=args.overwrite,
        )
        print(
            {
                "written_file_count": len(report.written_files),
                "skipped_existing_file_count": len(report.skipped_existing_files),
                "partition_count": len(report.partition_keys),
            }
        )
    elif args.command == "migrate-identity-map":
        metadata = migrate_stock_identity_map_snapshot(
            lake_root=Path(args.lake_root),
            old_lake_root=Path(args.old_lake_root),
            duckdb=DuckDBResource(),
            overwrite=args.overwrite,
        )
        print(metadata)
    elif args.command == "register-partitions":
        keys = (
            all_raw_partition_keys(Path(args.lake_root))
            if args.all_from_raw_files
            else _selected_partition_keys(args)
        )
        report = register_stock_mins_partitions(
            instance=dg.DagsterInstance.get(),
            partition_keys=keys,
        )
        print(
            {
                "requested_partition_count": len(report.requested_partition_keys),
                "existing_partition_count": len(report.existing_partition_keys),
                "registered_partition_count": len(report.registered_partition_keys),
            }
        )
    elif args.command == "report-raw-events":
        report = report_stk_mins_raw_bootstrap_events(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            duckdb=DuckDBResource(),
            partition_keys=_selected_partition_keys(args, from_raw=True),
            dry_run=args.dry_run,
            skip_existing_ready=args.skip_existing_ready,
        )
        print(
            {
                "dry_run": report.dry_run,
                "selected_partition_count": len(report.selected_partition_keys),
                "audit_count": len(report.partition_audits),
                "failed_audit_count": report.failed_audit_count,
                "reported_asset_partition_count": len(report.reported_asset_partitions),
                "skipped_ready_asset_partition_count": len(
                    report.skipped_ready_asset_partitions
                ),
                "reported_event_count": report.reported_event_count,
            }
        )
    elif args.command == "report-identity-map-events":
        report = report_stock_identity_map_bootstrap_events(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            duckdb=DuckDBResource(),
            dry_run=args.dry_run,
            skip_existing_ready=args.skip_existing_ready,
        )
        print(
            {
                "dry_run": report.dry_run,
                "passed": report.audit.passed,
                "row_count": report.audit.row_count,
                "reported_event_count": report.reported_event_count,
                "skipped_ready": report.skipped_ready,
            }
        )
    elif args.command == "audit-final":
        report = audit_stk_mins_final_state(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            backup_root=Path(args.backup_root),
        )
        print(report)


def _print_plan(args) -> None:
    plan = plan_stk_mins_migration(
        lake_root=Path(args.lake_root),
        backup_root=Path(args.backup_root),
        old_lake_root=Path(args.old_lake_root),
    )
    print(
        {
            "partition_count": len(plan.partition_keys),
            "backup_partition_counts": dict(plan.backup_partition_counts),
            "target_existing_counts": dict(plan.target_existing_counts),
            "backup_file_size_bytes": plan.backup_file_size_bytes,
            "target_filesystem_free_bytes": plan.target_filesystem_free_bytes,
            "planned_raw_file_count": plan.planned_raw_file_count,
            "planned_raw_event_count": plan.planned_raw_event_count,
            "identity_map_source_exists": plan.identity_map_source_exists,
            "identity_map_target_exists": plan.identity_map_target_exists,
            "sample_partition_keys": list(SAMPLE_PARTITION_KEYS),
        }
    )


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    _add_lake_and_backup(parser)
    parser.add_argument("--old-lake-root", default=str(OLD_TUSHARE_LAKE_ROOT))


def _add_lake_and_backup(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--backup-root", default=str(BACKUP_STK_MINS_ROOT))


def _add_lake_and_old_lake(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--old-lake-root", default=str(OLD_TUSHARE_LAKE_ROOT))


def _add_partition_selection(
    parser: argparse.ArgumentParser,
    *,
    include_raw_files: bool = False,
) -> None:
    parser.add_argument("--partition-keys")
    parser.add_argument("--all", action="store_true")
    if include_raw_files:
        parser.add_argument("--all-from-raw-files", action="store_true")


def _selected_partition_keys(args, *, from_raw: bool = False) -> tuple[str, ...]:
    if getattr(args, "partition_keys", None):
        return tuple(
            sorted(
                key.strip()
                for key in args.partition_keys.split(",")
                if key.strip()
            )
        )
    if getattr(args, "all", False):
        if from_raw:
            return all_raw_partition_keys(Path(args.lake_root))
        return all_backup_partition_keys(Path(getattr(args, "backup_root", BACKUP_STK_MINS_ROOT)))
    raise ValueError("Pass --partition-keys or --all.")


if __name__ == "__main__":
    main()
