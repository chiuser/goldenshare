from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.stk_mins_derived_service import StkMinsDerivedService
from lake_console.backend.app.services.stk_mins_research_service import StkMinsResearchService
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.services.tushare_client import TushareLakeClient
from lake_console.backend.app.services.tushare_stk_mins_sync_service import TushareStkMinsSyncService
from lake_console.backend.app.services.tushare_stock_basic_sync_service import TushareStockBasicSyncService
from lake_console.backend.app.settings import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args) or 0)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lake-console", description="Goldenshare 本地 Tushare Lake 管理台")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="初始化 Lake Root 目录结构")
    _add_lake_root_arg(init_parser)
    init_parser.set_defaults(handler=_handle_init)

    status_parser = subparsers.add_parser("status", help="查看 Lake Root 状态")
    _add_lake_root_arg(status_parser)
    status_parser.set_defaults(handler=_handle_status)

    dataset_parser = subparsers.add_parser("list-datasets", help="扫描本地 Lake 数据集")
    _add_lake_root_arg(dataset_parser)
    dataset_parser.set_defaults(handler=_handle_list_datasets)

    clean_parser = subparsers.add_parser("clean-tmp", help="审计或清理 Lake Root 下的 _tmp run 目录")
    _add_lake_root_arg(clean_parser)
    clean_parser.add_argument("--dry-run", action="store_true", help="只列出候选目录，不删除")
    clean_parser.add_argument("--older-than-hours", default=None, type=float, help="只清理超过指定小时数的 _tmp/{run_id}")
    clean_parser.set_defaults(handler=_handle_clean_tmp)

    stock_parser = subparsers.add_parser("sync-stock-basic", help="从 Tushare 拉取 stock_basic 并写入本地股票池")
    _add_lake_root_arg(stock_parser)
    stock_parser.set_defaults(handler=_handle_sync_stock_basic)

    mins_parser = subparsers.add_parser("sync-stk-mins", help="从 Tushare 拉取单股票单日分钟线并写入 by_date 分区")
    _add_lake_root_arg(mins_parser)
    mins_parser.add_argument("--ts-code", default=None, help="股票代码，例如 000001.SZ；单股票模式必填")
    mins_parser.add_argument("--freq", default=None, type=int, choices=(1, 5, 15, 30, 60), help="单个分钟周期")
    mins_parser.add_argument("--freqs", default=None, help="多个分钟周期，逗号分隔，例如 1,5,15,30,60；全市场模式可用")
    mins_parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="交易日，格式 YYYY-MM-DD")
    mins_parser.add_argument("--all-market", action="store_true", help="从本地 stock_basic 股票池读取全市场 ts_code 并扇出请求")
    mins_parser.add_argument("--part-rows", default=200_000, type=int, help="全市场模式下每个 Parquet part 的最大行数")
    mins_parser.set_defaults(handler=_handle_sync_stk_mins)

    derive_parser = subparsers.add_parser("derive-stk-mins", help="从 30/60 分钟线派生 90/120 分钟线")
    _add_lake_root_arg(derive_parser)
    derive_parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="交易日，格式 YYYY-MM-DD")
    derive_parser.add_argument("--targets", default="90,120", help="派生目标，逗号分隔，当前支持 90,120")
    derive_parser.set_defaults(handler=_handle_derive_stk_mins)

    research_parser = subparsers.add_parser("rebuild-stk-mins-research", help="把 by_date 分区重排为 by_symbol_month research 层")
    _add_lake_root_arg(research_parser)
    research_parser.add_argument("--freq", required=True, type=int, choices=(1, 5, 15, 30, 60, 90, 120), help="分钟周期")
    research_parser.add_argument("--trade-month", required=True, help="月份，格式 YYYY-MM")
    research_parser.add_argument("--bucket-count", default=None, type=int, help="bucket 数量，默认读取配置 bucket_count")
    research_parser.set_defaults(handler=_handle_rebuild_stk_mins_research)
    return parser


def _add_lake_root_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", default=None, help="本地移动盘 Lake 根目录；默认读取 GOLDENSHARE_LAKE_ROOT 或 config.local.toml")


def _settings(args: argparse.Namespace):
    return load_settings(lake_root=args.lake_root)


def _handle_init(args: argparse.Namespace) -> int:
    settings = _settings(args)
    LakeRootService(settings.lake_root).initialize()
    print(f"[lake] initialized root={settings.lake_root}")
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    settings = _settings(args)
    status = LakeRootService(settings.lake_root).get_status()
    _print_json(status.model_dump(mode="json"))
    return 0


def _handle_list_datasets(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = FilesystemScanner(settings.lake_root).list_datasets()
    _print_json([item.model_dump(mode="json") for item in items])
    return 0


def _handle_clean_tmp(args: argparse.Namespace) -> int:
    settings = _settings(args)
    service = TmpCleanupService(settings.lake_root)
    summaries = service.clean(older_than_hours=args.older_than_hours, dry_run=args.dry_run)
    _print_json(
        [
            {
                "path": item.path,
                "modified_at": item.modified_at.isoformat(),
                "age_hours": item.age_hours,
                "total_bytes": item.total_bytes,
                "file_count": item.file_count,
                "empty": item.empty,
                "action": item.action,
            }
            for item in summaries
        ]
    )
    return 0


def _handle_sync_stock_basic(args: argparse.Namespace) -> int:
    settings = _settings(args)
    service = TushareStockBasicSyncService(
        lake_root=settings.lake_root,
        client=TushareLakeClient(settings.tushare_token),
    )
    summary = service.sync()
    _print_json(summary)
    return 0


def _handle_sync_stk_mins(args: argparse.Namespace) -> int:
    settings = _settings(args)
    service = TushareStkMinsSyncService(
        lake_root=settings.lake_root,
        client=TushareLakeClient(settings.tushare_token),
    )
    if args.all_market:
        freqs = _parse_freqs(args.freqs, fallback=args.freq)
        summary = service.sync_market_day(freqs=freqs, trade_date=args.trade_date, part_rows=args.part_rows)
    else:
        if not args.ts_code:
            raise SystemExit("单股票模式必须传 --ts-code；全市场请传 --all-market。")
        if args.freq is None:
            raise SystemExit("单股票模式必须传 --freq。")
        summary = service.sync_single_symbol_day(ts_code=args.ts_code, freq=args.freq, trade_date=args.trade_date)
    _print_json(summary)
    return 0


def _handle_derive_stk_mins(args: argparse.Namespace) -> int:
    settings = _settings(args)
    targets = _parse_int_csv(args.targets, allowed={90, 120}, label="targets")
    summary = StkMinsDerivedService(lake_root=settings.lake_root).derive_day(trade_date=args.trade_date, targets=targets)
    _print_json(summary)
    return 0


def _handle_rebuild_stk_mins_research(args: argparse.Namespace) -> int:
    settings = _settings(args)
    bucket_count = args.bucket_count or settings.bucket_count
    summary = StkMinsResearchService(lake_root=settings.lake_root, bucket_count=bucket_count).rebuild_month(
        freq=args.freq,
        trade_month=args.trade_month,
    )
    _print_json(summary)
    return 0


def _parse_freqs(raw_value: str | None, *, fallback: int | None) -> list[int]:
    if raw_value:
        values = [int(item.strip()) for item in raw_value.split(",") if item.strip()]
    elif fallback is not None:
        values = [fallback]
    else:
        values = [1, 5, 15, 30, 60]
    allowed = {1, 5, 15, 30, 60}
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise SystemExit(f"不支持的 freqs={invalid}，允许值：1,5,15,30,60")
    return values


def _parse_int_csv(raw_value: str, *, allowed: set[int], label: str) -> list[int]:
    values = [int(item.strip()) for item in raw_value.split(",") if item.strip()]
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise SystemExit(f"不支持的 {label}={invalid}，允许值：{','.join(str(item) for item in sorted(allowed))}")
    return values


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
