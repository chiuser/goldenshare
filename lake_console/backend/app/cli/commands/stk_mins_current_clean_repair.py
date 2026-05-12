from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, print_json, settings_from_args
from lake_console.backend.app.services.stk_mins_current_clean_2022_bj_freq30_repair_service import (
    StkMinsCurrentClean2022BjFreq30RepairService,
)
from lake_console.backend.app.services.stk_mins_current_clean_20241030_multifreq_repair_service import (
    StkMinsCurrentClean20241030MultifreqRepairService,
)


def register_stk_mins_current_clean_repair_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "repair-current-clean-20241030-multifreq",
        help="专项修复当前错误 clean 的 2024-10-30 5/15/30/60 混入 1min 问题（独立命令，不可泛化）",
    )
    add_lake_root_arg(parser)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只读审计与重建计划，不写正式分区")
    mode.add_argument("--apply", action="store_true", help="执行专项修复并替换目标分区")
    parser.set_defaults(handler=_handle_repair_current_clean_20241030_multifreq)

    parser_2022 = subparsers.add_parser(
        "repair-current-clean-2022-bj-freq30",
        help="专项修复当前错误 clean 的 2022 北交所 30min 缺失（bar_count=6）问题（独立命令，不可泛化）",
    )
    add_lake_root_arg(parser_2022)
    mode_2022 = parser_2022.add_mutually_exclusive_group(required=True)
    mode_2022.add_argument("--dry-run", action="store_true", help="只读审计与重建计划，不写正式分区")
    mode_2022.add_argument("--apply", action="store_true", help="执行专项修复并替换目标分区")
    parser_2022.set_defaults(handler=_handle_repair_current_clean_2022_bj_freq30)


def _handle_repair_current_clean_20241030_multifreq(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = StkMinsCurrentClean20241030MultifreqRepairService(lake_root=settings.lake_root).repair(
        dry_run=args.dry_run,
        apply=args.apply,
    )
    print_json(summary)
    return 0


def _handle_repair_current_clean_2022_bj_freq30(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = StkMinsCurrentClean2022BjFreq30RepairService(lake_root=settings.lake_root).repair(
        dry_run=args.dry_run,
        apply=args.apply,
    )
    print_json(summary)
    return 0
