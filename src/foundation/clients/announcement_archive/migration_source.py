"""Read-only, bounded snapshots of the explicitly selected legacy SQLite files."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import time

from .core import Blocked, identity
from .volume import no_symlinks
from src.foundation.dao.announcement_archive.legacy_schema import LegacyLedgerSchema
from src.foundation.dao.announcement_archive.pg_schema import LEDGER_TABLES, TABLES
from src.foundation.config.announcement_archive import ArchiveDatabasePolicy, DataCenterPolicy

TERMINAL = {'completed', 'partial_failed', 'cancelled', 'blocked', 'stopped', 'interrupted'}


def fingerprint(path, control):
    manifest = []
    for suffix in ('', '-wal'):
        filename = Path(str(path) + suffix)
        no_symlinks(filename)
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            if suffix:
                manifest.append([suffix, None])
                continue
            raise Blocked('migration_source_missing') from None
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise Blocked('migration_source_unsafe')
            sha = hashlib.sha256()
            while chunk := os.read(fd, 1024 * 1024):
                control.check()
                sha.update(chunk)
            after = os.fstat(fd)
            def facts(info):
                return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
            if (facts(before) != facts(after) or facts(os.stat(filename, follow_symlinks=False)) != facts(after)):
                raise Blocked('migration_source_changed')
            manifest.append([suffix, sha.hexdigest()])
        finally:
            os.close(fd)
    return identity(manifest)


def extend_digest(previous, row):
    # JSON preserves NULL versus empty text, and all strings verbatim. Types are mapped explicitly.
    value = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return identity([previous, value])


EMPTY_DIGEST = identity([])


def default_value(definition):
    value = definition['default']
    if value is None:
        return None
    if value.startswith("'"):
        return value[1:-1].replace("''", "'")
    return float(value) if definition['type'] == 'DOUBLE PRECISION' else int(value)


class SQLiteSource:
    def __init__(self, path, control, policy=ArchiveDatabasePolicy()):
        self.path, self.control = Path(path).absolute(), control
        self.policy = policy
        self.conn = None

    def open(self):
        no_symlinks(self.path)
        journal = Path(str(self.path) + '-journal')
        no_symlinks(journal)
        if journal.exists() and journal.stat().st_size:
            raise Blocked('migration_source_hot_journal')
        # Opening read-only WAL without its shared-memory file can create it; never do so.
        wal, shm = Path(str(self.path) + '-wal'), Path(str(self.path) + '-shm')
        no_symlinks(shm)
        if wal.exists() and not shm.is_file():
            raise Blocked('migration_wal_shared_memory_missing')
        self.sha256 = fingerprint(self.path, self.control)
        try:
            self.conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=1)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute('PRAGMA query_only=ON')
            self.conn.execute('BEGIN')
        except sqlite3.Error:
            self.close()
            raise Blocked('migration_source_invalid') from None
        self.assert_unchanged()
        return self

    def assert_unchanged(self):
        journal = Path(str(self.path) + '-journal')
        if journal.exists() and journal.stat().st_size:
            raise Blocked('migration_source_hot_journal')
        if fingerprint(self.path, self.control) != self.sha256:
            raise Blocked('migration_source_changed')

    def query(self, sql, params=()):
        deadline = time.monotonic() + self.policy.statement_milliseconds / 1000
        self.conn.set_progress_handler(lambda: int(self.control.stop.is_set() or time.monotonic() >= deadline), 1000)
        try:
            self.control.check()
            rows = self.conn.execute(sql, params).fetchall()
            self.control.check()
            if time.monotonic() >= deadline:
                raise Blocked('migration_source_timeout')
            return rows
        except sqlite3.Error:
            self.control.check()
            raise Blocked('migration_source_invalid') from None
        finally:
            self.conn.set_progress_handler(None, 0)

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


class LegacyLedger(SQLiteSource):
    def open(self):
        try:
            super().open()
            archives = self.query('SELECT * FROM archive')
            if len(archives) != 1:
                raise Blocked('archive_schema_invalid')
            self.archive = dict(archives[0])
            self.version = self.archive['schema_version']
            if self.version not in (2, 3):
                raise Blocked('archive_schema_version_unsupported')
            # Reuse exact legacy validation, not its writer constructor or upgrade path.
            reader = object.__new__(LegacyLedgerSchema)
            reader.conn = self.conn
            reader._validate_schema(self.version)
            root = PurePosixPath(self.archive['root_relative_path'])
            if (root.is_absolute() or '..' in root.parts or not root.parts or root.parts[0] != 'announcements'
                    or str(root) != self.archive['root_relative_path']):
                raise Blocked('archive_identity_mismatch')
            self.archive_id = identity([self.archive['volume_uuid'], str(root)])
            if self.path.parent.name != self.archive_id:
                raise Blocked('archive_identity_mismatch')
            if self.query("SELECT 1 FROM runs WHERE phase NOT IN (?,?,?,?,?,?) LIMIT 1", tuple(sorted(TERMINAL))):
                raise Blocked('migration_active_run')
            if self.version == 3:
                if self.query("SELECT 1 FROM archive_execution WHERE active_run_id IS NOT NULL LIMIT 1"):
                    raise Blocked('migration_active_run')
                if self.query("SELECT 1 FROM runs WHERE check_state='checking' LIMIT 1"):
                    raise Blocked('migration_active_check')
            if self.query('SELECT 1 FROM cooldown WHERE request_in_flight<>0 LIMIT 1'):
                raise Blocked('migration_request_in_flight')
            self.assert_unchanged()
            return self
        except BaseException:
            self.close()
            raise

    def count(self, table):
        if table not in LEDGER_TABLES:
            raise ValueError('migration_table_invalid')
        if self.version == 2 and table in ('archive_execution', 'attempt_log', 'run_sessions', 'command_receipts'):
            return int(table == 'archive_execution')
        return self.query(f'SELECT count(*) FROM {table}')[0][0]

    def batch(self, table, after=0, limit=500):
        if table not in LEDGER_TABLES or not 1 <= limit <= 500:
            raise ValueError('migration_batch_invalid')
        if self.version == 2 and table in ('archive_execution', 'attempt_log', 'run_sessions', 'command_receipts'):
            raw = [dict(_source_rowid=1)] if table == 'archive_execution' and after < 1 else []
        else:
            raw = [dict(r) for r in self.query(f'SELECT rowid AS _source_rowid,* FROM {table} '
                                             'WHERE rowid>? ORDER BY rowid LIMIT ?', (after, limit))]
        return [(r['_source_rowid'], self.map_row(table, r)) for r in raw]

    def map_row(self, table, raw):
        output = {}
        for name, definition in TABLES[table]['columns'].items():
            value = (self.archive_id if name == 'archive_id' else raw['_source_rowid'] if name == 'row_seq'
                     else raw[name] if name in raw else default_value(definition))
            if value is None:
                if not definition['nullable']:
                    raise Blocked('migration_source_null_key')
            elif definition['type'] == 'TEXT':
                if not isinstance(value, str):
                    raise Blocked('migration_source_type')
            elif definition['type'] == 'BIGINT':
                if type(value) is not int or not -(2**63) <= value < 2**63:
                    raise Blocked('migration_source_type')
            else:
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise Blocked('migration_source_type')
                value = float(value)
            output[name] = value
        return output

    def facts(self, table):
        digest, after, count = EMPTY_DIGEST, 0, 0
        while batch := self.batch(table, after):
            for rowid, row in batch:
                digest = extend_digest(digest, row)
                after, count = rowid, count + 1
        return dict(rows_total=count, rows_digest=digest)


class LegacyCatalog(SQLiteSource):
    def open(self):
        try:
            super().open()
            from src.foundation.dao.announcement_archive.catalog import LegacyCatalogSchema
            meta = self.query('SELECT * FROM catalog_meta WHERE singleton=1')
            if len(meta) != 1 or meta[0]['schema_version'] != 2:
                raise Blocked('catalog_schema_invalid')
            self.scope = meta[0]['source_scope']
            self.version = 2
            LegacyCatalogSchema(self.scope).validate(self.conn)
            self.assert_unchanged()
            return self
        except BaseException:
            self.close()
            raise

    def validate_archives(self, archive_ids, default_id):
        self.archive_ids, self.default_id = set(archive_ids), default_id
        for table in ('query_snapshots', 'previews'):
            for row in self.query(f'SELECT DISTINCT archive_identity FROM {table}'):
                if row[0] is not None and row[0] not in self.archive_ids:
                    raise Blocked('migration_catalog_archive_unknown')

    def batch(self, table, archive_id, anchor, *, after=0, completed_at=None):
        from datetime import datetime, timezone
        if table not in ('query_snapshots', 'previews'):
            raise ValueError('migration_table_invalid')
        rows = self.query(f'SELECT rowid AS _source_rowid,* FROM {table} WHERE rowid>? '
            'AND (archive_identity=? OR (archive_identity IS NULL AND ?=?)) ORDER BY rowid LIMIT 500',
            (after, archive_id, archive_id, self.default_id))
        expiry = (datetime.fromisoformat(completed_at).replace(tzinfo=timezone.utc).timestamp()
                  + DataCenterPolicy.ttl_seconds) if completed_at else None
        output = []
        for r in rows:
            common = dict(archive_id=archive_id, source_scope=self.scope, state='error', source_version=None,
                          expires_at=expiry, owner_token=None)
            if table == 'query_snapshots':
                total = self.query('SELECT SUM(match_count) FROM query_day_counts WHERE query_id=?', (r['query_id'],))[0][0]
                row = dict(common, query_id=r['query_id'], conditions=r['conditions'], total=total,
                    status_available=r['status_available'] or 0, created_at=r['created_at'], updated_at=r['updated_at'],
                    checked_at=r['checked_at'], reason='DC_QUERY_CONTEXT_CHANGED', preparation_stage='readingSource',
                    dates_total=r['dates_total'], dates_scanned=r['dates_scanned'], records_scanned=r['records_scanned'],
                    artifacts_checked=r['artifacts_checked'])
            else:
                from datetime import date
                if not r['start_date'] or not r['end_date'] or r['interval_seconds'] is None:
                    raise Blocked('migration_catalog_conditions_invalid')
                try:
                    days_total = (date.fromisoformat(r['end_date'])-date.fromisoformat(r['start_date'])).days+1
                    if days_total <= 0:
                        raise ValueError
                except ValueError:
                    raise Blocked('migration_catalog_conditions_invalid') from None
                row = dict(common, preview_id=r['preview_id'], start_date=r['start_date'], end_date=r['end_date'],
                    interval_seconds=float(r['interval_seconds']), source_scope=r['source_scope'] or self.scope,
                    statistics=r['statistics'], created_at=anchor, updated_at=anchor, reason='DC_PREVIEW_STALE',
                    dates_total=days_total,
                    dates_scanned=0, records_scanned=0)
            output.append((r['_source_rowid'], row))
        return output

    def facts(self, table, archive_id, anchor, completed_at=None):
        digest, after, count = EMPTY_DIGEST, 0, 0
        while rows := self.batch(table, archive_id, anchor, after=after, completed_at=completed_at):
            for rowid, row in rows:
                digest = extend_digest(digest, row)
                after, count = rowid, count+1
        return dict(rows_total=count, rows_digest=digest)


@contextmanager
def opened(source):
    try:
        yield source.open()
    finally:
        source.close()
