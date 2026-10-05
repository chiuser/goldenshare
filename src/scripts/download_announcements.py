"""Download existing announcement URLs to a verified external macOS volume.

Run from the repository with its existing Python environment. No production writes.
"""
from __future__ import annotations

import argparse
import signal
import sqlite3
from pathlib import Path

from src.scripts.announcement_download.core import (
    Blocked, Cancelled, Control, DownloadOptions, DownloadPolicy, FileFailed, iso_date,
)
from src.scripts.announcement_download.files import Files
from src.scripts.announcement_download.http import Downloader
from src.scripts.announcement_download.ledger import Ledger
from src.scripts.announcement_download.source import Source
from src.scripts.announcement_download.volume import Volume


def parse_options(argv=None) -> DownloadOptions:
    parser = argparse.ArgumentParser(description='从 DG Raw 读取公告并本地归档 PDF；重复相同日期命令可续跑。')
    parser.add_argument('--start-date', required=True, type=iso_date, help='ann_date 起始日 YYYY-MM-DD（包含）')
    parser.add_argument('--end-date', required=True, type=iso_date, help='ann_date 结束日 YYYY-MM-DD（包含）')
    parser.add_argument('--interval-seconds', type=float, default=DownloadOptions.interval_seconds,
                        help='请求结束后等待秒数；默认 5，支持小数及 debug 用的 0')
    parser.add_argument('--output-root', type=Path, default=DownloadOptions.output_root,
                        help='默认 /Volumes/datasource/announcements，必须在已挂载外盘内')
    args = parser.parse_args(argv)
    try:
        return DownloadOptions(**vars(args))
    except ValueError as exc:
        parser.error(str(exc))


def execute(options, policy, control, volume, ledger, source, scope, client=None, clock=None) -> int:
    """Dependency injection lets isolated tests exercise the same production run loop."""
    run = ledger.begin_run(options, scope, policy)
    downloader = None
    active_key = None
    try:
        control.update(phase='enumerating', start_date=str(options.start_date), end_date=str(options.end_date),
                       interval_seconds=options.interval_seconds, source_kind='dg_raw_parquet', source_scope=scope,
                       records=0, total=None, percent=None)
        control.check()
        volume.assert_valid(full=True)
        for day in source.iter_days():
            ledger.begin_day(run, day.day)
            control.update(**ledger.stats(run), footer_count=None, records_committed=0)
            with day:
                ledger.describe_day(run, day.day, day.facts)
                control.update(footer_count=day.facts['footer_count'], records_committed=0)
                committed = 0
                for rows in day:
                    control.check()
                    volume.assert_valid(full=True)
                    ledger.ingest(run, scope, day.day, rows, policy.batch_size)
                    committed += len(rows)
                    control.update(**ledger.stats(run), records_committed=committed)
                    del rows
                    control.check()
                facts = day.verify()
                control.check()
                volume.assert_valid(full=True)
                ledger.complete_day(run, day.day, facts)
                control.update(**ledger.stats(run))
        control.check()
        ledger.seal(run)
        files = Files(volume, ledger, policy, control)
        kwargs = {'clock': clock} if clock else {}
        downloader = Downloader(ledger, files, volume, options, policy, control, client=client, **kwargs)
        control.update(phase='downloading', source_stage=None, **ledger.stats(run))
        while task := ledger.next_task(run):
            control.check()
            volume.assert_valid(full=True)
            source.assert_valid(full=True)
            active_key = task['artifact_key']
            control.update(ts_code=task['ts_code'], title=task['title'], ann_date=task['ann_date'], error=None)
            try:
                task = files.allocate(task)
                outcome = files.recover(task)
                if outcome is None:
                    task = ledger.artifact(task['artifact_key'])
                    downloader.download(run, task)
                    outcome = 'succeeded'
                ledger.result(run, task['artifact_key'], outcome)
            except FileFailed as exc:
                ledger.state(task['artifact_key'], 'failed', str(exc))
                ledger.result(run, task['artifact_key'], 'failed')
                control.update(error=str(exc))
            control.update(**ledger.stats(run))
            active_key = None
        failed = ledger.stats(run)['failed']
        terminal = 'partial_failed' if failed else 'completed'
        ledger.phase(run, terminal)
        control.update(phase=terminal, **ledger.stats(run))
        return 1 if failed else 0
    except Cancelled:
        try:
            ledger.phase(run, 'cancelled', 'user_cancelled')
        except sqlite3.Error:
            pass
        try:
            stats = ledger.stats(run)
        except sqlite3.Error:
            stats = {}
        control.update(phase='cancelled', **stats)
        return 130
    except (Blocked, OSError, sqlite3.Error) as exc:
        reason = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
        # Best effort observation must not delete already committed PDFs.
        try:
            if active_key and ledger.artifact(active_key)['state'] not in ('prepared', 'succeeded'):
                ledger.state(active_key, 'blocked', reason)
            ledger.phase(run, 'blocked', reason)
        except sqlite3.Error:
            pass
        control.update(phase='blocked', error=reason)
        return 3
    finally:
        if downloader:
            downloader.close()
        source.close()


def main(argv=None) -> int:
    options = parse_options(argv)
    policy = DownloadPolicy()
    control = Control(policy)
    volume = Volume(options.output_root, policy)
    ledger = source = None
    old_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda *_: control.stop.set())
    control.start()
    try:
        # Verify both external anchors before opening the ledger or reading Raw.
        volume.open()
        control.check()
        source = Source(options, policy, control).open()
        ledger = Ledger(volume.ledger_path(), volume.volume_uuid, volume.relative_root)
        return execute(options, policy, control, volume, ledger, source, source.scope)
    except Cancelled:
        control.update(phase='cancelled')
        return 130
    except (Blocked, OSError, sqlite3.Error, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
        control.update(phase='startup_failed', error=reason)
        return 2
    finally:
        if source:
            source.close()
        if ledger:
            ledger.close()
        volume.close()
        control.close()
        signal.signal(signal.SIGINT, old_handler)


if __name__ == '__main__':
    raise SystemExit(main())
