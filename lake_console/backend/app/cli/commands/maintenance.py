from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, print_json, settings_from_args
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


def register_maintenance_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    clean_parser = subparsers.add_parser("clean-tmp", help="审计或清理 Lake Root 下的 _tmp run 目录")
    add_lake_root_arg(clean_parser)
    clean_parser.add_argument("--dry-run", action="store_true", help="只列出候选目录，不删除")
    clean_parser.add_argument("--older-than-hours", default=None, type=float, help="只清理超过指定小时数的 _tmp/{run_id}")
    clean_parser.set_defaults(handler=_handle_clean_tmp)


def _handle_clean_tmp(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    service = TmpCleanupService(settings.lake_root)
    summaries = service.clean(older_than_hours=args.older_than_hours, dry_run=args.dry_run)
    print_json(
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
