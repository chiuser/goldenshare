from __future__ import annotations

import argparse
from datetime import date

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, parse_freqs, parse_int_csv, print_json, settings_from_args
from lake_console.backend.app.cli.progress import StkMinsTerminalProgress
from lake_console.backend.app.services.stk_mins_derived_service import StkMinsDerivedService
from lake_console.backend.app.services.stk_mins_gap_repair_service import StkMinsGapRepairService
from lake_console.backend.app.services.stk_mins_clean_service import StkMinsCleanService
from lake_console.backend.app.services.stk_mins_raw_recovery_service import StkMinsRawRecoveryService
from lake_console.backend.app.services.stk_mins_research_service import StkMinsResearchService
from lake_console.backend.app.services.stk_mins_schema_migration_service import StkMinsSchemaMigrationService
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
    range_parser.add_argument("--freqs", default=None, help="多个分钟周期，逗号分隔，例如 1,5,15,30,60；全市场和单股票区间模式均可用")
    range_parser.add_argument("--part-rows", default=DEFAULT_PART_ROWS, type=int, help="全市场模式下每个 Parquet part 的最大行数")
    range_parser.set_defaults(handler=_handle_sync_stk_mins_range)

    derive_parser = subparsers.add_parser("derive-stk-mins", help="从 30/60 分钟线派生 90/120 分钟线")
    add_lake_root_arg(derive_parser)
    derive_parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="交易日，格式 YYYY-MM-DD")
    derive_parser.add_argument("--targets", default="90,120", help="派生目标，逗号分隔，当前支持 90,120")
    derive_parser.set_defaults(handler=_handle_derive_stk_mins)

    derive_range_parser = subparsers.add_parser("derive-stk-mins-range", help="按本地交易日历批量派生 90/120 分钟线")
    add_lake_root_arg(derive_range_parser)
    derive_range_parser.add_argument("--start-date", required=True, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD")
    derive_range_parser.add_argument("--end-date", required=True, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD")
    derive_range_parser.add_argument("--targets", default="90,120", help="派生目标，逗号分隔，当前支持 90,120")
    derive_range_parser.set_defaults(handler=_handle_derive_stk_mins_range)

    derive_from_clean_range_parser = subparsers.add_parser(
        "rebuild-stk-mins-derived-from-clean-range",
        help="从 clean 30/60 分钟线批量重建 derived 90/120 分钟线",
    )
    add_lake_root_arg(derive_from_clean_range_parser)
    derive_from_clean_range_parser.add_argument("--start-date", required=True, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD")
    derive_from_clean_range_parser.add_argument("--end-date", required=True, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD")
    derive_from_clean_range_parser.add_argument("--target-freqs", default="90,120", help="派生目标，逗号分隔，当前支持 90,120")
    derive_from_clean_range_parser.set_defaults(handler=_handle_rebuild_stk_mins_derived_from_clean_range)

    repair_parser = subparsers.add_parser("repair-stk-mins-from-1m", help="用本地 1 分钟线修补已审计的 5/15 分钟 source gap")
    add_lake_root_arg(repair_parser)
    repair_parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="缺口交易日，格式 YYYY-MM-DD")
    repair_parser.add_argument("--freq", required=True, type=int, choices=(5, 15), help="目标分钟周期，仅支持 5 或 15")
    repair_parser.add_argument("--ts-code", default=None, help="只修补指定股票代码；用于目标分区已存在但该股票缺失的场景")
    repair_parser.set_defaults(handler=_handle_repair_stk_mins_from_1m)

    research_parser = subparsers.add_parser("rebuild-stk-mins-research", help="把 by_date 分区重排为 by_symbol_month research 层")
    add_lake_root_arg(research_parser)
    research_parser.add_argument("--freq", required=True, type=int, choices=(1, 5, 15, 30, 60, 90, 120), help="分钟周期")
    research_parser.add_argument("--trade-month", required=True, help="月份，格式 YYYY-MM")
    research_parser.add_argument("--bucket-count", default=None, type=int, help="bucket 数量，默认读取配置 bucket_count")
    research_parser.set_defaults(handler=_handle_rebuild_stk_mins_research)

    research_range_parser = subparsers.add_parser("rebuild-stk-mins-research-range", help="批量重建多个 freq 和月份的 research 层")
    add_lake_root_arg(research_range_parser)
    research_range_parser.add_argument("--start-month", required=True, help="开始月份，格式 YYYY-MM")
    research_range_parser.add_argument("--end-month", required=True, help="结束月份，格式 YYYY-MM")
    research_range_parser.add_argument("--freqs", required=True, help="多个分钟周期，逗号分隔，例如 1,5,15,30,60,90,120")
    research_range_parser.add_argument("--bucket-count", default=None, type=int, help="bucket 数量，默认读取配置 bucket_count")
    research_range_parser.set_defaults(handler=_handle_rebuild_stk_mins_research_range)

    research_from_clean_range_parser = subparsers.add_parser(
        "rebuild-stk-mins-research-from-clean-range",
        help="从 clean/derived 输入批量重建 by_symbol_month research 层",
    )
    add_lake_root_arg(research_from_clean_range_parser)
    research_from_clean_range_parser.add_argument("--start-month", required=True, help="开始月份，格式 YYYY-MM")
    research_from_clean_range_parser.add_argument("--end-month", required=True, help="结束月份，格式 YYYY-MM")
    research_from_clean_range_parser.add_argument("--freqs", required=True, help="多个分钟周期，逗号分隔，例如 1,5,15,30,60,90,120")
    research_from_clean_range_parser.add_argument("--bucket-count", default=None, type=int, help="bucket 数量，默认读取配置 bucket_count")
    research_from_clean_range_parser.set_defaults(handler=_handle_rebuild_stk_mins_research_range)

    migrate_parser = subparsers.add_parser("migrate-stk-mins-schema", help="迁移本地 stk_mins raw Parquet schema，不请求 Tushare")
    add_lake_root_arg(migrate_parser)
    mode = migrate_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只扫描并报告待迁移文件，不写入")
    mode.add_argument("--apply", action="store_true", help="执行逐文件 schema 迁移")
    migrate_parser.add_argument("--freq", default=None, type=int, choices=(1, 5, 15, 30, 60), help="只处理指定分钟周期")
    migrate_parser.add_argument("--trade-date", default=None, type=date.fromisoformat, help="只处理指定交易日，格式 YYYY-MM-DD")
    migrate_parser.set_defaults(handler=_handle_migrate_stk_mins_schema)

    audit_parser = subparsers.add_parser("audit-stk-mins-raw-integrity", help="只读审计 stk_mins raw by_date 分区完整性")
    add_lake_root_arg(audit_parser)
    audit_parser.add_argument("--start-date", required=True, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD")
    audit_parser.add_argument("--end-date", required=True, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD")
    audit_parser.add_argument("--freqs", default="1,5,15,30,60", help="多个分钟周期，逗号分隔，例如 1,5,15,30,60")
    audit_parser.add_argument("--patch-ts-code", default=None, help="用于检查 raw patch 行的股票代码，例如 300114.SZ")
    audit_parser.add_argument("--sample-limit", default=20, type=int, help="每个 freq 返回的样本数量上限")
    audit_parser.set_defaults(handler=_handle_audit_stk_mins_raw_integrity)

    recover_parser = subparsers.add_parser("recover-stk-mins-raw-from-research", help="从 research 恢复 stk_mins raw 损坏分区")
    add_lake_root_arg(recover_parser)
    recover_parser.add_argument("--start-date", required=True, type=date.fromisoformat, help="开始日期，格式 YYYY-MM-DD")
    recover_parser.add_argument("--end-date", required=True, type=date.fromisoformat, help="结束日期，格式 YYYY-MM-DD")
    recover_parser.add_argument("--freqs", required=True, help="多个分钟周期，逗号分隔，例如 1,5")
    recover_parser.add_argument("--patch-ts-code", required=True, help="需要从当前 raw patch 行合并回去的股票代码，例如 300114.SZ")
    recover_mode = recover_parser.add_mutually_exclusive_group(required=True)
    recover_mode.add_argument("--dry-run", action="store_true", help="只生成恢复预案，不写任何文件")
    recover_mode.add_argument("--apply", action="store_true", help="执行恢复写入；会备份原 raw 分区到 _recovery")
    recover_parser.add_argument("--sample-limit", default=20, type=int, help="每个 freq 返回的计划样本数量上限")
    recover_parser.set_defaults(handler=_handle_recover_stk_mins_raw_from_research)

    identity_parser = subparsers.add_parser(
        "build-stk-mins-security-identity-map",
        help="构建 stk_mins clean 层使用的 security_identity_map",
    )
    add_lake_root_arg(identity_parser)
    identity_mode = identity_parser.add_mutually_exclusive_group(required=True)
    identity_mode.add_argument("--dry-run", action="store_true", help="只生成身份映射预案，不写 manifest")
    identity_mode.add_argument("--apply", action="store_true", help="写入 manifest/security_identity/security_identity_map.parquet")
    identity_parser.add_argument("--sample-limit", default=20, type=int, help="样本数量上限")
    identity_parser.set_defaults(handler=_handle_build_stk_mins_security_identity_map)

    clean_next_audit_parser = subparsers.add_parser(
        "audit-stk-mins-by-date-clean-next",
        help="只读审计 research/stk_mins_by_date_clean_next 是否符合正式 clean schema 与基础规则",
    )
    add_lake_root_arg(clean_next_audit_parser)
    clean_next_audit_parser.add_argument("--freqs", default="1,5,15,30,60", help="多个分钟周期，逗号分隔")
    clean_next_audit_parser.add_argument("--start-date", default=None, type=date.fromisoformat, help="可选开始交易日")
    clean_next_audit_parser.add_argument("--end-date", default=None, type=date.fromisoformat, help="可选结束交易日")
    clean_next_audit_parser.add_argument("--sample-limit", default=20, type=int, help="样本数量上限")
    clean_next_audit_parser.set_defaults(handler=_handle_audit_stk_mins_by_date_clean_next)

    clean_next_completeness_parser = subparsers.add_parser(
        "audit-stk-mins-clean-next-completeness",
        help="审计 clean_next 分钟线完备性，并可写入 clean_next 专用问题账本",
    )
    add_lake_root_arg(clean_next_completeness_parser)
    clean_next_completeness_parser.add_argument("--freqs", default="1,5,15,30,60", help="多个分钟周期，逗号分隔")
    clean_next_completeness_parser.add_argument("--start-date", default=None, type=date.fromisoformat, help="可选开始交易日")
    clean_next_completeness_parser.add_argument("--end-date", default=None, type=date.fromisoformat, help="可选结束交易日")
    clean_next_completeness_parser.add_argument("--sample-limit", default=20, type=int, help="样本数量上限")
    clean_next_completeness_parser.add_argument(
        "--write-ledger",
        action="store_true",
        help="只写 manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet，不修改 clean_next/derived/research",
    )
    clean_next_completeness_parser.set_defaults(handler=_handle_audit_stk_mins_clean_next_completeness)

    clean_next_rebuild_parser = subparsers.add_parser(
        "rebuild-stk-mins-by-date-clean-next-range",
        help="按正式 schema 从 raw 重建 research/stk_mins_by_date_clean_next",
    )
    add_lake_root_arg(clean_next_rebuild_parser)
    clean_next_rebuild_mode = clean_next_rebuild_parser.add_mutually_exclusive_group(required=True)
    clean_next_rebuild_mode.add_argument("--dry-run", action="store_true", help="只生成正式 clean candidate 重建计划，不写文件")
    clean_next_rebuild_mode.add_argument("--apply", action="store_true", help="执行正式 clean candidate 分区重建，只写 clean_next")
    clean_next_rebuild_parser.add_argument("--freqs", default="1,5,15,30,60", help="多个分钟周期，逗号分隔")
    clean_next_rebuild_parser.add_argument("--start-date", default=None, type=date.fromisoformat, help="可选开始交易日")
    clean_next_rebuild_parser.add_argument("--end-date", default=None, type=date.fromisoformat, help="可选结束交易日")
    clean_next_rebuild_parser.add_argument("--replace-existing", action="store_true", help="允许替换已存在的 clean_next 分区")
    clean_next_rebuild_parser.add_argument("--sample-limit", default=20, type=int, help="样本数量上限")
    clean_next_rebuild_parser.set_defaults(handler=_handle_rebuild_stk_mins_by_date_clean_next_range)


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
            if args.freq is None and not args.freqs:
                raise SystemExit("单股票区间模式必须传 --freq 或 --freqs。")
            freqs = parse_freqs(args.freqs, fallback=args.freq)
            summary = service.sync_range(
                start_date=args.start_date,
                end_date=args.end_date,
                freqs=freqs,
                all_market=False,
                ts_code=args.ts_code,
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


def _handle_derive_stk_mins_range(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    targets = parse_int_csv(args.targets, allowed={90, 120}, label="targets")
    summary = StkMinsDerivedService(lake_root=settings.lake_root).derive_range(
        start_date=args.start_date,
        end_date=args.end_date,
        targets=targets,
    )
    print_json(summary)
    return 0


def _handle_rebuild_stk_mins_derived_from_clean_range(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    targets = parse_int_csv(args.target_freqs, allowed={90, 120}, label="target-freqs")
    summary = StkMinsDerivedService(lake_root=settings.lake_root).derive_range(
        start_date=args.start_date,
        end_date=args.end_date,
        targets=targets,
    )
    print_json(summary)
    return 0


def _handle_repair_stk_mins_from_1m(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = StkMinsGapRepairService(lake_root=settings.lake_root).repair_day(
        trade_date=args.trade_date,
        freq=args.freq,
        ts_code=args.ts_code,
    )
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


def _handle_rebuild_stk_mins_research_range(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    bucket_count = args.bucket_count or settings.bucket_count
    freqs = parse_int_csv(args.freqs, allowed={1, 5, 15, 30, 60, 90, 120}, label="freqs")
    summary = StkMinsResearchService(lake_root=settings.lake_root, bucket_count=bucket_count).rebuild_range(
        freqs=freqs,
        start_month=args.start_month,
        end_month=args.end_month,
    )
    print_json(summary)
    return 0


def _handle_migrate_stk_mins_schema(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = StkMinsSchemaMigrationService(lake_root=settings.lake_root).migrate(
        dry_run=args.dry_run,
        apply=args.apply,
        freq=args.freq,
        trade_date=args.trade_date,
    )
    print_json(summary)
    return 0


def _handle_audit_stk_mins_raw_integrity(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    freqs = parse_freqs(args.freqs, fallback=None)
    summary = StkMinsRawRecoveryService(lake_root=settings.lake_root).audit_raw_integrity(
        freqs=freqs,
        start_date=args.start_date,
        end_date=args.end_date,
        patch_ts_code=args.patch_ts_code,
        sample_limit=args.sample_limit,
    )
    print_json(summary)
    return 0


def _handle_recover_stk_mins_raw_from_research(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    freqs = parse_freqs(args.freqs, fallback=None)
    service = StkMinsRawRecoveryService(lake_root=settings.lake_root)
    if args.dry_run:
        summary = service.plan_recover_from_research(
            freqs=freqs,
            start_date=args.start_date,
            end_date=args.end_date,
            patch_ts_code=args.patch_ts_code,
            sample_limit=args.sample_limit,
        )
    else:
        summary = service.apply_recover_from_research(
            freqs=freqs,
            start_date=args.start_date,
            end_date=args.end_date,
            patch_ts_code=args.patch_ts_code,
            sample_limit=args.sample_limit,
        )
    print_json(summary)
    return 0


def _handle_build_stk_mins_security_identity_map(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = StkMinsCleanService(lake_root=settings.lake_root).build_security_identity_map(
        dry_run=args.dry_run,
        apply=args.apply,
        sample_limit=args.sample_limit,
    )
    print_json(summary)
    return 0


def _handle_audit_stk_mins_by_date_clean_next(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    freqs = parse_freqs(args.freqs, fallback=None)
    summary = StkMinsCleanService(lake_root=settings.lake_root).audit_formal_clean_next_layer(
        freqs=freqs,
        start_date=args.start_date,
        end_date=args.end_date,
        sample_limit=args.sample_limit,
    )
    print_json(summary)
    return 0


def _handle_audit_stk_mins_clean_next_completeness(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    freqs = parse_freqs(args.freqs, fallback=None)
    summary = StkMinsCleanService(lake_root=settings.lake_root).audit_formal_clean_next_completeness(
        freqs=freqs,
        start_date=args.start_date,
        end_date=args.end_date,
        sample_limit=args.sample_limit,
        write_ledger=args.write_ledger,
    )
    print_json(summary)
    return 0


def _handle_rebuild_stk_mins_by_date_clean_next_range(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    freqs = parse_freqs(args.freqs, fallback=None)
    summary = StkMinsCleanService(lake_root=settings.lake_root).rebuild_formal_clean_next_from_raw(
        freqs=freqs,
        start_date=args.start_date,
        end_date=args.end_date,
        dry_run=args.dry_run,
        apply=args.apply,
        replace_existing=args.replace_existing,
        sample_limit=args.sample_limit,
    )
    print_json(summary)
    return 0
