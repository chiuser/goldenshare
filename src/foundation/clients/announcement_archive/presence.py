"""Read-only ledger + safe stat observation. Never hashes or repairs PDFs."""
import os
import stat
import sqlite3
import time
from pathlib import PurePosixPath

from .core import Blocked, identity
from .budget import remaining
from src.foundation.config.announcement_archive import DataCenterPolicy
from src.foundation.dao.announcement_archive.ledger import Ledger


class ArchivePresence:
    def __init__(self, volume, ledger_path, root_relative_path, prefix='',policy=DataCenterPolicy()):
        self.policy=policy
        self.volume, self.path = volume, ledger_path
        self.root_relative_path, self.prefix = root_relative_path, prefix
        self.identity = identity([volume.volume_uuid, root_relative_path])
        self.stat_count = 0

    def assert_valid(self,full=False):
        self.volume.assert_valid(full=full)

    def check(self, keys):
        if len(keys) > 500:
            raise ValueError('presence_batch_limit')
        self.volume.assert_valid()
        if not keys:
            return set()
        if not self.path.exists():
            # A genuinely absent ledger means no succeeded facts; broken links remain unknown.
            if self.path.is_symlink():
                raise Blocked('symlink_path_forbidden')
            return set()
        try:
            ledger = Ledger(self.path,self.volume.volume_uuid,self.root_relative_path,read_only=True,read_timeout_seconds=remaining(self.policy.sql_seconds))
        except sqlite3.Error:
            raise Blocked('archive_presence_unavailable') from None
        try:
            ledger.conn.execute(f'PRAGMA busy_timeout={int(remaining(self.policy.sql_seconds)*1000)}')
            deadline=time.monotonic()+remaining(self.policy.sql_seconds)
            ledger.conn.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
            rows = ledger.conn.execute('SELECT artifact_key,relative_path FROM artifacts WHERE state=\'succeeded\' AND artifact_key IN ('
                                       + ','.join('?' for _ in keys)+')', keys).fetchmany(500)
        except sqlite3.Error:
            raise Blocked('archive_presence_unavailable') from None
        finally:
            ledger.close()
        present = set()
        for key, relative in rows:
            if relative is None:
                raise Blocked('archive_relative_path_missing')
            path = PurePosixPath(relative)
            if path.is_absolute() or '..' in path.parts or not path.parts or '\\' in relative:
                raise Blocked('unsafe_relative_path')
            directory = '/'.join(p for p in (self.prefix,str(path.parent)) if p)
            try:
                with self.volume.directory(directory) as fd:
                    self.stat_count += 1
                    info = os.stat(path.name,dir_fd=fd,follow_symlinks=False)
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_dev != self.volume.device):
                        raise Blocked('unsafe_archive_file')
                present.add(key)
            except FileNotFoundError:
                continue
            except OSError:
                raise Blocked('archive_presence_unavailable') from None
        self.volume.assert_valid()
        return present

    def current_run(self):
        if not self.path.exists():
            return None
        ledger=Ledger(self.path,self.volume.volume_uuid,self.root_relative_path,read_only=True,read_timeout_seconds=remaining(self.policy.sql_seconds))
        try:
            version=ledger.conn.execute("SELECT schema_version FROM archive").fetchone()[0]
            return ledger.conn.execute("SELECT active_run_id FROM archive_execution WHERE singleton=1").fetchone()[0] if version==3 else None
        finally:
            ledger.close()

    def close(self):
        self.volume.close()
