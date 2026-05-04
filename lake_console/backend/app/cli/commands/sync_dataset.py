from __future__ import annotations

import argparse
from datetime import date

from lake_console.backend.app.cli.commands.common import (
    add_lake_root_arg,
    parse_freqs,
    parse_optional_csv,
    print_json,
    settings_from_args,
)
from lake_console.backend.app.services.tushare_client import TushareLakeClient
from lake_console.backend.app.services.tushare_stock_basic_sync_service import TushareStockBasicSyncService
from lake_console.backend.app.services.tushare_trade_cal_sync_service import TushareTradeCalSyncService
from lake_console.backend.app.sync import LakeSyncEngine, LakeSyncPlanner


def register_sync_dataset_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    plan_parser = subparsers.add_parser("plan-sync", help="预览数据集本地 Lake 同步计划，不发请求、不写文件")
    add_lake_root_arg(plan_parser)
    plan_parser.add_argument("dataset_key", help="数据集 key，例如 daily、index_basic、moneyflow")
    plan_parser.add_argument(
        "--from",
        dest="source",
        default="tushare",
        choices=("tushare", "prod-raw-db"),
        help="同步来源，默认 tushare；daily 可显式选择 prod-raw-db",
    )
    plan_parser.add_argument("--trade-date", default=None, type=date.fromisoformat, help="单日日期，格式 YYYY-MM-DD")
    plan_parser.add_argument("--start-date", default=None, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD")
    plan_parser.add_argument("--end-date", default=None, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD")
    plan_parser.add_argument("--ts-code", default=None, help="证券代码，可用于单标的调试或补数计划")
    plan_parser.add_argument("--market", default=None, help="市场枚举，快照类数据集可用")
    plan_parser.add_argument("--all-market", action="store_true", help="用于 stk_mins 计划预估：读取本地股票池估算全市场请求量")
    plan_parser.add_argument("--freq", default=None, type=int, choices=(1, 5, 15, 30, 60), help="单个分钟周期，stk_mins 可用")
    plan_parser.add_argument("--freqs", default=None, help="多个分钟周期，逗号分隔，例如 1,5,15,30,60；stk_mins 可用")
    plan_parser.add_argument("--daily-quota-limit", default=250000, type=int, help="用于 stk_mins 计划预估的单日配额上限，默认 250000")
    plan_parser.set_defaults(handler=_handle_plan_sync)

    sync_dataset_parser = subparsers.add_parser("sync-dataset", help="按 Lake Dataset Catalog 同步单个数据集")
    add_lake_root_arg(sync_dataset_parser)
    sync_dataset_parser.add_argument("dataset_key", help="数据集 key；当前接入 index_basic、daily、moneyflow")
    sync_dataset_parser.add_argument(
        "--from",
        dest="source",
        default="tushare",
        choices=("tushare", "prod-raw-db"),
        help="同步来源，默认 tushare；daily 可显式选择 prod-raw-db",
    )
    sync_dataset_parser.add_argument("--trade-date", default=None, type=date.fromisoformat, help="单日日期，格式 YYYY-MM-DD；daily/moneyflow 可用")
    sync_dataset_parser.add_argument("--start-date", default=None, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD；daily/moneyflow 可用")
    sync_dataset_parser.add_argument("--end-date", default=None, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD；daily/moneyflow 可用")
    sync_dataset_parser.add_argument("--ts-code", default=None, help="证券代码")
    sync_dataset_parser.add_argument("--name", default=None, help="源站 name 过滤")
    sync_dataset_parser.add_argument("--market", default=None, help="市场枚举；多个值用逗号分隔")
    sync_dataset_parser.add_argument("--publisher", default=None, help="发布方过滤")
    sync_dataset_parser.add_argument("--category", default=None, help="指数类别过滤")
    sync_dataset_parser.set_defaults(handler=_handle_sync_dataset)

    stock_parser = subparsers.add_parser("sync-stock-basic", help="从 Tushare 拉取 stock_basic 并写入本地股票池")
    add_lake_root_arg(stock_parser)
    stock_parser.set_defaults(handler=_handle_sync_stock_basic)

    trade_cal_parser = subparsers.add_parser("sync-trade-cal", help="从 Tushare 拉取交易日历并写入本地交易日历")
    add_lake_root_arg(trade_cal_parser)
    trade_cal_parser.add_argument("--start-date", default=None, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD；与 --end-date 同时传入时走区间模式")
    trade_cal_parser.add_argument("--end-date", default=None, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD；与 --start-date 同时传入时走区间模式")
    trade_cal_parser.add_argument("--exchange", default="SSE", help="交易所，默认 SSE")
    trade_cal_parser.set_defaults(handler=_handle_sync_trade_cal)


def _handle_plan_sync(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    plan = LakeSyncPlanner(
        lake_root=settings.lake_root,
        stk_mins_request_window_days=settings.stk_mins_request_window_days,
    ).plan(
        dataset_key=args.dataset_key,
        source=args.source,
        trade_date=args.trade_date,
        start_date=args.start_date,
        end_date=args.end_date,
        ts_code=args.ts_code,
        market=args.market,
        all_market=args.all_market,
        freq=args.freq,
        freqs=parse_freqs(args.freqs, fallback=args.freq) if args.dataset_key == "stk_mins" else None,
        daily_quota_limit=args.daily_quota_limit,
    )
    print_json(plan.to_dict())
    return 0


def _handle_sync_dataset(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    engine = LakeSyncEngine(
        lake_root=settings.lake_root,
        client=TushareLakeClient(
            settings.tushare_token,
            request_limit_per_minute=settings.tushare_request_limit_per_minute,
        ),
        settings=settings,
    )
    summary = engine.sync_dataset(
        dataset_key=args.dataset_key,
        source=args.source,
        trade_date=args.trade_date,
        start_date=args.start_date,
        end_date=args.end_date,
        ts_code=args.ts_code,
        name=args.name,
        markets=parse_optional_csv(args.market),
        publisher=args.publisher,
        category=args.category,
    )
    print_json(summary)
    return 0


def _handle_sync_stock_basic(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    service = TushareStockBasicSyncService(
        lake_root=settings.lake_root,
        client=TushareLakeClient(
            settings.tushare_token,
            request_limit_per_minute=settings.tushare_request_limit_per_minute,
        ),
    )
    summary = service.sync()
    print_json(summary)
    return 0


def _handle_sync_trade_cal(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    if (args.start_date is None) != (args.end_date is None):
        raise SystemExit("sync-trade-cal 的 --start-date 和 --end-date 必须同时传入，或同时省略。")
    service = TushareTradeCalSyncService(
        lake_root=settings.lake_root,
        client=TushareLakeClient(
            settings.tushare_token,
            request_limit_per_minute=settings.tushare_request_limit_per_minute,
        ),
    )
    summary = service.sync(start_date=args.start_date, end_date=args.end_date, exchange=args.exchange)
    print_json(summary)
    return 0
