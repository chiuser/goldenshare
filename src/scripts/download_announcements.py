"""Stable CLI entry for DG announcement PDF archival."""
from __future__ import annotations
import argparse
from pathlib import Path
from src.foundation.clients.announcement_archive.core import DownloadOptions, iso_date
from src.ops.runtime.announcement_archive.executor import run_cli


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


def main(argv=None) -> int:
    return run_cli(parse_options(argv))


if __name__ == '__main__':
    raise SystemExit(main())
