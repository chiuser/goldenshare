from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, parse_freqs, print_json, settings_from_args
from lake_console.backend.app.services.duckdb_compute_benchmark_service import DuckDbComputeBenchmarkService


def register_benchmark_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("benchmark-duckdb-compute", help="只读跑 DuckDB 大计算样本 benchmark")
    add_lake_root_arg(parser)
    parser.add_argument("--sample-month", default="2026-03", help="样本月份，格式 YYYY-MM，默认 2026-03")
    parser.add_argument("--freq", default=None, type=int, help="单个分钟频率")
    parser.add_argument("--freqs", default=None, help="多个分钟频率，逗号分隔；默认使用 --freq 或 30")
    parser.set_defaults(handler=_handle_benchmark_duckdb_compute)


def _handle_benchmark_duckdb_compute(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    freqs = parse_freqs(args.freqs, fallback=args.freq or 30)
    summary = DuckDbComputeBenchmarkService(settings=settings).run_stk_mins_qfq_sample(
        sample_month=args.sample_month,
        freqs=freqs,
    )
    print_json(summary)
    return 0
