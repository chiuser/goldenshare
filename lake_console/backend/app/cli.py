from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.stk_mins_derived_service import StkMinsDerivedService
from lake_console.backend.app.services.stk_mins_research_service import StkMinsResearchService
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.services.tushare_client import TushareLakeClient
from lake_console.backend.app.services.tushare_stk_mins_sync_service import (
    DEFAULT_PART_ROWS,
    StkMinsProgressEvent,
    TushareStkMinsSyncService,
)
from lake_console.backend.app.services.tushare_stock_basic_sync_service import TushareStockBasicSyncService
from lake_console.backend.app.services.tushare_trade_cal_sync_service import TushareTradeCalSyncService
from lake_console.backend.app.settings import load_settings
from lake_console.backend.app.sync import LakeSyncEngine, LakeSyncPlanner


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

    plan_parser = subparsers.add_parser("plan-sync", help="预览数据集本地 Lake 同步计划，不发请求、不写文件")
    _add_lake_root_arg(plan_parser)
    plan_parser.add_argument("dataset_key", help="数据集 key，例如 daily、index_basic、moneyflow")
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
    _add_lake_root_arg(sync_dataset_parser)
    sync_dataset_parser.add_argument("dataset_key", help="数据集 key；当前只接入 index_basic")
    sync_dataset_parser.add_argument("--ts-code", default=None, help="证券代码")
    sync_dataset_parser.add_argument("--name", default=None, help="源站 name 过滤")
    sync_dataset_parser.add_argument("--market", default=None, help="市场枚举；多个值用逗号分隔")
    sync_dataset_parser.add_argument("--publisher", default=None, help="发布方过滤")
    sync_dataset_parser.add_argument("--category", default=None, help="指数类别过滤")
    sync_dataset_parser.set_defaults(handler=_handle_sync_dataset)

    clean_parser = subparsers.add_parser("clean-tmp", help="审计或清理 Lake Root 下的 _tmp run 目录")
    _add_lake_root_arg(clean_parser)
    clean_parser.add_argument("--dry-run", action="store_true", help="只列出候选目录，不删除")
    clean_parser.add_argument("--older-than-hours", default=None, type=float, help="只清理超过指定小时数的 _tmp/{run_id}")
    clean_parser.set_defaults(handler=_handle_clean_tmp)

    stock_parser = subparsers.add_parser("sync-stock-basic", help="从 Tushare 拉取 stock_basic 并写入本地股票池")
    _add_lake_root_arg(stock_parser)
    stock_parser.set_defaults(handler=_handle_sync_stock_basic)

    trade_cal_parser = subparsers.add_parser("sync-trade-cal", help="从 Tushare 拉取交易日历并写入本地交易日历")
    _add_lake_root_arg(trade_cal_parser)
    trade_cal_parser.add_argument("--start-date", default=None, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD；与 --end-date 同时传入时走区间模式")
    trade_cal_parser.add_argument("--end-date", default=None, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD；与 --start-date 同时传入时走区间模式")
    trade_cal_parser.add_argument("--exchange", default="SSE", help="交易所，默认 SSE")
    trade_cal_parser.set_defaults(handler=_handle_sync_trade_cal)

    mins_parser = subparsers.add_parser("sync-stk-mins", help="从 Tushare 拉取单股票单日分钟线并写入 by_date 分区")
    _add_lake_root_arg(mins_parser)
    mins_parser.add_argument("--ts-code", default=None, help="股票代码，例如 000001.SZ；单股票模式必填")
    mins_parser.add_argument("--freq", default=None, type=int, choices=(1, 5, 15, 30, 60), help="单个分钟周期")
    mins_parser.add_argument("--freqs", default=None, help="多个分钟周期，逗号分隔，例如 1,5,15,30,60；全市场模式可用")
    mins_parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="交易日，格式 YYYY-MM-DD")
    mins_parser.add_argument("--all-market", action="store_true", help="从本地 stock_basic 股票池读取全市场 ts_code 并扇出请求")
    mins_parser.add_argument("--part-rows", default=DEFAULT_PART_ROWS, type=int, help="全市场模式下每个 Parquet part 的最大行数")
    mins_parser.set_defaults(handler=_handle_sync_stk_mins)

    range_parser = subparsers.add_parser("sync-stk-mins-range", help="按本地交易日历拉取区间内分钟线行情")
    _add_lake_root_arg(range_parser)
    range_parser.add_argument("--start-date", required=True, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD")
    range_parser.add_argument("--end-date", required=True, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD")
    range_parser.add_argument("--all-market", action="store_true", help="从本地 stock_basic 股票池读取全市场 ts_code 并扇出请求")
    range_parser.add_argument("--ts-code", default=None, help="股票代码，例如 000001.SZ；单股票模式必填")
    range_parser.add_argument("--freq", default=None, type=int, choices=(1, 5, 15, 30, 60), help="单个分钟周期")
    range_parser.add_argument("--freqs", default=None, help="多个分钟周期，逗号分隔，例如 1,5,15,30,60；全市场模式可用")
    range_parser.add_argument("--part-rows", default=DEFAULT_PART_ROWS, type=int, help="全市场模式下每个 Parquet part 的最大行数")
    range_parser.set_defaults(handler=_handle_sync_stk_mins_range)

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


def _handle_plan_sync(args: argparse.Namespace) -> int:
    settings = _settings(args)
    plan = LakeSyncPlanner(
        lake_root=settings.lake_root,
        stk_mins_request_window_days=settings.stk_mins_request_window_days,
    ).plan(
        dataset_key=args.dataset_key,
        trade_date=args.trade_date,
        start_date=args.start_date,
        end_date=args.end_date,
        ts_code=args.ts_code,
        market=args.market,
        all_market=args.all_market,
        freq=args.freq,
        freqs=_parse_freqs(args.freqs, fallback=args.freq) if args.dataset_key == "stk_mins" else None,
        daily_quota_limit=args.daily_quota_limit,
    )
    _print_json(plan.to_dict())
    return 0


def _handle_sync_dataset(args: argparse.Namespace) -> int:
    settings = _settings(args)
    engine = LakeSyncEngine(
        lake_root=settings.lake_root,
        client=TushareLakeClient(
            settings.tushare_token,
            request_limit_per_minute=settings.tushare_request_limit_per_minute,
        ),
    )
    summary = engine.sync_dataset(
        dataset_key=args.dataset_key,
        ts_code=args.ts_code,
        name=args.name,
        markets=_parse_optional_csv(args.market),
        publisher=args.publisher,
        category=args.category,
    )
    _print_json(summary)
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
        client=TushareLakeClient(
            settings.tushare_token,
            request_limit_per_minute=settings.tushare_request_limit_per_minute,
        ),
    )
    summary = service.sync()
    _print_json(summary)
    return 0


def _handle_sync_trade_cal(args: argparse.Namespace) -> int:
    settings = _settings(args)
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
    _print_json(summary)
    return 0


def _handle_sync_stk_mins(args: argparse.Namespace) -> int:
    settings = _settings(args)
    service = TushareStkMinsSyncService(
        lake_root=settings.lake_root,
        client=TushareLakeClient(
            settings.tushare_token,
            request_limit_per_minute=settings.tushare_request_limit_per_minute,
        ),
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


def _handle_sync_stk_mins_range(args: argparse.Namespace) -> int:
    settings = _settings(args)
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
            freqs = _parse_freqs(args.freqs, fallback=args.freq)
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


def _parse_optional_csv(raw_value: str | None) -> list[str] | None:
    if not raw_value:
        return None
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    return values or None


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


class StkMinsTerminalProgress:
    def __init__(self, *, stream=None, width: int = 24, min_interval_seconds: float = 0.2) -> None:
        self.stream = stream or sys.stderr
        self.width = width
        self.min_interval_seconds = min_interval_seconds
        self._last_render_at = 0.0
        self._last_line_length = 0
        self._line_active = False

    def __call__(self, payload: str | StkMinsProgressEvent) -> None:
        if isinstance(payload, StkMinsProgressEvent):
            self._render_event(payload)
            return
        self._print_message(payload)

    def finish(self) -> None:
        if self._line_active:
            self.stream.write("\n")
            self.stream.flush()
            self._line_active = False
            self._last_line_length = 0

    def _render_event(self, event: StkMinsProgressEvent) -> None:
        now = time.monotonic()
        if event.units_done < event.units_total and now - self._last_render_at < self.min_interval_seconds:
            return
        self._last_render_at = now
        percent = 0.0 if event.units_total <= 0 else min(1.0, event.units_done / event.units_total)
        filled = int(round(self.width * percent))
        bar = "█" * filled + "░" * (self.width - filled)
        line = (
            f"[{bar}] {percent * 100:6.2f}% "
            f"unit={event.units_done}/{event.units_total} "
            f"ts_code={event.ts_code} {_format_event_window(event)} freq={event.freq} "
            f"fetched={event.fetched_rows} written={event.written_rows}"
        )
        if event.page is not None and event.offset is not None:
            line += f" page={event.page} offset={event.offset}"
        padding = " " * max(0, self._last_line_length - len(line))
        self.stream.write(f"\r{line}{padding}")
        self.stream.flush()
        self._last_line_length = len(line)
        self._line_active = True

    def _print_message(self, message: str) -> None:
        if self._line_active:
            self.stream.write("\n")
            self._line_active = False
            self._last_line_length = 0
        self.stream.write(message + "\n")
        self.stream.flush()


def _format_event_window(event: StkMinsProgressEvent) -> str:
    if event.window_start and event.window_end:
        return f"window={event.window_start.isoformat()}~{event.window_end.isoformat()}"
    if event.trade_date:
        return f"trade_date={event.trade_date.isoformat()}"
    return "window=-"


if __name__ == "__main__":
    raise SystemExit(main())
