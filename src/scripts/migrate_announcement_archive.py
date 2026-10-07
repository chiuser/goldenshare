"""Explicit announcement SQLite → local PG PLAN/APPLY; never invoked on startup."""
import argparse
import json
import os
import re
import signal
import subprocess

from src.foundation.clients.announcement_archive.core import Blocked, Cancelled, Control, DownloadPolicy
from src.foundation.config.settings import get_settings
from src.foundation.dao.announcement_archive.pg_database import ArchiveDatabase
from src.ops.runtime.announcement_archive.migration import ArchiveMigration


def require_writers_stopped():
    result = subprocess.run(['ps', '-axo', 'pid,args'], capture_output=True, text=True, check=True, timeout=3)
    pattern = re.compile(r'(goldenshare-web|src\.app\.web\.run|src\.scripts\.(download_announcements|announcement_ledger))')
    for line in result.stdout.splitlines()[1:]:
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and int(parts[0]) != os.getpid() and pattern.search(parts[1]):
            raise Blocked('migration_writers_must_stop')


def main(argv=None):
    parser = argparse.ArgumentParser(description='公告台账迁移：默认只读 PLAN；--apply 显式迁移。')
    parser.add_argument('--apply', action='store_true', help='停止公告 Web/CLI 后迁移；保留 SQLite/PDF')
    args = parser.parse_args(argv)
    control = Control(DownloadPolicy())
    old_handler = signal.signal(signal.SIGINT, lambda *_: control.stop.set())
    database = None
    try:
        if args.apply:
            require_writers_stopped()
        database = ArchiveDatabase(get_settings().announcement_archive_database_url)
        result = ArchiveMigration(database, control).run(apply=args.apply)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Cancelled:
        print(json.dumps(dict(code='migration_cancelled', committed_batches_preserved=True)), flush=True)
        return 130
    except (Blocked, OSError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(code=str(error) if isinstance(error, Blocked) else 'migration_dependency_failed')), flush=True)
        return 3
    finally:
        if database:
            database.close()
        signal.signal(signal.SIGINT, old_handler)


if __name__ == '__main__':
    raise SystemExit(main())
