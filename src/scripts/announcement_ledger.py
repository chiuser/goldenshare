"""Stable CLI entry for local announcement ledger maintenance."""
from __future__ import annotations
import argparse
import re
from pathlib import Path
from src.foundation.clients.announcement_archive.core import DownloadOptions, iso_date
from src.foundation.dao.announcement_archive.maintenance import ARTIFACT_STATES, LedgerQueryPolicy
from src.ops.runtime.announcement_archive.maintenance import run_cli


def parse_options(argv=None):
    policy = LedgerQueryPolicy()
    def positive(value):
        number = int(value)
        if number <= 0 or number > 2**63 - 1:
            raise argparse.ArgumentTypeError('请输入正整数游标')
        return number
    def limit(value):
        number = positive(value)
        if number > policy.page_max:
            raise argparse.ArgumentTypeError(f'limit 最大 {policy.page_max}')
        return number
    def key(value):
        if not re.fullmatch('[0-9a-f]{64}', value):
            raise argparse.ArgumentTypeError('artifact-key 必须为 64 位小写十六进制')
        return value
    def run_id(value):
        if not re.fullmatch('[0-9a-f]{32}', value):
            raise argparse.ArgumentTypeError('run-id 必须为 32 位小写十六进制')
        return value
    parser = argparse.ArgumentParser(description='公告下载台账查询/单文件维护；不发起 PDF 网络请求。')
    parser.add_argument('--output-root', type=Path, default=DownloadOptions.output_root,
                        help='已有外盘归档根；默认 /Volumes/datasource/announcements；置于子命令前')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('summary', help='归档概况及 PG 存储标识（只读）')
    runs = commands.add_parser('runs', help='最近创建的运行/历史原因（只读）')
    runs.add_argument('--limit', type=limit, default=policy.page_default)
    runs.add_argument('--before-rowid', type=positive)
    runs.add_argument('--run-id', type=run_id)
    files = commands.add_parser('files', help='按日期/代码/标题/状态筛选文件（只读）')
    files.add_argument('--limit', type=limit, default=policy.page_default)
    files.add_argument('--start-date', type=iso_date)
    files.add_argument('--end-date', type=iso_date)
    files.add_argument('--ts-code')
    files.add_argument('--title', help='标题包含原文；百分号/下划线按字面匹配')
    files.add_argument('--state', choices=ARTIFACT_STATES)
    files.add_argument('--run-id', type=run_id)
    files.add_argument('--after-key', type=key)
    for name, help_text in [('show','文件及来源记录（只读）'),('verify','现场文件大小/哈希核验（只读）'),
                            ('repair','单文件恢复/整理为可重下状态，保留已有文件，不联网')]:
        child = commands.add_parser(name, help=help_text)
        child.add_argument('--artifact-key', required=True, type=key)
        if name == 'show':
            child.add_argument('--limit', type=limit, default=policy.page_default)
            child.add_argument('--after-rowid', type=positive)
    args = parser.parse_args(argv)
    if (args.command == 'files' and args.start_date and args.end_date and args.start_date > args.end_date):
        parser.error('date_range_reversed')
    return args


def main(argv=None):
    return run_cli(parse_options(argv))


if __name__ == '__main__':
    raise SystemExit(main())
