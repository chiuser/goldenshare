from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, parse_freqs, print_json, settings_from_args
from lake_console.backend.app.services.duckdb_compute_audit_service import DuckDbComputeAuditService
from lake_console.backend.app.services.duckdb_compute_executor_service import DuckDbComputeExecutorService
from lake_console.backend.app.services.duckdb_compute_plan_service import DuckDbComputePlanService
from lake_console.backend.app.services.duckdb_compute_prewrite_backup_service import DuckDbComputePrewriteBackupService
from lake_console.backend.app.services.duckdb_compute_publish_service import DuckDbComputePublishService
from lake_console.backend.app.services.duckdb_compute_readiness_service import DuckDbComputeReadinessService
from lake_console.backend.app.services.duckdb_compute_run_lifecycle_service import DuckDbComputeRunLifecycleService


def register_compute_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    readiness_parser = subparsers.add_parser(
        "readiness-stk-mins-qfq",
        help="M4-1 只读检查真实 Lake 是否具备生成 stk_mins qfq candidate 的前置条件",
    )
    add_lake_root_arg(readiness_parser)
    readiness_parser.add_argument("--start-date", required=True, help="起始交易日，格式 YYYY-MM-DD")
    readiness_parser.add_argument("--end-date", required=True, help="结束交易日，格式 YYYY-MM-DD")
    readiness_parser.add_argument("--freq", default=None, type=int, help="单个分钟频率")
    readiness_parser.add_argument("--freqs", default=None, help="多个分钟频率，逗号分隔；默认使用 --freq 或全频率")
    readiness_parser.set_defaults(handler=_handle_readiness_stk_mins_qfq)

    abandon_parser = subparsers.add_parser(
        "abandon-stk-mins-qfq-run",
        help="废弃尚未进入正式发布阶段的 stk_mins qfq run；不删除数据，不修改正式分区",
    )
    add_lake_root_arg(abandon_parser)
    abandon_parser.add_argument("--run-id", required=True, help="需要废弃的 run_id")
    abandon_parser.add_argument("--reason", required=True, help="废弃原因，会写入 run manifest 事件")
    abandon_parser.set_defaults(handler=_handle_abandon_stk_mins_qfq_run)

    parser = subparsers.add_parser("plan-stk-mins-qfq", help="只读生成 stk_mins qfq 大计算 dry-run plan")
    add_lake_root_arg(parser)
    parser.add_argument("--start-date", required=True, help="起始交易日，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="结束交易日，格式 YYYY-MM-DD")
    parser.add_argument("--freq", default=None, type=int, help="单个分钟频率")
    parser.add_argument("--freqs", default=None, help="多个分钟频率，逗号分隔；默认使用 --freq 或全频率")
    parser.set_defaults(handler=_handle_plan_stk_mins_qfq)

    prepare_parser = subparsers.add_parser(
        "prepare-stk-mins-qfq-run",
        help="持锁写入 stk_mins qfq run manifest；不执行 DuckDB candidate 计算，不发布正式分区",
    )
    add_lake_root_arg(prepare_parser)
    prepare_parser.add_argument("--start-date", required=True, help="起始交易日，格式 YYYY-MM-DD")
    prepare_parser.add_argument("--end-date", required=True, help="结束交易日，格式 YYYY-MM-DD")
    prepare_parser.add_argument("--freq", default=None, type=int, help="单个分钟频率")
    prepare_parser.add_argument("--freqs", default=None, help="多个分钟频率，逗号分隔；默认使用 --freq 或全频率")
    prepare_parser.set_defaults(handler=_handle_prepare_stk_mins_qfq_run)

    compute_parser = subparsers.add_parser(
        "compute-stk-mins-qfq-candidates",
        help="执行已准备好的 stk_mins qfq run，只写 _tmp candidate_parts，不发布正式分区",
    )
    add_lake_root_arg(compute_parser)
    compute_parser.add_argument("--run-id", required=True, help="prepare-stk-mins-qfq-run 生成的 run_id")
    compute_parser.set_defaults(handler=_handle_compute_stk_mins_qfq_candidates)

    audit_parser = subparsers.add_parser(
        "audit-stk-mins-qfq-candidates",
        help="汇总并审计 stk_mins qfq candidate_parts；只写 audit ledger 和 publish manifest，不发布正式分区",
    )
    add_lake_root_arg(audit_parser)
    audit_parser.add_argument("--run-id", required=True, help="compute-stk-mins-qfq-candidates 完成后的 run_id")
    audit_parser.set_defaults(handler=_handle_audit_stk_mins_qfq_candidates)

    backup_parser = subparsers.add_parser(
        "backup-stk-mins-qfq-prewrite",
        help="为已通过审计的 stk_mins qfq run 创建 Kopia 写前备份；不发布正式分区",
    )
    add_lake_root_arg(backup_parser)
    backup_parser.add_argument("--run-id", required=True, help="audit-stk-mins-qfq-candidates 通过后的 run_id")
    backup_parser.set_defaults(handler=_handle_backup_stk_mins_qfq_prewrite)

    preflight_parser = subparsers.add_parser(
        "preflight-stk-mins-qfq-publish",
        help="M3-C-A 只读校验 stk_mins qfq 正式发布计划；不替换正式分区、不写 gate、不写 queue",
    )
    add_lake_root_arg(preflight_parser)
    preflight_parser.add_argument("--run-id", required=True, help="backup-stk-mins-qfq-prewrite 完成后的 run_id")
    preflight_parser.set_defaults(handler=_handle_preflight_stk_mins_qfq_publish)

    gate_plan_parser = subparsers.add_parser(
        "prepare-stk-mins-qfq-gate-publish-plan",
        help="M3-C-B 持锁写入 gate publishing 计划；不替换正式分区、不写正式 gate",
    )
    add_lake_root_arg(gate_plan_parser)
    gate_plan_parser.add_argument("--run-id", required=True, help="preflight-stk-mins-qfq-publish 通过后的 run_id")
    gate_plan_parser.set_defaults(handler=_handle_prepare_stk_mins_qfq_gate_publish_plan)

    gate_publish_parser = subparsers.add_parser(
        "stage-stk-mins-qfq-gate-publishing",
        help="M3-C-C 写正式 clean_next gate=publishing；不替换正式分区、不写 downstream、不 gate passed",
    )
    add_lake_root_arg(gate_publish_parser)
    gate_publish_parser.add_argument("--run-id", required=True, help="prepare-stk-mins-qfq-gate-publish-plan 通过后的 run_id")
    gate_publish_parser.set_defaults(handler=_handle_stage_stk_mins_qfq_gate_publishing)

    formal_publish_parser = subparsers.add_parser(
        "publish-stk-mins-qfq-formal",
        help="M3-C-D 原子替换正式 clean_next 分区并执行 formal audit；不写 downstream、不 gate passed",
    )
    add_lake_root_arg(formal_publish_parser)
    formal_publish_parser.add_argument("--run-id", required=True, help="stage-stk-mins-qfq-gate-publishing 通过后的 run_id")
    formal_publish_parser.set_defaults(handler=_handle_publish_stk_mins_qfq_formal)

    finalize_parser = subparsers.add_parser(
        "finalize-stk-mins-qfq-publish",
        help="M3-C-E 写 downstream requirement / indicator queue，最后把 clean_next gate 改为 passed",
    )
    add_lake_root_arg(finalize_parser)
    finalize_parser.add_argument("--run-id", required=True, help="publish-stk-mins-qfq-formal 通过后的 run_id")
    finalize_parser.set_defaults(handler=_handle_finalize_stk_mins_qfq_publish)


def _handle_readiness_stk_mins_qfq(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    freqs = parse_freqs(args.freqs, fallback=args.freq)
    summary = DuckDbComputeReadinessService(settings=settings).scan_stk_mins_qfq_readiness(
        start_date=args.start_date,
        end_date=args.end_date,
        freqs=freqs,
    )
    print_json(summary)
    return 0 if summary["ready"] else 2


def _handle_abandon_stk_mins_qfq_run(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = DuckDbComputeRunLifecycleService(settings=settings).abandon_stk_mins_qfq_run(
        run_id=args.run_id,
        reason=args.reason,
    )
    print_json(summary)
    return 0 if summary["status"] == "abandoned" else 2


def _handle_plan_stk_mins_qfq(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    freqs = parse_freqs(args.freqs, fallback=args.freq)
    summary = DuckDbComputePlanService(settings=settings).plan_stk_mins_qfq(
        start_date=args.start_date,
        end_date=args.end_date,
        freqs=freqs,
    )
    print_json(summary)
    return 0


def _handle_prepare_stk_mins_qfq_run(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    freqs = parse_freqs(args.freqs, fallback=args.freq)
    summary = DuckDbComputePlanService(settings=settings).prepare_stk_mins_qfq_run(
        start_date=args.start_date,
        end_date=args.end_date,
        freqs=freqs,
    )
    print_json(summary)
    return 0


def _handle_compute_stk_mins_qfq_candidates(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = DuckDbComputeExecutorService(settings=settings).compute_stk_mins_qfq_candidates(
        run_id=args.run_id,
        progress_callback=_print_compute_progress,
    )
    print_json(summary)
    return 0


def _handle_audit_stk_mins_qfq_candidates(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = DuckDbComputeAuditService(settings=settings).audit_stk_mins_qfq_candidates(
        run_id=args.run_id,
        progress_callback=_print_audit_progress,
    )
    print_json(summary)
    return 0


def _handle_backup_stk_mins_qfq_prewrite(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = DuckDbComputePrewriteBackupService(settings=settings).backup_stk_mins_qfq_prewrite(
        run_id=args.run_id,
        progress_callback=_print_backup_progress,
    )
    print_json(summary)
    return 0


def _handle_preflight_stk_mins_qfq_publish(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = DuckDbComputePublishService(settings=settings).preflight_stk_mins_qfq_publish(
        run_id=args.run_id,
        progress_callback=_print_publish_preflight_progress,
    )
    print_json(summary)
    return 0


def _handle_prepare_stk_mins_qfq_gate_publish_plan(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = DuckDbComputePublishService(settings=settings).prepare_stk_mins_qfq_gate_publish_plan(
        run_id=args.run_id,
        progress_callback=_print_gate_publish_plan_progress,
    )
    print_json(summary)
    return 0


def _handle_stage_stk_mins_qfq_gate_publishing(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = DuckDbComputePublishService(settings=settings).stage_stk_mins_qfq_gate_publishing(
        run_id=args.run_id,
        progress_callback=_print_gate_publishing_progress,
    )
    print_json(summary)
    return 0


def _handle_publish_stk_mins_qfq_formal(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = DuckDbComputePublishService(settings=settings).stage_stk_mins_qfq_formal_replace_and_audit(
        run_id=args.run_id,
        progress_callback=_print_formal_publish_progress,
    )
    print_json(summary)
    return 0


def _handle_finalize_stk_mins_qfq_publish(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = DuckDbComputePublishService(settings=settings).stage_stk_mins_qfq_downstream_and_gate_passed(
        run_id=args.run_id,
        progress_callback=_print_finalize_publish_progress,
    )
    print_json(summary)
    return 0


def _print_compute_progress(event: dict[str, object]) -> None:
    if event.get("event") == "unit_started":
        print(
            "[duckdb_compute] "
            f"unit={event.get('unit_index')}/{event.get('unit_count')} "
            f"{event.get('unit_key')}"
        )
        return
    if event.get("event") == "unit_succeeded":
        print(
            "[duckdb_compute] "
            f"unit_done={event.get('unit_index')}/{event.get('unit_count')} "
            f"{event.get('unit_key')} rows={event.get('row_count')}"
        )


def _print_audit_progress(event: dict[str, object]) -> None:
    if event.get("event") == "partition_audit_started":
        print(
            "[duckdb_compute] "
            f"audit={event.get('partition_index')}/{event.get('partition_count')} "
            f"{event.get('partition_key')}"
        )
        return
    if event.get("event") == "partition_audit_finished":
        print(
            "[duckdb_compute] "
            f"audit_done={event.get('partition_index')}/{event.get('partition_count')} "
            f"{event.get('partition_key')} issues={event.get('issue_count')}"
        )


def _print_backup_progress(event: dict[str, object]) -> None:
    if event.get("event") == "prewrite_backup_started":
        print(f"[duckdb_compute] prewrite_backup_start run_id={event.get('run_id')}")
        return
    if event.get("event") == "prewrite_backup_completed":
        print(
            "[duckdb_compute] "
            f"prewrite_backup_done run_id={event.get('run_id')} "
            f"snapshots={event.get('snapshot_count')}"
        )


def _print_publish_preflight_progress(event: dict[str, object]) -> None:
    if event.get("event") == "publish_partition_preflight":
        print(
            "[duckdb_compute] "
            f"publish_preflight={event.get('partition_index')}/{event.get('partition_count')} "
            f"{event.get('partition_key')}"
        )


def _print_gate_publish_plan_progress(event: dict[str, object]) -> None:
    if event.get("event") == "gate_publish_plan_started":
        print(f"[duckdb_compute] gate_publish_plan_start run_id={event.get('run_id')}")
        return
    if event.get("event") == "publish_partition_preflight":
        print(
            "[duckdb_compute] "
            f"gate_publish_plan_preflight={event.get('partition_index')}/{event.get('partition_count')} "
            f"{event.get('partition_key')}"
        )
        return
    if event.get("event") == "gate_publish_plan_completed":
        print(
            "[duckdb_compute] "
            f"gate_publish_plan_done run_id={event.get('run_id')} "
            f"planned_gates={event.get('planned_gate_row_count')}"
        )


def _print_gate_publishing_progress(event: dict[str, object]) -> None:
    if event.get("event") == "formal_gate_publishing_started":
        print(f"[duckdb_compute] gate_publishing_start run_id={event.get('run_id')}")
        return
    if event.get("event") == "formal_gate_publishing_completed":
        print(
            "[duckdb_compute] "
            f"gate_publishing_done run_id={event.get('run_id')} "
            f"updated_gates={event.get('updated_gate_partitions')}"
        )


def _print_formal_publish_progress(event: dict[str, object]) -> None:
    if event.get("event") == "formal_replace_started":
        print(f"[duckdb_compute] formal_publish_start run_id={event.get('run_id')}")
        return
    if event.get("event") == "formal_partition_replace_finished":
        print(
            "[duckdb_compute] "
            f"formal_publish={event.get('partition_index')}/{event.get('partition_count')} "
            f"{event.get('partition_key')} target={event.get('target_path')}"
        )


def _print_finalize_publish_progress(event: dict[str, object]) -> None:
    if event.get("event") == "downstream_notification_started":
        print(f"[duckdb_compute] finalize_start run_id={event.get('run_id')}")
