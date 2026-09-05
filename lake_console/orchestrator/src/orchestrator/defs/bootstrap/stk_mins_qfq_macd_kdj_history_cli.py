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
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_macd_kdj_baseline_events import (
    audit_stk_mins_qfq_macd_kdj_final_state,
    report_stk_mins_qfq_macd_kdj_baseline_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_macd_kdj_history import (
    audit_stk_mins_qfq_macd_kdj_files,
    generate_stk_mins_qfq_macd_kdj_history,
    plan_stk_mins_qfq_macd_kdj_history,
    rebuild_stk_mins_qfq_macd_kdj_history,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="stk mins qfq macd kdj history helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_gold_qfq_macd_kdj = subparsers.add_parser(
        "plan-gold-stk-mins-qfq-macd-kdj-history"
    )
    plan_gold_qfq_macd_kdj.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    add_history_selection_arguments(
        plan_gold_qfq_macd_kdj, default_start_date=STK_MINS_QFQ_HISTORY_START_DATE
    )
    generate_gold_qfq_macd_kdj = subparsers.add_parser(
        "generate-gold-stk-mins-qfq-macd-kdj-history"
    )
    generate_gold_qfq_macd_kdj.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    add_history_selection_arguments(
        generate_gold_qfq_macd_kdj, default_start_date=STK_MINS_QFQ_HISTORY_START_DATE
    )
    rebuild_gold_qfq_macd_kdj = subparsers.add_parser(
        "rebuild-gold-stk-mins-qfq-macd-kdj-history"
    )
    rebuild_gold_qfq_macd_kdj.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    rebuild_gold_qfq_macd_kdj.add_argument("--checkpoint", required=True)
    rebuild_gold_qfq_macd_kdj.add_argument("--stock-codes")
    rebuild_gold_qfq_macd_kdj.add_argument("--confirm-rebuild", action="store_true")
    add_history_selection_arguments(
        rebuild_gold_qfq_macd_kdj, default_start_date=STK_MINS_QFQ_HISTORY_START_DATE
    )
    audit_gold_qfq_macd_kdj_files = subparsers.add_parser(
        "audit-gold-stk-mins-qfq-macd-kdj-files"
    )
    audit_gold_qfq_macd_kdj_files.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    add_history_selection_arguments(
        audit_gold_qfq_macd_kdj_files,
        default_start_date=STK_MINS_QFQ_HISTORY_START_DATE,
    )
    report_gold_qfq_macd_kdj_baseline_events = subparsers.add_parser(
        "report-gold-stk-mins-qfq-macd-kdj-baseline-events"
    )
    report_gold_qfq_macd_kdj_baseline_events.add_argument(
        "--lake-root", default=DEFAULT_LAKE_ROOT
    )
    add_history_selection_arguments(
        report_gold_qfq_macd_kdj_baseline_events,
        default_start_date=STK_MINS_QFQ_HISTORY_START_DATE,
    )
    report_gold_qfq_macd_kdj_baseline_events.add_argument(
        "--dry-run", action="store_true"
    )
    report_gold_qfq_macd_kdj_baseline_events.add_argument(
        "--skip-existing-ready", action="store_true"
    )
    audit_gold_qfq_macd_kdj_final = subparsers.add_parser(
        "audit-gold-stk-mins-qfq-macd-kdj-final"
    )
    audit_gold_qfq_macd_kdj_final.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    add_history_selection_arguments(
        audit_gold_qfq_macd_kdj_final,
        default_start_date=STK_MINS_QFQ_HISTORY_START_DATE,
    )
    audit_gold_qfq_macd_kdj_final.add_argument(
        "--mode", choices=("full", "quick"), default="full"
    )
    args = parser.parse_args(argv)
    if args.command == "plan-gold-stk-mins-qfq-macd-kdj-history":
        report = plan_stk_mins_qfq_macd_kdj_history(
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
                "planned_source_file_count": report.planned_source_file_count,
                "planned_source_row_count": report.planned_source_row_count,
                "planned_indicator_file_count": report.planned_indicator_file_count,
                "existing_indicator_file_count": report.existing_indicator_file_count,
                "planned_state_file_count": report.planned_state_file_count,
                "existing_state_file_count": report.existing_state_file_count,
                "planned_target_file_count": report.planned_target_file_count,
                "existing_target_file_count": report.existing_target_file_count,
                "missing_input_count": report.missing_input_count,
                "missing_input_samples": list(report.missing_input_samples),
                "planned_event_count": report.planned_event_count,
            }
        )
    elif args.command == "generate-gold-stk-mins-qfq-macd-kdj-history":
        report = generate_stk_mins_qfq_macd_kdj_history(
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
    elif args.command == "rebuild-gold-stk-mins-qfq-macd-kdj-history":
        if not args.confirm_rebuild:
            raise ValueError("Pass --confirm-rebuild to rewrite MACD/KDJ history.")
        report = rebuild_stk_mins_qfq_macd_kdj_history(
            checkpoint_path=Path(args.checkpoint),
            lake_root=Path(args.lake_root),
            duckdb_resource=DuckDBResource(),
            registered_partition_keys=registered_stk_mins_silver_partition_keys(),
            partition_keys=parse_optional_partition_keys(args.partition_keys),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=parse_optional_csv_values(args.freqs) or (5, 15, 30, 60),
            years=parse_optional_csv_values(args.years),
            stock_codes=parse_optional_csv_values(args.stock_codes) or (),
        )
        print(
            {
                "plan_fingerprint": report.plan_fingerprint,
                "checkpoint_path": str(report.checkpoint_path),
                "stock_code_count": len(report.stock_codes),
                "resumed_batch_count": report.resumed_batch_count,
                "executed_batch_count": report.executed_batch_count,
            }
        )
    elif args.command == "audit-gold-stk-mins-qfq-macd-kdj-files":
        report = audit_stk_mins_qfq_macd_kdj_files(
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
                "passed": report.passed,
                "selected_partition_count": report.selected_partition_count,
                "selected_freqs": list(report.selected_freqs),
                "selected_years": list(report.selected_years),
                "planned_indicator_file_count": report.planned_indicator_file_count,
                "existing_indicator_file_count": report.existing_indicator_file_count,
                "planned_state_file_count": report.planned_state_file_count,
                "existing_state_file_count": report.existing_state_file_count,
                "source_row_count": report.source_row_count,
                "indicator_row_count": report.indicator_row_count,
                "state_row_count": report.state_row_count,
                "missing_input_count": report.missing_input_count,
                "row_count_mismatch_count": report.row_count_mismatch_count,
            }
        )
    elif args.command == "report-gold-stk-mins-qfq-macd-kdj-baseline-events":
        report = report_stk_mins_qfq_macd_kdj_baseline_events(
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
                "audited_asset_partition_count": len(report.asset_audits),
                "failed_asset_partition_count": report.failed_asset_partition_count,
                "reported_asset_partition_count": len(report.reported_asset_partitions),
                "skipped_ready_asset_partition_count": len(
                    report.skipped_ready_asset_partitions
                ),
                "reported_event_count": report.reported_event_count,
            }
        )
    elif args.command == "audit-gold-stk-mins-qfq-macd-kdj-final":
        report = audit_stk_mins_qfq_macd_kdj_final_state(
            instance=dg.DagsterInstance.get(),
            lake_root=Path(args.lake_root),
            registered_partition_keys=registered_stk_mins_silver_partition_keys(),
            partition_keys=parse_optional_partition_keys(args.partition_keys),
            start_date=args.start_date,
            end_date=args.end_date,
            freqs=parse_optional_csv_values(args.freqs),
            years=parse_optional_csv_values(args.years),
            duckdb_resource=DuckDBResource(),
            include_check_success_counts=args.mode == "full",
        )
        print(
            {
                "audit_mode": args.mode,
                "selected_partition_count": report.selected_partition_count,
                "selected_freqs": list(report.selected_freqs),
                "selected_years": list(report.selected_years),
                "file_audit_passed": report.file_audit_passed,
                "planned_target_file_count": report.planned_target_file_count,
                "existing_target_file_count": report.existing_target_file_count,
                "materialized_partition_counts": dict(
                    report.materialized_partition_counts
                ),
                "check_success_counts_skipped": report.check_success_counts_skipped,
                "check_success_counts": dict(report.check_success_counts),
                "sample_readiness": dict(report.sample_readiness),
            }
        )


if __name__ == "__main__":
    main()
