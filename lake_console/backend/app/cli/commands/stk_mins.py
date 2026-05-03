from __future__ import annotations

import argparse
from datetime import date

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, parse_freqs, parse_int_csv, print_json, settings_from_args
from lake_console.backend.app.cli.progress import StkMinsTerminalProgress
from lake_console.backend.app.services.stk_mins_derived_service import StkMinsDerivedService
from lake_console.backend.app.services.stk_mins_research_service import StkMinsResearchService
from lake_console.backend.app.services.tushare_client import TushareLakeClient
from lake_console.backend.app.services.tushare_stk_mins_sync_service import DEFAULT_PART_ROWS, TushareStkMinsSyncService


def register_stk_mins_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    mins_parser = subparsers.add_parser("sync-stk-mins", help="从 Tushare 拉取单股票单日分钟线并写入 by_date 分区")
    add_lake_root_arg(mins_parser)
    mins_parser.add_argument("--ts-code", default=None, help="股票代码，例如 000001.SZ；单股票模式必填")
    mins_parser.add_argument("--freq", default=None, type=int, choices=(1, 5, 15, 30, 60), help="单个分钟周期")
    mins_parser.add_argument("--freqs", default=None, help="多个分钟周期，逗号分隔，例如 1,5,15,30,60；全市场模式可用")
    mins_parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="交易日，格式 YYYY-MM-DD")
    mins_parser.add_argument("--all-market", action="store_true", help="从本地 stock_basic 股票池读取全市场 ts_code 并扇出请求")
    mins_parser.add_argument("--part-rows", default=DEFAULT_PART_ROWS, type=int, help="全市场模式下每个 Parquet part 的最大行数")
    mins_parser.set_defaults(handler=_handle_sync_stk_mins)

    range_parser = subparsers.add_parser("sync-stk-mins-range", help="按本地交易日历拉取区间内分钟线行情")
    add_lake_root_arg(range_parser)
    range_parser.add_argument("--start-date", required=True, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD")
    range_parser.add_argument("--end-date", required=True, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD")
    range_parser.add_argument("--all-market", action="store_true", help="从本地 stock_basic 股票池读取全市场 ts_code 并扇出请求")
    range_parser.add_argument("--ts-code", default=None, help="股票代码，例如 000001.SZ；单股票模式必填")
    range_parser.add_argument("--freq", default=None, type=int, choices=(1, 5, 15, 30, 60), help="单个分钟周期")
    range_parser.add_argument("--freqs", default=None, help="多个分钟周期，逗号分隔，例如 1,5,15,30,60；全市场模式可用")
    range_parser.add_argument("--part-rows", default=DEFAULT_PART_ROWS, type=int, help="全市场模式下每个 Parquet part 的最大行数")
    range_parser.set_defaults(handler=_handle_sync_stk_mins_range)

    derive_parser = subparsers.add_parser("derive-stk-mins", help="从 30/60 分钟线派生 90/120 分钟线")
    add_lake_root_arg(derive_parser)
    derive_parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="交易日，格式 YYYY-MM-DD")
    derive_parser.add_argument("--targets", default="90,120", help="派生目标，逗号分隔，当前支持 90,120")
    derive_parser.set_defaults(handler=_handle_derive_stk_mins)

    research_parser = subparsers.add_parser("rebuild-stk-mins-research", help="把 by_date 分区重排为 by_symbol_month research 层")
    add_lake_root_arg(research_parser)
    research_parser.add_argument("--freq", required=True, type=int, choices=(1, 5, 15, 30, 60, 90, 120), help="分钟周期")
    research_parser.add_argument("--trade-month", required=True, help="月份，格式 YYYY-MM")
    research_parser.add_argument("--bucket-count", default=None, type=int, help="bucket 数量，默认读取配置 bucket_count")
    research_parser.set_defaults(handler=_handle_rebuild_stk_mins_research)


def _handle_sync_stk_mins(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    service = TushareStkMinsSyncService(
        lake_root=settings.lake_root,
        client=TushareLakeClient(
            settings.tushare_token,
            request_limit_per_minute=settings.tushare_request_limit_per_minute,
        ),
    )
    if args.all_market:
        freqs = parse_freqs(args.freqs, fallback=args.freq)
        summary = service.sync_market_day(freqs=freqs, trade_date=args.trade_date, part_rows=args.part_rows)
    else:
        if not args.ts_code:
            raise SystemExit("单股票模式必须传 --ts-code；全市场请传 --all-market。")
        if args.freq is None:
            raise SystemExit("单股票模式必须传 --freq。")
        summary = service.sync_single_symbol_day(ts_code=args.ts_code, freq=args.freq, trade_date=args.trade_date)
    print_json(summary)
    return 0


def _handle_sync_stk_mins_range(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    progress = StkMinsTerminalProgress() if args.all_market else None
    service = TushareStkMinsSyncService(
        lake_root=settings.lake_root,
        client=TushareLakeClient(
            settings.tushare_token,
            request_limit_per_minute=settings.tushare_request_limit_per_minute,
        ),
        progress=progress,
    )
    try:
        if args.all_market:
            freqs = parse_freqs(args.freqs, fallback=args.freq)
            summary = service.sync_range(
                start_date=args.start_date,
                end_date=args.end_date,
                freqs=freqs,
                all_market=True,
                part_rows=args.part_rows,
            )
        else:
            if not args.ts_code:
                raise SystemExit("单股票区间模式必须传 --ts-code；全市场请传 --all-market。")
            if args.freq is None:
                raise SystemExit("单股票区间模式必须传 --freq。")
            summary = service.sync_range(
                start_date=args.start_date,
                end_date=args.end_date,
                freqs=[],
                all_market=False,
                ts_code=args.ts_code,
                freq=args.freq,
                part_rows=args.part_rows,
            )
    finally:
        if progress:
            progress.finish()
    print_json(summary)
    return 0


def _handle_derive_stk_mins(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    targets = parse_int_csv(args.targets, allowed={90, 120}, label="targets")
    summary = StkMinsDerivedService(lake_root=settings.lake_root).derive_day(trade_date=args.trade_date, targets=targets)
    print_json(summary)
    return 0


def _handle_rebuild_stk_mins_research(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    bucket_count = args.bucket_count or settings.bucket_count
    summary = StkMinsResearchService(lake_root=settings.lake_root, bucket_count=bucket_count).rebuild_month(
        freq=args.freq,
        trade_month=args.trade_month,
    )
    print_json(summary)
    return 0
