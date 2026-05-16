from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, parse_freqs, print_json, settings_from_args
from lake_console.backend.app.services.duckdb_compute_plan_service import DuckDbComputePlanService


def register_compute_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
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
