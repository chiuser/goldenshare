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
from orchestrator.defs.bootstrap.stk_mins_silver_bootstrap_events import (
    audit_stk_mins_silver_final_state,
    register_stock_mins_silver_partitions,
    report_stk_mins_silver_bootstrap_events,
)
from orchestrator.defs.bootstrap.stk_mins_silver_history import (
    STK_MINS_SILVER_HISTORY_START_DATE,
    all_silver_partition_keys,
    generate_stk_mins_silver_history,
    plan_stk_mins_silver_history,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
    generate_stk_mins_qfq_history,
    plan_stk_mins_qfq_history,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_bootstrap_events import (
    audit_stk_mins_qfq_final_state,
    plan_stk_mins_qfq_bootstrap_events,
    report_stk_mins_qfq_bootstrap_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_derived_bootstrap_events import (
    audit_stk_mins_qfq_derived_final_state,
    plan_stk_mins_qfq_derived_bootstrap_events,
    report_stk_mins_qfq_derived_bootstrap_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_derived_history import (
    generate_stk_mins_qfq_derived_history,
    plan_stk_mins_qfq_derived_history,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main(argv: list[str] | None = None) -> None:
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

    plan_silver = subparsers.add_parser("plan-silver")
    plan_silver.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_silver_history_range(plan_silver)
    plan_silver.add_argument("--partition-keys")

    generate_silver = subparsers.add_parser("generate-silver")
    generate_silver.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_silver_partition_selection(generate_silver)
    generate_silver.add_argument("--skip-existing", action="store_true")
    generate_silver.add_argument("--overwrite", action="store_true")

    register_silver = subparsers.add_parser("register-silver-partitions")
    register_silver.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_silver_partition_selection(register_silver, include_silver_files=True)
    register_silver.add_argument("--dry-run", action="store_true")

    silver_events = subparsers.add_parser("report-silver-events")
    silver_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_silver_partition_selection(silver_events, include_silver_files=True)
    silver_events.add_argument("--dry-run", action="store_true")
    silver_events.add_argument("--skip-existing-materialized", action="store_true")

    silver_audit_final = subparsers.add_parser("audit-silver-final")
    silver_audit_final.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_silver_history_range(silver_audit_final)

    plan_gold_qfq = subparsers.add_parser("plan-gold-qfq-history")
    plan_gold_qfq.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(plan_gold_qfq)

    generate_gold_qfq = subparsers.add_parser("generate-gold-qfq-history")
    generate_gold_qfq.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(generate_gold_qfq)

    plan_gold_qfq_events = subparsers.add_parser("plan-gold-qfq-events")
    plan_gold_qfq_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(plan_gold_qfq_events)

    report_gold_qfq_events = subparsers.add_parser("report-gold-qfq-events")
    report_gold_qfq_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(report_gold_qfq_events)
    report_gold_qfq_events.add_argument("--dry-run", action="store_true")
    report_gold_qfq_events.add_argument("--skip-existing-ready", action="store_true")

    audit_gold_qfq_final = subparsers.add_parser("audit-gold-qfq-final")
    audit_gold_qfq_final.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(audit_gold_qfq_final)

    plan_gold_qfq_derived = subparsers.add_parser("plan-gold-qfq-derived-history")
    plan_gold_qfq_derived.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(plan_gold_qfq_derived)

    generate_gold_qfq_derived = subparsers.add_parser(
        "generate-gold-qfq-derived-history"
    )
    generate_gold_qfq_derived.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(generate_gold_qfq_derived)

    plan_gold_qfq_derived_events = subparsers.add_parser(
        "plan-gold-qfq-derived-events"
    )
    plan_gold_qfq_derived_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(plan_gold_qfq_derived_events)

    report_gold_qfq_derived_events = subparsers.add_parser(
        "report-gold-qfq-derived-events"
    )
    report_gold_qfq_derived_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(report_gold_qfq_derived_events)
    report_gold_qfq_derived_events.add_argument("--dry-run", action="store_true")
    report_gold_qfq_derived_events.add_argument(
        "--skip-existing-ready",
        action="store_true",
    )

    audit_gold_qfq_derived_final = subparsers.add_parser(
        "audit-gold-qfq-derived-final"
    )
    audit_gold_qfq_derived_final.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    _add_gold_qfq_history_selection(audit_gold_qfq_derived_final)

    args = parser.parse_args(argv)
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
    elif args.command == "plan-silver":
        report = plan_stk_mins_silver_history(
            lake_root=Path(args.lake_root),
            partition_keys=_optional_partition_keys(args),
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
            partition_keys=_selected_silver_partition_keys(args, from_raw=True),
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
        selected_keys = _selected_silver_partition_keys(args, from_silver=True)
        if selected_keys is None:
            raise ValueError(
                "Pass --partition-keys, --all, or --all-from-silver-files."
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
            partition_keys=_selected_silver_partition_keys(args, from_silver=True),
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
    elif args.command == "plan-gold-qfq-history":
        report = plan_stk_mins_qfq_history(
            lake_root=Path(args.lake_root),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
            duckdb_resource=DuckDBResource(),
        )
        print(
            {
                "selected_partition_count": len(report.selected_partition_keys),
                "selected_freqs": list(report.selected_freqs),
                "selected_years": list(report.selected_years),
                "batch_count": len(report.batches),
                "planned_target_file_count": report.planned_target_file_count,
                "existing_target_file_count": report.existing_target_file_count,
                "missing_input_count": report.missing_input_count,
                "missing_input_samples": list(report.missing_input_samples),
                "planned_event_count": report.planned_event_count,
                "target_file_counts_by_batch": {
                    f"{freq}:{year}": count
                    for (freq, year), count in report.target_file_counts_by_batch.items()
                },
            }
        )
    elif args.command == "generate-gold-qfq-history":
        report = generate_stk_mins_qfq_history(
            lake_root=Path(args.lake_root),
            duckdb_resource=DuckDBResource(),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
        )
        print(
            {
                "selected_partition_count": len(report.plan.selected_partition_keys),
                "selected_freqs": list(report.plan.selected_freqs),
                "selected_years": list(report.plan.selected_years),
                "batch_count": len(report.batch_results),
                "written_file_count": report.written_file_count,
                "written_row_count": report.written_row_count,
                "planned_event_count": report.plan.planned_event_count,
            }
        )
    elif args.command == "plan-gold-qfq-events":
        report = plan_stk_mins_qfq_bootstrap_events(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
            duckdb_resource=DuckDBResource(),
        )
        print(
            {
                "selected_partition_count": len(report.selected_partition_keys),
                "selected_freqs": list(report.selected_freqs),
                "selected_years": list(report.selected_years),
                "asset_partition_count": report.asset_partition_count,
                "planned_target_file_count": report.planned_target_file_count,
                "existing_target_file_count": report.existing_target_file_count,
                "missing_input_count": report.missing_input_count,
                "missing_input_samples": list(report.missing_input_samples),
                "planned_event_count": report.planned_event_count,
                "materialized_partition_counts": dict(
                    report.materialized_partition_counts
                ),
                "check_success_counts": dict(report.check_success_counts),
            }
        )
    elif args.command == "report-gold-qfq-events":
        report = report_stk_mins_qfq_bootstrap_events(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            duckdb=DuckDBResource(),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
            dry_run=args.dry_run,
            skip_existing_ready=args.skip_existing_ready,
        )
        print(
            {
                "dry_run": report.dry_run,
                "selected_partition_count": len(report.plan.selected_partition_keys),
                "selected_freqs": list(report.plan.selected_freqs),
                "audited_asset_partition_count": len(report.partition_audits),
                "failed_partition_count": report.failed_partition_count,
                "reported_asset_partition_count": len(report.reported_asset_partitions),
                "skipped_ready_asset_partition_count": len(
                    report.skipped_ready_asset_partitions
                ),
                "reported_event_count": report.reported_event_count,
            }
        )
    elif args.command == "audit-gold-qfq-final":
        report = audit_stk_mins_qfq_final_state(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
            duckdb_resource=DuckDBResource(),
        )
        print(
            {
                "selected_partition_count": report.selected_partition_count,
                "selected_freqs": list(report.selected_freqs),
                "planned_target_file_count": report.planned_target_file_count,
                "existing_target_file_count": report.existing_target_file_count,
                "missing_input_count": report.missing_input_count,
                "materialized_partition_counts": dict(
                    report.materialized_partition_counts
                ),
                "check_success_counts": dict(report.check_success_counts),
                "sample_readiness": dict(report.sample_readiness),
            }
        )
    elif args.command == "plan-gold-qfq-derived-history":
        report = plan_stk_mins_qfq_derived_history(
            lake_root=Path(args.lake_root),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
            duckdb_resource=DuckDBResource(),
        )
        print(
            {
                "selected_partition_count": len(report.selected_partition_keys),
                "selected_target_freqs": list(report.selected_target_freqs),
                "selected_years": list(report.selected_years),
                "batch_count": len(report.batches),
                "planned_source_file_count": report.planned_source_file_count,
                "planned_source_row_count": report.planned_source_row_count,
                "planned_source_stock_day_count": (
                    report.planned_source_stock_day_count
                ),
                "planned_target_file_count": report.planned_target_file_count,
                "planned_target_row_count": report.planned_target_row_count,
                "existing_target_file_count": report.existing_target_file_count,
                "missing_input_count": report.missing_input_count,
                "missing_input_samples": list(report.missing_input_samples),
                "planned_event_count": report.planned_event_count,
                "target_file_counts_by_batch": {
                    f"{freq}:{year}": estimate.planned_target_file_count
                    for (freq, year), estimate in report.estimates_by_batch.items()
                },
            }
        )
    elif args.command == "generate-gold-qfq-derived-history":
        report = generate_stk_mins_qfq_derived_history(
            lake_root=Path(args.lake_root),
            duckdb_resource=DuckDBResource(),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
        )
        print(
            {
                "selected_partition_count": len(report.plan.selected_partition_keys),
                "selected_target_freqs": list(report.plan.selected_target_freqs),
                "selected_years": list(report.plan.selected_years),
                "batch_count": len(report.batch_results),
                "written_file_count": report.written_file_count,
                "written_row_count": report.written_row_count,
                "planned_event_count": report.plan.planned_event_count,
            }
        )
    elif args.command == "plan-gold-qfq-derived-events":
        report = plan_stk_mins_qfq_derived_bootstrap_events(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
            duckdb_resource=DuckDBResource(),
        )
        print(
            {
                "selected_partition_count": len(report.selected_partition_keys),
                "selected_target_freqs": list(report.selected_target_freqs),
                "selected_years": list(report.selected_years),
                "asset_partition_count": report.asset_partition_count,
                "planned_source_file_count": report.planned_source_file_count,
                "planned_source_row_count": report.planned_source_row_count,
                "planned_target_file_count": report.planned_target_file_count,
                "planned_target_row_count": report.planned_target_row_count,
                "existing_target_file_count": report.existing_target_file_count,
                "missing_input_count": report.missing_input_count,
                "missing_input_samples": list(report.missing_input_samples),
                "planned_event_count": report.planned_event_count,
                "materialized_partition_counts": dict(
                    report.materialized_partition_counts
                ),
                "check_success_counts": dict(report.check_success_counts),
            }
        )
    elif args.command == "report-gold-qfq-derived-events":
        report = report_stk_mins_qfq_derived_bootstrap_events(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            duckdb=DuckDBResource(),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
            dry_run=args.dry_run,
            skip_existing_ready=args.skip_existing_ready,
        )
        print(
            {
                "dry_run": report.dry_run,
                "selected_partition_count": len(report.plan.selected_partition_keys),
                "selected_target_freqs": list(report.plan.selected_target_freqs),
                "audited_asset_partition_count": len(report.partition_audits),
                "failed_partition_count": report.failed_partition_count,
                "reported_asset_partition_count": len(report.reported_asset_partitions),
                "skipped_ready_asset_partition_count": len(
                    report.skipped_ready_asset_partitions
                ),
                "reported_event_count": report.reported_event_count,
            }
        )
    elif args.command == "audit-gold-qfq-derived-final":
        report = audit_stk_mins_qfq_derived_final_state(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            registered_partition_keys=_registered_stock_mins_silver_partition_keys(),
            partition_keys=_optional_partition_keys(args),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=_optional_csv_values(args.freqs),
            years=_optional_csv_values(args.years),
            duckdb_resource=DuckDBResource(),
        )
        print(
            {
                "selected_partition_count": report.selected_partition_count,
                "selected_target_freqs": list(report.selected_target_freqs),
                "planned_source_file_count": report.planned_source_file_count,
                "planned_source_row_count": report.planned_source_row_count,
                "planned_target_file_count": report.planned_target_file_count,
                "existing_target_file_count": report.existing_target_file_count,
                "missing_input_count": report.missing_input_count,
                "materialized_partition_counts": dict(
                    report.materialized_partition_counts
                ),
                "check_success_counts": dict(report.check_success_counts),
                "sample_readiness": dict(report.sample_readiness),
            }
        )


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


def _add_silver_history_range(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start-date", default=STK_MINS_SILVER_HISTORY_START_DATE)
    parser.add_argument("--end-date")


def _add_gold_qfq_history_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start-date", default=STK_MINS_QFQ_HISTORY_START_DATE)
    parser.add_argument("--end-date")
    parser.add_argument("--partition-keys")
    parser.add_argument("--freqs")
    parser.add_argument("--years")


def _add_silver_partition_selection(
    parser: argparse.ArgumentParser,
    *,
    include_silver_files: bool = False,
) -> None:
    parser.add_argument("--partition-keys")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--all-from-raw-files", action="store_true")
    if include_silver_files:
        parser.add_argument("--all-from-silver-files", action="store_true")
    _add_silver_history_range(parser)


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


def _optional_partition_keys(args) -> tuple[str, ...] | None:
    if getattr(args, "partition_keys", None):
        return tuple(
            sorted(
                key.strip()
                for key in args.partition_keys.split(",")
                if key.strip()
            )
        )
    return None


def _optional_csv_values(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _registered_stock_mins_silver_partition_keys() -> tuple[str, ...]:
    return tuple(
        sorted(
            dg.DagsterInstance.get().get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )


def _selected_silver_partition_keys(
    args,
    *,
    from_raw: bool = False,
    from_silver: bool = False,
) -> tuple[str, ...] | None:
    if getattr(args, "partition_keys", None):
        return tuple(
            sorted(
                key.strip()
                for key in args.partition_keys.split(",")
                if key.strip()
            )
        )
    if getattr(args, "all_from_raw_files", False):
        keys = all_raw_partition_keys(Path(args.lake_root))
        return tuple(
            key
            for key in keys
            if key >= args.start_date and (args.end_date is None or key <= args.end_date)
        )
    if getattr(args, "all_from_silver_files", False):
        return all_silver_partition_keys(
            Path(args.lake_root),
            start_date=args.start_date,
            end_date=args.end_date,
        )
    if getattr(args, "all", False):
        if from_silver:
            return all_silver_partition_keys(
                Path(args.lake_root),
                start_date=args.start_date,
                end_date=args.end_date,
            )
        if from_raw:
            keys = all_raw_partition_keys(Path(args.lake_root))
            return tuple(
                key
                for key in keys
                if key >= args.start_date
                and (args.end_date is None or key <= args.end_date)
            )
    if from_silver:
        return None
    raise ValueError(
        "Pass --partition-keys, --all, --all-from-raw-files, or --all-from-silver-files."
    )


if __name__ == "__main__":
    main()
