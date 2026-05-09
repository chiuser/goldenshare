from __future__ import annotations

import argparse
from datetime import date

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, print_json, settings_from_args
from lake_console.backend.app.services.indicators import (
    DEFAULT_MACD_PARAMS,
    IndicatorRecalcQueueService,
    StkMinsIndicatorComputeService,
    StkMinsIndicatorResearchService,
)


def register_indicator_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("compute-stk-mins-indicator", help="计算本地 stk_mins 指标，当前支持 MACD")
    add_lake_root_arg(parser)
    parser.add_argument("--indicator", required=True, choices=("macd",), help="指标名，当前支持 macd")
    parser.add_argument("--mode", required=True, choices=("full", "incremental"), help="计算模式")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--ts-code", default=None, help="股票代码，例如 600000.SH")
    scope.add_argument("--all-market", action="store_true", help="全市场计算；full 模式要求 source research 已存在")
    parser.add_argument("--freq", required=True, type=int, choices=(1, 5, 15, 30, 60, 90, 120), help="分钟周期")
    parser.add_argument("--start-date", required=True, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD")
    parser.set_defaults(handler=_handle_compute_stk_mins_indicator)

    research_parser = subparsers.add_parser("rebuild-stk-mins-indicator-research", help="把指标 by_date 分区重排为 by_symbol_month research 层")
    add_lake_root_arg(research_parser)
    research_parser.add_argument("--indicator", required=True, choices=("macd",), help="指标名，当前支持 macd")
    research_parser.add_argument("--freq", required=True, type=int, choices=(1, 5, 15, 30, 60, 90, 120), help="分钟周期")
    research_parser.add_argument("--trade-month", required=True, help="月份，格式 YYYY-MM")
    research_parser.add_argument("--params-key", default=DEFAULT_MACD_PARAMS.params_key, help="参数版本，默认 12_26_9")
    research_parser.add_argument("--bucket-count", default=None, type=int, help="bucket 数量，默认读取配置 bucket_count")
    research_parser.set_defaults(handler=_handle_rebuild_stk_mins_indicator_research)

    queue_parser = subparsers.add_parser("list-indicator-recalc-queue", help="查看指标待重算队列，并输出建议重算命令")
    add_lake_root_arg(queue_parser)
    queue_parser.add_argument("--indicator", default="macd", choices=("macd",), help="指标名，当前支持 macd")
    queue_parser.add_argument("--include-done", action="store_true", help="包含已完成队列项")
    queue_parser.set_defaults(handler=_handle_list_indicator_recalc_queue)

    mark_parser = subparsers.add_parser("mark-indicator-recalc-done", help="人工重算完成后关闭指标待重算队列项")
    add_lake_root_arg(mark_parser)
    mark_parser.add_argument("--queue-id", required=True, help="待关闭的 queue_id")
    mark_parser.set_defaults(handler=_handle_mark_indicator_recalc_done)


def _handle_compute_stk_mins_indicator(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = StkMinsIndicatorComputeService(lake_root=settings.lake_root).compute_macd(
        mode=args.mode,
        freq=args.freq,
        start_date=args.start_date,
        end_date=args.end_date,
        ts_code=args.ts_code,
        all_market=args.all_market,
    )
    print_json(summary)
    return 0


def _handle_rebuild_stk_mins_indicator_research(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    bucket_count = args.bucket_count or settings.bucket_count
    summary = StkMinsIndicatorResearchService(lake_root=settings.lake_root, bucket_count=bucket_count).rebuild_month(
        indicator=args.indicator,
        params_key=args.params_key,
        freq=args.freq,
        trade_month=args.trade_month,
    )
    print_json(summary)
    return 0


def _handle_list_indicator_recalc_queue(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    service = IndicatorRecalcQueueService(lake_root=settings.lake_root)
    items = service.list_items(indicator=args.indicator, include_done=args.include_done)
    print(service.format_queue_items(items))
    return 0


def _handle_mark_indicator_recalc_done(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = IndicatorRecalcQueueService(lake_root=settings.lake_root).mark_done(queue_id=args.queue_id)
    print_json(summary)
    return 0
