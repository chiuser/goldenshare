"""Explicit cleanup of the five migrated SQLite files, never a runtime fallback."""
from contextlib import ExitStack
import os
from pathlib import Path
import stat
import subprocess

from sqlalchemy import text

from src.foundation.clients.announcement_archive.core import Blocked
from src.foundation.clients.announcement_archive.locking import ExecutionLock
from src.foundation.clients.announcement_archive.migration_source import LegacyCatalog, LegacyLedger, opened, fingerprint
from src.foundation.clients.announcement_archive.volume import no_symlinks
from src.foundation.dao.announcement_archive.pg_archive import ArchiveDAO
from src.foundation.dao.announcement_archive.pg_schema import LEDGER_TABLES, validate_schema


def require_closed_files(paths):
    result = subprocess.run(['/usr/sbin/lsof', '-Fpn', '--', *map(str, paths)],
                            capture_output=True, text=True, timeout=3)
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise Blocked('migration_open_files_check_failed')
    pid = None
    names = set(map(str, paths))
    for line in result.stdout.splitlines():
        if line.startswith('p'):
            pid = int(line[1:])
        elif line.startswith('n') and line[1:] in names and pid != os.getpid():
            raise Blocked('migration_sources_still_open')


def file_facts(path):
    no_symlinks(path)
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise Blocked('migration_source_unsafe')
    return dict(path=str(path), device=info.st_dev, inode=info.st_ino, size=info.st_size,
                modified_ns=info.st_mtime_ns, changed_ns=info.st_ctime_ns)


class ArchiveCleanup:
    def __init__(self, migration, *, closed_files=require_closed_files):
        self.migration, self.closed_files = migration, closed_files
        self.db, self.control, self.inventory = migration.db, migration.control, migration.inventory

    def run(self, *, cleanup=False):
        paths = (*self.inventory.ledgers, self.inventory.catalog)
        if (len(self.inventory.ledgers) != 4 or len(set(paths)) != 5
                or any(p.name != 'downloads.sqlite' for p in self.inventory.ledgers)
                or self.inventory.catalog.name != 'catalog.sqlite'):
            raise Blocked('migration_cleanup_inventory_invalid')
        with ExitStack() as stack:
            if cleanup:
                lock = ExecutionLock(self.inventory.catalog.parent / 'catalog-writer.lock').open()
                stack.callback(lock.close)
            catalog = stack.enter_context(opened(LegacyCatalog(self.inventory.catalog, self.control, self.db.policy)))
            sources = [stack.enter_context(opened(LegacyLedger(p, self.control, self.db.policy))) for p in self.inventory.ledgers]
            catalog.validate_archives([s.archive_id for s in sources], sources[0].archive_id)
            for source in sources:
                stack.enter_context(self.migration.guard(source, self.inventory.mount, apply=cleanup, policy=self.db.policy))
            with self.db.transaction(read_only=True) as conn:
                validate_schema(conn)
                anchor = conn.scalar(text('SELECT installed_at FROM announcement_archive.schema_info WHERE singleton=1'))
            for source in sources:
                self.verify_import(source, catalog, anchor)
            source_hashes = {str(s.path): s.sha256 for s in (*sources, catalog)}
            for source in (*sources, catalog):
                source.assert_unchanged()
                source.close()
            manifest = []
            # Companions before the main file; no parent directories, locks or binding are removed.
            for path in paths:
                for suffix in ('-shm', '-journal', '-wal', ''):
                    candidate = Path(str(path) + suffix)
                    no_symlinks(candidate)
                    if candidate.exists():
                        manifest.append(file_facts(candidate))
            self.closed_files([Path(f['path']) for f in manifest])
            for path, digest in source_hashes.items():
                if fingerprint(Path(path), self.control) != digest:
                    raise Blocked('migration_source_changed')
            result = dict(phase='cleanupPlanned', files=manifest, source_sha256=source_hashes,
                          target=dict(database=self.db.policy.database, schema=self.db.policy.schema),
                          bytes=sum(f['size'] for f in manifest), source_http_requests=0)
            if not cleanup:
                return result
            # Recheck all source hashes and path identities before the first unlink.
            for facts in manifest:
                if file_facts(Path(facts['path'])) != facts:
                    raise Blocked('migration_source_changed')
            removed = []
            for facts in manifest:
                self.control.check()
                path = Path(facts['path'])
                no_symlinks(path.parent)
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    if file_facts(path) != facts:
                        raise Blocked('migration_source_changed')
                    os.unlink(path.name, dir_fd=directory)
                    os.fsync(directory)
                finally:
                    os.close(directory)
                removed.append(str(path))
                self.control.update(phase='cleaningLegacy', filesRemoved=len(removed),
                                    filesTotal=len(manifest), currentFile=str(path))
            return dict(result, phase='cleaned', removed=removed)

    def verify_import(self, source, catalog, anchor):
        with self.db.transaction(read_only=True) as conn:
            dao = ArchiveDAO(conn, source.archive_id)
            archive = dao.get('archives', {})
            if (archive['source_schema_version'] != source.version
                    or archive['created_at'] != source.archive['created_at']
                    or not archive['import_completed_at']):
                raise Blocked('migration_cleanup_import_incomplete')
        tables = {t: (source, source.facts(t)) for t in LEDGER_TABLES}
        tables.update({t: (catalog, catalog.facts(t, source.archive_id, anchor, archive['import_completed_at']))
                       for t in ('query_snapshots', 'previews')})
        with self.db.transaction(read_only=True) as conn:
            dao = ArchiveDAO(conn, source.archive_id)
            checkpoints = list(conn.execute(text('SELECT source_table FROM announcement_archive.migration_checkpoints '
                'WHERE archive_id=:a'), dict(a=source.archive_id)).scalars())
            if set(checkpoints) != set(tables):
                raise Blocked('migration_cleanup_import_incomplete')
            for table, (reader, facts) in tables.items():
                checkpoint = dao.get('migration_checkpoints', dict(source_table=table))
                self.migration.check_checkpoint(checkpoint, reader, facts)
                if (checkpoint['state'] != 'completed' or checkpoint['rows_committed'] != facts['rows_total']
                        or checkpoint['rows_digest'] != facts['rows_digest']):
                    raise Blocked('migration_cleanup_import_incomplete')
                # Native runtime may add rows or update files; old query/preview controls may be GC'd.
                if table in LEDGER_TABLES and dao.count(table) < facts['rows_total']:
                    raise Blocked('migration_cleanup_import_incomplete')
