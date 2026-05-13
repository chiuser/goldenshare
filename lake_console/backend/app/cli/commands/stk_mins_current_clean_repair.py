from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, print_json, settings_from_args
from lake_console.backend.app.services.stk_mins_clean_next_20241030_multifreq_repair_service import (
    StkMinsCleanNext20241030MultifreqRepairService,
)
from lake_console.backend.app.services.stk_mins_clean_next_2022_bj_freq30_repair_service import (
    StkMinsCleanNext2022BjFreq30RepairService,
)


def register_stk_mins_clean_next_repair_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser_clean_next_20241030 = subparsers.add_parser(
        "repair-stk-mins-clean-next-20241030-multifreq",
        help="专项修复 clean_next 的 2024-10-30 5/15/30/60 混入 1min 问题（独立命令，不可泛化）",
    )
    add_lake_root_arg(parser_clean_next_20241030)
    mode_clean_next_20241030 = parser_clean_next_20241030.add_mutually_exclusive_group(required=True)
    mode_clean_next_20241030.add_argument("--dry-run", action="store_true", help="只读审计与重建计划，不写正式分区")
    mode_clean_next_20241030.add_argument("--apply", action="store_true", help="执行专项修复并替换 clean_next 目标分区")
    parser_clean_next_20241030.set_defaults(handler=_handle_repair_clean_next_20241030_multifreq)

    parser_clean_next_2022_bj = subparsers.add_parser(
        "repair-stk-mins-clean-next-2022-bj-freq30",
        help="专项修复 clean_next 的 2022 北交所 30min 缺失 bar_count=6 问题（独立命令，不可泛化）",
    )
    add_lake_root_arg(parser_clean_next_2022_bj)
    mode_clean_next_2022_bj = parser_clean_next_2022_bj.add_mutually_exclusive_group(required=True)
    mode_clean_next_2022_bj.add_argument("--dry-run", action="store_true", help="只读审计与重建计划，不写正式分区")
    mode_clean_next_2022_bj.add_argument("--apply", action="store_true", help="执行专项修复并替换 clean_next 目标分区")
    parser_clean_next_2022_bj.set_defaults(handler=_handle_repair_clean_next_2022_bj_freq30)


def _handle_repair_clean_next_20241030_multifreq(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = StkMinsCleanNext20241030MultifreqRepairService(lake_root=settings.lake_root).repair(
        dry_run=args.dry_run,
        apply=args.apply,
    )
    print_json(summary)
    return 0


def _handle_repair_clean_next_2022_bj_freq30(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    summary = StkMinsCleanNext2022BjFreq30RepairService(lake_root=settings.lake_root).repair(
        dry_run=args.dry_run,
        apply=args.apply,
    )
    print_json(summary)
    return 0
