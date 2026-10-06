"""Query/verify a local announcement archive, or reconcile one explicitly chosen file."""
from __future__ import annotations

import argparse
import json
import re
import signal
import sqlite3
from dataclasses import asdict
from pathlib import Path

from src.scripts.announcement_download.core import Blocked, Cancelled, Control, DownloadOptions, DownloadPolicy, iso_date
from src.scripts.announcement_download.ledger import Ledger
from src.scripts.announcement_download.maintenance import (
    ARTIFACT_STATES, LedgerQuery, LedgerQueryPolicy, repair_one, verify_one,
)
from src.scripts.announcement_download.volume import SourceVolume, Volume, no_symlinks


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
    commands.add_parser('summary', help='归档概况及实际台账路径（只读）')
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
    args = parse_options(argv)
    policy, query_policy = DownloadPolicy(), LedgerQueryPolicy()
    control = Control(policy)
    volume = SourceVolume(args.output_root, policy)
    ledger = None
    old_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda *_: control.stop.set())
    def emit(**result):
        print(json.dumps(result, ensure_ascii=False), flush=True)
    try:
        volume.open()
        volume.assert_archive_path()
        path = volume.ledger_path()
        no_symlinks(path)
        ledger = Ledger(path, volume.volume_uuid, volume.relative_root, read_only=True)
        query = LedgerQuery(ledger, control, query_policy)
        context = dict(command=args.command, output_root=str(volume.output), ledger_path=str(path),
                       schema_version=query.version, policy=asdict(query_policy))
        if args.command == 'summary':
            result = query.summary()
        elif args.command == 'runs':
            result = query.runs(args.limit, args.before_rowid, args.run_id)
        elif args.command == 'files':
            result = query.files(args.limit, **{key:getattr(args,key) for key in (
                'start_date','end_date','ts_code','title','state','run_id','after_key')})
        elif args.command == 'show':
            result = query.show(args.artifact_key, args.limit, args.after_rowid)
        else:
            task = query.artifact(args.artifact_key)
            # Hashing/promoting a PDF must not keep a SQLite read transaction open.
            ledger.close(); ledger = None
            if args.command == 'verify':
                result = verify_one(task, volume, policy, control)
            else:
                control.check()
                prior_identity = volume.volume_uuid, volume.relative_root
                volume.close()
                volume = Volume(args.output_root, policy)
                volume.open()
                if (volume.volume_uuid,volume.relative_root) != prior_identity:
                    raise Blocked('archive_identity_mismatch')
                path = volume.ledger_path()
                no_symlinks(path)
                if not path.is_file():
                    raise Blocked('archive_ledger_missing')
                control.check()
                ledger = Ledger(path, volume.volume_uuid, volume.relative_root)
                result = repair_one(args.artifact_key, volume, ledger, policy, control)
                context['schema_version'] = 2
        if ledger:
            ledger.close(); ledger = None
        control.check()
        volume.assert_valid(full=True)
        emit(**context, result=result)
        if args.command == 'verify':
            return 0 if result['final']['status'] == 'matched' else 1
        if args.command == 'repair' and result['outcome'] == 'failed':
            return 1
        return 0
    except Cancelled:
        emit(command=args.command, error='user_cancelled')
        return 130
    except (Blocked, OSError, sqlite3.Error, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
        emit(command=args.command, error=reason)
        return 3
    finally:
        if ledger:
            ledger.close()
        volume.close()
        control.close()
        signal.signal(signal.SIGINT, old_handler)


if __name__ == '__main__':
    raise SystemExit(main())
