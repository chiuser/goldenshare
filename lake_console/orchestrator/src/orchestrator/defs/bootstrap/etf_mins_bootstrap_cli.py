"""CLI for the approved ETF minute Direct Lake Bootstrap stages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.etf_mins import EtfMinsRawWriteError
from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    EtfMinsBootstrapError,
    apply_etf_mins_bootstrap_events,
    apply_etf_mins_bootstrap_raw,
    apply_etf_mins_bootstrap_silver,
    audit_etf_mins_bootstrap_events,
    plan_etf_mins_bootstrap_events,
    plan_etf_mins_bootstrap_partitions,
    register_etf_mins_bootstrap_partitions,
    run_etf_mins_bootstrap_plan,
    validate_etf_mins_bootstrap_operation_path,
)
from orchestrator.defs.bootstrap.etf_mins_raw_decision import (
    decide_etf_mins_raw,
)
from orchestrator.defs.bootstrap.etf_mins_raw_observation import (
    observe_etf_mins_raw,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "ETF 分钟 Direct Lake Bootstrap"
            "（plan/raw-apply/raw-observe/raw-decide/silver-apply/partitions/events）"
        )
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    plan_parser = subcommands.add_parser(
        "plan",
        help="只读冻结 Basic、水位、范围、预算和目标状态",
    )
    plan_parser.add_argument("--start-date", required=True)
    plan_parser.add_argument("--end-date", required=True)
    plan_parser.add_argument("--report-path", required=True, type=Path)
    plan_parser.add_argument("--protect-from-date")

    raw_apply_parser = subcommands.add_parser(
        "raw-apply",
        help="按冻结计划串行写入或等价复用 Raw",
    )
    raw_apply_parser.add_argument("--plan-path", required=True, type=Path)
    raw_apply_parser.add_argument("--checkpoint-path", required=True, type=Path)
    raw_apply_parser.add_argument(
        "--raw-final-report-path",
        required=True,
        type=Path,
    )
    raw_apply_parser.add_argument(
        "--confirm-raw-lake-write",
        required=True,
        action="store_true",
    )
    raw_observe_parser = subcommands.add_parser(
        "raw-observe",
        help="只读已完成的本地 Raw，输出 N3A 事实、问题和规则建议",
    )
    raw_observe_parser.add_argument(
        "--raw-final-report-path",
        required=True,
        type=Path,
    )
    raw_observe_parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
    )
    raw_decide_parser = subcommands.add_parser(
        "raw-decide",
        help="只读 N3A 产物，按已登记 policy 生成 N3B 分区决策",
    )
    raw_decide_parser.add_argument(
        "--observation-summary-path",
        required=True,
        type=Path,
    )
    raw_decide_parser.add_argument(
        "--approved-policy-version",
        required=True,
    )
    raw_decide_parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
    )
    silver_apply_parser = subcommands.add_parser(
        "silver-apply",
        help="只消费已批准的 N3 decision，写入或等价复用 Silver",
    )
    silver_apply_parser.add_argument(
        "--raw-decision-summary-path",
        required=True,
        type=Path,
    )
    silver_apply_parser.add_argument(
        "--decision-manifest-path",
        required=True,
        type=Path,
    )
    silver_apply_parser.add_argument(
        "--checkpoint-path",
        required=True,
        type=Path,
    )
    silver_apply_parser.add_argument(
        "--final-report-path",
        required=True,
        type=Path,
    )
    silver_apply_parser.add_argument(
        "--confirm-silver-lake-write",
        required=True,
        action="store_true",
    )
    partitions_parser = subcommands.add_parser(
        "partitions",
        help="只读计划或显式确认注册已验收范围的动态分区",
    )
    partitions_parser.add_argument(
        "--final-report-path",
        required=True,
        type=Path,
    )
    partitions_parser.add_argument(
        "--confirm-partition-write",
        action="store_true",
    )
    events_parser = subcommands.add_parser(
        "events",
        help="只读计划、显式补录或 post-audit 已验收的 Runless events",
    )
    events_parser.add_argument(
        "--final-report-path",
        required=True,
        type=Path,
    )
    events_mode = events_parser.add_mutually_exclusive_group()
    events_mode.add_argument("--confirm-event-write", action="store_true")
    events_mode.add_argument("--post-audit", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    lake_root = Path(DEFAULT_LAKE_ROOT)
    staging_root = Path(DEFAULT_LAKE_STAGING_ROOT)
    duckdb = DuckDBResource()
    try:
        if args.command == "plan":
            prod_postgres = ProdPostgresResource()
            with dg.DagsterInstance.get() as instance:
                result = run_etf_mins_bootstrap_plan(
                    instance=instance,
                    lake_root=lake_root,
                    staging_root=staging_root,
                    duckdb=duckdb,
                    prod_postgres=prod_postgres,
                    requested_start_date=args.start_date,
                    requested_end_date=args.end_date,
                    report_path=args.report_path,
                    protect_from_date=args.protect_from_date,
                )
            payload: dict[str, object] = result.to_dict()
        elif args.command == "raw-apply":
            prod_postgres = ProdPostgresResource()
            report = apply_etf_mins_bootstrap_raw(
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb=duckdb,
                prod_postgres=prod_postgres,
                plan_path=args.plan_path,
                checkpoint_path=args.checkpoint_path,
                raw_final_report_path=args.raw_final_report_path,
                confirm_raw_lake_write=args.confirm_raw_lake_write,
            )
            payload = {
                "operation_id": report.operation_id,
                "plan_fingerprint": report.plan_fingerprint,
                "plan_path": str(report.plan_path),
                "checkpoint_path": str(report.checkpoint_path),
                "finalized_raw_manifest_path": str(report.finalized_raw_manifest_path),
                "finalized_raw_manifest_hash": report.finalized_raw_manifest_hash,
                "raw_final_report_path": str(report.raw_final_report_path),
                "source_row_count": report.source_row_count,
                "formal_raw_row_count": report.formal_raw_row_count,
                "added_file_count": report.added_file_count,
                "reused_file_count": report.reused_file_count,
                "zero_row_file_count": report.zero_row_file_count,
                "actual_remote_query_count": report.actual_remote_query_count,
                "temporary_space_peak_bytes": report.temporary_space_peak_bytes,
                "final_space_increment_bytes": report.final_space_increment_bytes,
                "report_hash": report.report_hash,
            }
        elif args.command == "raw-observe":
            _, operation_id = validate_etf_mins_bootstrap_operation_path(
                args.raw_final_report_path,
                staging_root=staging_root,
            )
            validate_etf_mins_bootstrap_operation_path(
                args.output_dir / "raw_observation_summary.json",
                staging_root=staging_root,
                expected_operation_id=operation_id,
            )
            observation = observe_etf_mins_raw(
                lake_root=lake_root,
                duckdb=duckdb,
                raw_bootstrap_report_path=args.raw_final_report_path,
                output_dir=args.output_dir,
            )
            payload = {
                "operation_id": observation.operation_id,
                "output_dir": str(observation.output_dir),
                "raw_observation_summary_path": str(
                    observation.raw_observation_summary_path
                ),
                "proposed_policy_path": str(observation.proposed_policy_path),
                "input_manifest_hash": observation.input_manifest_hash,
                "observation_summary_hash": observation.observation_summary_hash,
                "proposed_policy_hash": observation.proposed_policy_hash,
                "scanned_file_count": observation.scanned_file_count,
                "scanned_row_count": observation.scanned_row_count,
                "scanned_byte_count": observation.scanned_byte_count,
                "issue_row_count": observation.issue_row_count,
                "raw_scan_query_count": observation.raw_scan_query_count,
                "analysis_sql_statement_count": (
                    observation.analysis_sql_statement_count
                ),
                "peak_temp_dir_size_bytes": observation.peak_temp_dir_size_bytes,
                "elapsed_seconds": observation.elapsed_seconds,
            }
        elif args.command == "raw-decide":
            operation_root, operation_id = validate_etf_mins_bootstrap_operation_path(
                args.observation_summary_path,
                staging_root=staging_root,
            )
            validate_etf_mins_bootstrap_operation_path(
                args.output_dir / "raw_decision_summary.json",
                staging_root=staging_root,
                expected_operation_id=operation_id,
            )
            if args.output_dir.resolve(strict=False) != operation_root.resolve(
                strict=False
            ):
                raise EtfMinsBootstrapError(
                    "etf_mins_raw_decision_output_path_invalid."
                )
            decision = decide_etf_mins_raw(
                observation_summary_path=args.observation_summary_path,
                approved_policy_version=args.approved_policy_version,
                output_dir=args.output_dir,
            )
            payload = {
                "operation_id": decision.operation_id,
                "output_dir": str(decision.output_dir),
                "raw_partition_decision_manifest_path": str(
                    decision.raw_partition_decision_manifest_path
                ),
                "raw_decision_summary_path": str(decision.raw_decision_summary_path),
                "observation_summary_hash": decision.observation_summary_hash,
                "approved_policy_version": decision.approved_policy_version,
                "approved_policy_hash": decision.approved_policy_hash,
                "raw_partition_decision_manifest_hash": (
                    decision.raw_partition_decision_manifest_hash
                ),
                "raw_decision_summary_hash": decision.raw_decision_summary_hash,
                "partition_count": decision.partition_count,
                "green_partition_count": decision.green_partition_count,
                "warn_partition_count": decision.warn_partition_count,
                "blocked_partition_count": decision.blocked_partition_count,
                "silver_eligible_partition_count": (
                    decision.silver_eligible_partition_count
                ),
                "analysis_sql_statement_count": (decision.analysis_sql_statement_count),
                "elapsed_seconds": decision.elapsed_seconds,
            }
        elif args.command == "silver-apply":
            report = apply_etf_mins_bootstrap_silver(
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb=duckdb,
                raw_decision_summary_path=args.raw_decision_summary_path,
                decision_manifest_path=args.decision_manifest_path,
                checkpoint_path=args.checkpoint_path,
                final_report_path=args.final_report_path,
                confirm_silver_lake_write=args.confirm_silver_lake_write,
            )
            payload = {
                "operation_id": report.operation_id,
                "plan_fingerprint": report.plan_fingerprint,
                "silver_work_manifest_path": str(report.silver_work_manifest_path),
                "silver_work_manifest_hash": report.silver_work_manifest_hash,
                "finalized_silver_manifest_path": str(
                    report.finalized_silver_manifest_path
                ),
                "finalized_silver_manifest_hash": (
                    report.finalized_silver_manifest_hash
                ),
                "checkpoint_path": str(report.checkpoint_path),
                "final_report_path": str(report.final_report_path),
                "raw_file_count": report.raw_file_count,
                "raw_row_count": report.raw_row_count,
                "silver_file_count": report.silver_file_count,
                "silver_row_count": report.silver_row_count,
                "added_file_count": report.added_file_count,
                "reused_file_count": report.reused_file_count,
                "blocked_partition_count": report.blocked_partition_count,
                "warn_partition_count": report.warn_partition_count,
                "report_hash": report.report_hash,
            }
        elif args.command == "partitions":
            with dg.DagsterInstance.get() as instance:
                if args.confirm_partition_write:
                    partition_report = register_etf_mins_bootstrap_partitions(
                        instance=instance,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        duckdb=duckdb,
                        final_report_path=args.final_report_path,
                        confirm_partition_write=True,
                    )
                else:
                    partition_report = plan_etf_mins_bootstrap_partitions(
                        instance=instance,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        duckdb=duckdb,
                        final_report_path=args.final_report_path,
                    )
            payload = partition_report.to_dict()
        elif args.command == "events":
            with dg.DagsterInstance.get() as instance:
                if args.post_audit:
                    event_report = audit_etf_mins_bootstrap_events(
                        instance=instance,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        duckdb=duckdb,
                        final_report_path=args.final_report_path,
                    )
                elif args.confirm_event_write:
                    event_report = apply_etf_mins_bootstrap_events(
                        instance=instance,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        duckdb=duckdb,
                        final_report_path=args.final_report_path,
                        confirm_event_write=True,
                    )
                else:
                    event_report = plan_etf_mins_bootstrap_events(
                        instance=instance,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        duckdb=duckdb,
                        final_report_path=args.final_report_path,
                    )
            payload = event_report.to_dict()
        else:  # pragma: no cover - argparse rejects unknown commands.
            raise AssertionError(f"Unsupported command: {args.command}")
    except (EtfMinsBootstrapError, EtfMinsRawWriteError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
