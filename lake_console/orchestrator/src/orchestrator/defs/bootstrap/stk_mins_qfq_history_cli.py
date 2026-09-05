from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stk_mins_history_cli_contract import (
    add_history_selection_arguments,
    parse_optional_csv_values,
    parse_optional_partition_keys,
    registered_stk_mins_silver_partition_keys,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_bootstrap_events import (
    audit_stk_mins_qfq_final_state,
    plan_stk_mins_qfq_bootstrap_events,
    report_stk_mins_qfq_bootstrap_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
    generate_stk_mins_qfq_history,
    plan_stk_mins_qfq_history,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="stk mins qfq history helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_gold_qfq = subparsers.add_parser("plan-gold-qfq-history")
    plan_gold_qfq.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    add_history_selection_arguments(
        plan_gold_qfq, default_start_date=STK_MINS_QFQ_HISTORY_START_DATE
    )
    generate_gold_qfq = subparsers.add_parser("generate-gold-qfq-history")
    generate_gold_qfq.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    add_history_selection_arguments(
        generate_gold_qfq, default_start_date=STK_MINS_QFQ_HISTORY_START_DATE
    )
    plan_gold_qfq_events = subparsers.add_parser("plan-gold-qfq-events")
    plan_gold_qfq_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    add_history_selection_arguments(
        plan_gold_qfq_events, default_start_date=STK_MINS_QFQ_HISTORY_START_DATE
    )
    report_gold_qfq_events = subparsers.add_parser("report-gold-qfq-events")
    report_gold_qfq_events.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    add_history_selection_arguments(
        report_gold_qfq_events, default_start_date=STK_MINS_QFQ_HISTORY_START_DATE
    )
    report_gold_qfq_events.add_argument("--dry-run", action="store_true")
    report_gold_qfq_events.add_argument("--skip-existing-ready", action="store_true")
    audit_gold_qfq_final = subparsers.add_parser("audit-gold-qfq-final")
    audit_gold_qfq_final.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    add_history_selection_arguments(
        audit_gold_qfq_final, default_start_date=STK_MINS_QFQ_HISTORY_START_DATE
    )
    args = parser.parse_args(argv)
    if args.command == "plan-gold-qfq-history":
        report = plan_stk_mins_qfq_history(
            lake_root=Path(args.lake_root),
            registered_partition_keys=registered_stk_mins_silver_partition_keys(),
            partition_keys=parse_optional_partition_keys(args.partition_keys),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=parse_optional_csv_values(args.freqs),
            years=parse_optional_csv_values(args.years),
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
                    for (
                        freq,
                        year,
                    ), count in report.target_file_counts_by_batch.items()
                },
            }
        )
    elif args.command == "generate-gold-qfq-history":
        report = generate_stk_mins_qfq_history(
            lake_root=Path(args.lake_root),
            duckdb_resource=DuckDBResource(),
            registered_partition_keys=registered_stk_mins_silver_partition_keys(),
            partition_keys=parse_optional_partition_keys(args.partition_keys),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=parse_optional_csv_values(args.freqs),
            years=parse_optional_csv_values(args.years),
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
            registered_partition_keys=registered_stk_mins_silver_partition_keys(),
            partition_keys=parse_optional_partition_keys(args.partition_keys),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=parse_optional_csv_values(args.freqs),
            years=parse_optional_csv_values(args.years),
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
            registered_partition_keys=registered_stk_mins_silver_partition_keys(),
            partition_keys=parse_optional_partition_keys(args.partition_keys),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=parse_optional_csv_values(args.freqs),
            years=parse_optional_csv_values(args.years),
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
            registered_partition_keys=registered_stk_mins_silver_partition_keys(),
            partition_keys=parse_optional_partition_keys(args.partition_keys),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=parse_optional_csv_values(args.freqs),
            years=parse_optional_csv_values(args.years),
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


if __name__ == "__main__":
    main()
