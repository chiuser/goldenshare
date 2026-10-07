"""Explicit legacy-ledger migration. No application startup or daily sync calls this."""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import fcntl
import math
import os
from pathlib import Path
import stat
import shutil

from sqlalchemy import text

from src.foundation.clients.announcement_archive.core import Blocked, Cancelled, DownloadPolicy, timestamp
from src.foundation.clients.announcement_archive.locking import ExecutionLock
from src.foundation.clients.announcement_archive.migration_source import (
    EMPTY_DIGEST, LegacyCatalog, LegacyLedger, extend_digest, opened,
)
from src.foundation.clients.announcement_archive.volume import SourceVolume
from src.foundation.config.announcement_archive import DataCenterPolicy
from src.foundation.dao.announcement_archive.pg_archive import ArchiveDAO, register_archive
from src.foundation.dao.announcement_archive.pg_schema import (
    LEDGER_TABLES, TABLES, install_schema, schema_exists, validate_schema,
)

DOWNLOAD_IDS = (
    '6ae38d3a5436526b8e6a941086bda5ce366397699eea6d8d59fd598817d7f4f3',
    'ad609a131cad03f5d8de8e09cab84ded264842358993a512f2b289476bfc6c4c',
    'bb28fc7eca37cbf2a513cc48295d82efad9a55fe023853902181bfeabb24bf9f',
    'fe6ce589e8fe2f1d6ad0d572e7e194204edef2daa99bc7a555efec1d7f950013',
)
CATALOG_ID = 'e04b7c92bfa1082f05a370b0504bdfcb29f66fb352fbe82a904a71df1db7b79a'


@dataclass(frozen=True)
class MigrationInventory:
    ledgers: tuple[Path, ...]
    catalog: Path
    mount: Path = Path('/Volumes/datasource')

    @classmethod
    def local(cls):
        base = Path.home() / 'Library/Application Support/Goldenshare'
        return cls(tuple(base / 'announcement-download' / key / 'downloads.sqlite' for key in DOWNLOAD_IDS),
                   base / 'announcement-catalog' / CATALOG_ID / 'catalog.sqlite')


@contextmanager
def archive_guard(source, mount, *, apply, policy):
    """Read-only volume inspection for PLAN; the existing double locks for APPLY."""
    volume = SourceVolume(mount / source.archive['root_relative_path'], DownloadPolicy())
    local_lock = None
    lock_fd = -1
    try:
        volume.open()
        if volume.volume_uuid != source.archive['volume_uuid']:
            raise Blocked('archive_identity_mismatch')
        if apply:
            local_lock = ExecutionLock(source.path.parent / 'execution.lock').open()
            with volume.directory('.state') as directory:
                lock_fd = os.open('archive.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                  0o600, dir_fd=directory)
                info = os.fstat(lock_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise Blocked('unsafe_execution_lock')
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise Blocked('archive_already_running') from None
        volume.assert_valid(full=True)
        yield volume
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        if local_lock:
            local_lock.close()
        volume.close()


class ArchiveMigration:
    def __init__(self, database, control, inventory=None, *, guard=archive_guard):
        self.db, self.control = database, control
        self.inventory = inventory or MigrationInventory.local()
        self.guard = guard
        self.batch_size = database.policy.migration_batch_size
        if not 1 <= self.batch_size <= 500:
            raise ValueError('migration_batch_invalid')

    def run(self, *, apply=False):
        with ExitStack() as stack:
            if apply:
                lock = ExecutionLock(self.inventory.catalog.parent / 'catalog-writer.lock').open()
                stack.callback(lock.close)
            catalog = stack.enter_context(opened(LegacyCatalog(self.inventory.catalog, self.control, self.db.policy)))
            sources = [stack.enter_context(opened(LegacyLedger(path, self.control, self.db.policy))) for path in self.inventory.ledgers]
            if len({s.archive_id for s in sources}) != len(sources) or not sources:
                raise Blocked('migration_inventory_duplicate')
            catalog.validate_archives([s.archive_id for s in sources], sources[0].archive_id)
            volumes = [stack.enter_context(self.guard(s, self.inventory.mount, apply=apply, policy=self.db.policy)) for s in sources]
            plan = self.plan(sources, catalog)
            if not apply:
                return plan
            self.control.check()
            with self.db.transaction() as conn:
                install_schema(conn)
            with self.db.transaction(read_only=True) as conn:
                anchor = conn.scalar(text('SELECT installed_at FROM announcement_archive.schema_info WHERE singleton=1'))
            for source, volume in zip(sources, volumes):
                self.control.check()
                volume.assert_valid(full=True)
                self.apply_archive(source, catalog, anchor, volume)
            with self.db.transaction() as conn:
                for table in ('runs', 'source_records'):
                    conn.execute(text(f"SELECT setval(pg_get_serial_sequence('announcement_archive.{table}','row_seq'),"
                        f"COALESCE((SELECT max(row_seq) FROM announcement_archive.{table}),0)+1,false)"))
            catalog.assert_unchanged()
            for source in sources:
                source.assert_unchanged()
            return dict(plan, phase='completed')

    def plan(self, sources, catalog):
        with self.db.transaction(read_only=True) as conn:
            exists = schema_exists(conn)
            data_directory = conn.scalar(text('SHOW data_directory'))
            if exists:
                validate_schema(conn)
                anchor = conn.scalar(text('SELECT installed_at FROM announcement_archive.schema_info WHERE singleton=1'))
            else:
                anchor = timestamp()
        archives, batches = [], 0
        for source in sources:
            self.control.check()
            tables = {}
            for table in LEDGER_TABLES:
                self.control.update(phase='planning', archive=source.archive_id, table=table,
                                    rowsCommitted=None, rowsTotal=None, lastRowid=None, checkpoint=None)
                facts = source.facts(table)
                if facts['rows_total'] != source.count(table):
                    raise Blocked('migration_source_rowid_invalid')
                tables[table] = facts
                batches += math.ceil(facts['rows_total'] / self.batch_size)
            controls = {t: catalog.facts(t, source.archive_id, anchor) for t in ('query_snapshots', 'previews')}
            batches += sum(math.ceil(f['rows_total'] / 500) for f in controls.values())
            if exists:
                self.check_existing(source, tables)
                self.check_catalog_existing(source.archive_id, catalog, anchor)
            source.assert_unchanged()
            archives.append(dict(archive_id=source.archive_id, source_path=str(source.path),
                source_schema_version=source.version, source_sha256=source.sha256, tables=tables, expired_controls=controls))
        catalog.assert_unchanged()
        controls = {t: catalog.query(f'SELECT count(*) FROM {t}')[0][0] for t in ('query_snapshots', 'previews')}
        required_bytes = sum(s.path.stat().st_size for s in sources)*3
        available_bytes = shutil.disk_usage(data_directory).free
        if required_bytes > available_bytes:
            raise Blocked('migration_target_disk_space_insufficient')
        return dict(phase='planned', target=dict(database=self.db.policy.database, schema=self.db.policy.schema),
            schema_exists=exists, archives=archives, catalog=dict(source_path=str(catalog.path),
                source_sha256=catalog.sha256, expired_controls=controls, copied_metadata_rows=0),
            expected_batches=batches, estimated_target_bytes=required_bytes, available_target_bytes=available_bytes,
            conflicts=0, batch_size=self.batch_size)

    def check_existing(self, source, tables):
        with self.db.transaction(read_only=True) as conn:
            dao = ArchiveDAO(conn, source.archive_id, require_ready=False)
            archive = dao.get('archives', {})
            if archive is None:
                return
            if archive['source_schema_version'] != source.version or archive['created_at'] != source.archive['created_at']:
                raise Blocked('archive_migration_conflict')
            for table, facts in tables.items():
                cp = dao.get('migration_checkpoints', {'source_table': table})
                if cp:
                    self.check_checkpoint(cp, source, facts)
                if dao.count(table) > facts['rows_total']:
                    raise Blocked('archive_migration_conflict')
                if archive['import_state'] == 'ready' and (not cp or cp['state'] != 'completed'
                        or dao.count(table) != facts['rows_total']):
                    raise Blocked('migration_reconciliation_failed')
        # Read source batches outside PG transactions. Missing rows are expected during resume.
        for table in LEDGER_TABLES:
            after, matched = 0, 0
            self.control.update(phase='checkingTarget', archive=source.archive_id, table=table)
            while batch := source.batch(table, after, self.batch_size):
                rows = [row for _, row in batch]
                with self.db.transaction(read_only=True) as conn:
                    dao = ArchiveDAO(conn, source.archive_id, require_ready=False)
                    current = dao.matching(table, rows)
                    keys = {tuple(r[k] for k in TABLES[table]['primary_key']): r for r in rows}
                    if any(keys.get(tuple(r[k] for k in TABLES[table]['primary_key'])) != r for r in current):
                        raise Blocked('archive_migration_conflict')
                    matched += len(current)
                after = batch[-1][0]
            with self.db.transaction(read_only=True) as conn:
                if ArchiveDAO(conn, source.archive_id, require_ready=False).count(table) != matched:
                    raise Blocked('archive_migration_conflict')

    def check_catalog_existing(self, aid, catalog, anchor):
        with self.db.transaction(read_only=True) as conn:
            archive = ArchiveDAO(conn, aid, require_ready=False).get('archives', {})
        if not archive:
            return
        completed = archive['import_completed_at']
        for table in ('query_snapshots', 'previews'):
            facts = catalog.facts(table, aid, anchor, completed)
            with self.db.transaction(read_only=True) as conn:
                dao = ArchiveDAO(conn, aid, require_ready=False)
                cp = dao.get('migration_checkpoints', {'source_table': table})
                if cp:
                    self.check_checkpoint(cp, catalog, facts)
            after, matched = 0, 0
            while batch := catalog.batch(table, aid, anchor, after=after, completed_at=completed):
                expected = {tuple(r[k] for k in TABLES[table]['primary_key']): r for _, r in batch}
                with self.db.transaction(read_only=True) as conn:
                    rows = ArchiveDAO(conn, aid, require_ready=False).matching(table, [r for _, r in batch])
                for row in rows:
                    if not completed:
                        row['expires_at'] = None  # Unpublished expiry updates are restartable staging only.
                    if expected.get(tuple(row[k] for k in TABLES[table]['primary_key'])) != row:
                        raise Blocked('archive_migration_conflict')
                matched += len(rows)
                after = batch[-1][0]
            with self.db.transaction(read_only=True) as conn:
                if ArchiveDAO(conn, aid, require_ready=False).count(table) != matched:
                    raise Blocked('archive_migration_conflict')

    @staticmethod
    def check_checkpoint(cp, source, facts):
        if any(cp[k] != expected for k, expected in dict(source_path=str(source.path), source_sha256=source.sha256,
            source_schema_version=source.version, rows_total=facts['rows_total']).items()):
            raise Blocked('migration_checkpoint_source_changed')

    def apply_archive(self, source, catalog, anchor, volume):
        aid = source.archive_id
        with self.db.transaction() as conn:
            dao = register_archive(conn, source.archive['volume_uuid'], source.archive['root_relative_path'],
                                   source_version=source.version, created_at=source.archive['created_at'])
            archive = dao.get('archives', {})
        completed = archive['import_completed_at']
        try:
            if not completed:
                self.reset_control_expiry(aid)
            for table in LEDGER_TABLES:
                batch = lambda after, t=table: source.batch(t, after, self.batch_size)
                self.copy_table(source, aid, table, source.facts(table), batch, volume)
            for table in ('query_snapshots', 'previews'):
                batch = lambda after, t=table: catalog.batch(t, aid, anchor, after=after, completed_at=completed)
                self.copy_table(catalog, aid, table, catalog.facts(table, aid, anchor, completed), batch, volume)
            self.verify_references(aid)
            source.assert_unchanged(); catalog.assert_unchanged(); volume.assert_valid(full=True)
            if not completed:
                self.finish_archive(aid, catalog, anchor)
        except (Blocked, Cancelled):
            # Diagnostic state is independent of the already committed business batches.
            try:
                with self.db.transaction() as conn:
                    conn.execute(text("UPDATE announcement_archive.migration_checkpoints SET state=:state,updated_at=:now "
                        "WHERE archive_id=:a AND state<>'completed'"), dict(a=aid,
                            state='cancelled' if self.control.stop.is_set() else 'failed', now=timestamp()))
            except Blocked:
                pass
            raise

    def copy_table(self, source, aid, table, facts, batch_reader, volume):
        with self.db.transaction() as conn:
            dao = ArchiveDAO(conn, aid, require_ready=False)
            cp = dao.get('migration_checkpoints', {'source_table': table}, lock=True)
            if cp:
                self.check_checkpoint(cp, source, facts)
            else:
                cp = dict(archive_id=aid, source_table=table, source_path=str(source.path),
                    source_sha256=source.sha256, source_schema_version=source.version, last_rowid=0,
                    rows_committed=0, rows_total=facts['rows_total'], rows_digest=EMPTY_DIGEST,
                    state='pending', updated_at=timestamp())
                dao.insert_identical('migration_checkpoints', [cp])
        # Verify every existing prefix, including the digest and physical target rows, before extending it.
        after, count, digest = 0, 0, EMPTY_DIGEST
        while batch := batch_reader(after):
            self.control.check(); source.assert_unchanged(); volume.assert_valid()
            rows = [row for _, row in batch]
            boundary = batch[-1][0]
            for rowid, row in batch:
                digest = extend_digest(digest, row)
                count += 1
                if rowid == cp['last_rowid'] and (count != cp['rows_committed'] or digest != cp['rows_digest']):
                    raise Blocked('migration_checkpoint_invalid')
            if boundary <= cp['last_rowid']:
                with self.db.transaction(read_only=True) as conn:
                    ArchiveDAO(conn, aid, require_ready=False).verify_identical(table, rows)
            else:
                # A persisted checkpoint must end on a batch boundary.
                if batch[0][0] <= cp['last_rowid']:
                    raise Blocked('migration_checkpoint_invalid')
                values = dict(last_rowid=boundary, rows_committed=count, rows_digest=digest,
                    state='completed' if count == facts['rows_total'] else 'copying', updated_at=timestamp())
                with self.db.transaction() as conn:
                    dao = ArchiveDAO(conn, aid, require_ready=False)
                    dao.insert_identical(table, rows)
                    if dao.update('migration_checkpoints', {'source_table': table}, values,
                                  expected={'last_rowid': cp['last_rowid'], 'rows_digest': cp['rows_digest']}) != 1:
                        raise Blocked('migration_checkpoint_conflict')
                cp.update(values)
            after = boundary
            self.control.update(phase='migrating', archive=aid, table=table, rowsCommitted=cp['rows_committed'], rowsVerified=count,
                rowsTotal=facts['rows_total'], lastRowid=after, checkpoint=cp['state'])
            self.control.check()
        if count != facts['rows_total'] or digest != facts['rows_digest'] or cp['last_rowid'] != after:
            raise Blocked('migration_reconciliation_failed')
        with self.db.transaction() as conn:
            dao = ArchiveDAO(conn, aid, require_ready=False)
            if dao.count(table) != count:
                raise Blocked('migration_reconciliation_failed')
            dao.update('migration_checkpoints', {'source_table': table}, dict(state='completed', updated_at=timestamp()))
        self.control.update(phase='migrating', archive=aid, table=table, rowsCommitted=count,
                            rowsVerified=count, rowsTotal=count, lastRowid=after, checkpoint='completed')

    def verify_references(self, aid):
        links = [('source_records', 'artifact_key', 'artifacts', 'artifact_key'),
            ('source_records', 'first_seen_run', 'runs', 'run_id'), ('source_records', 'last_seen_run', 'runs', 'run_id'),
            ('run_artifacts', 'run_id', 'runs', 'run_id'), ('run_artifacts', 'artifact_key', 'artifacts', 'artifact_key'),
            ('run_source_days', 'run_id', 'runs', 'run_id'), ('attempt_log', 'run_id', 'runs', 'run_id'),
            ('attempt_log', 'artifact_key', 'artifacts', 'artifact_key'), ('run_sessions', 'run_id', 'runs', 'run_id'),
            ('command_receipts', 'result_run_id', 'runs', 'run_id'), ('artifacts', 'created_run_id', 'runs', 'run_id'),
            ('runs', 'parent_run_id', 'runs', 'run_id'), ('runs', 'retry_of_run_id', 'runs', 'run_id')]
        with self.db.transaction(read_only=True) as conn:
            for child, column, parent, key in links:
                invalid = conn.scalar(text(f'SELECT 1 FROM announcement_archive.{child} c '
                    f'WHERE c.archive_id=:a AND c.{column} IS NOT NULL AND NOT EXISTS('
                    f'SELECT 1 FROM announcement_archive.{parent} p WHERE p.archive_id=c.archive_id AND p.{key}=c.{column}) LIMIT 1'), {'a': aid})
                if invalid:
                    raise Blocked('migration_reference_invalid')

    def finish_archive(self, aid, catalog, anchor):
        from datetime import datetime
        # Expired controls are small rows only. Updating their expiry stays bounded and resumable.
        completed = timestamp()
        expiry = datetime.fromisoformat(completed).timestamp() + DataCenterPolicy.ttl_seconds
        for table, key in [('query_snapshots', 'query_id'), ('previews', 'preview_id')]:
            after = ''
            while True:
                self.control.check()
                with self.db.transaction() as conn:
                    ids = list(conn.scalars(text(f'SELECT {key} FROM announcement_archive.{table} '
                        f'WHERE archive_id=:a AND {key}>:after ORDER BY {key} LIMIT 500'), dict(a=aid, after=after)))
                    if not ids:
                        break
                    conn.execute(text(f'UPDATE announcement_archive.{table} SET expires_at=:expiry '
                        f'WHERE archive_id=:a AND {key}=ANY(:ids)'), dict(a=aid, ids=ids, expiry=expiry))
                    after = ids[-1]
        self.control.check()
        final_facts = {}
        for table in ('query_snapshots', 'previews'):
            facts = catalog.facts(table, aid, anchor, completed)
            final_facts[table] = facts
            after = 0
            while rows := catalog.batch(table, aid, anchor, after=after, completed_at=completed):
                with self.db.transaction(read_only=True) as conn:
                    ArchiveDAO(conn, aid, require_ready=False).verify_identical(table, [r for _, r in rows])
                after = rows[-1][0]
        catalog.assert_unchanged()
        self.control.check()
        # Publishing readiness and final control digests is one atomic short transaction.
        with self.db.transaction() as conn:
            dao = ArchiveDAO(conn, aid, require_ready=False)
            for table, facts in final_facts.items():
                dao.update('migration_checkpoints', {'source_table': table},
                    dict(rows_digest=facts['rows_digest'], state='completed', updated_at=completed))
            dao.update('archives', {}, dict(import_state='ready', import_completed_at=completed))

    def reset_control_expiry(self, aid):
        # Only unpublished temporary controls can be reset after a crash during finalization.
        for table, key in [('query_snapshots', 'query_id'), ('previews', 'preview_id')]:
            while True:
                self.control.check()
                with self.db.transaction() as conn:
                    ids = list(conn.scalars(text(f'SELECT {key} FROM announcement_archive.{table} '
                        'WHERE archive_id=:a AND expires_at IS NOT NULL LIMIT 500'), {'a': aid}))
                    if not ids:
                        break
                    conn.execute(text(f'UPDATE announcement_archive.{table} SET expires_at=NULL '
                        f'WHERE archive_id=:a AND {key}=ANY(:ids)'), dict(a=aid, ids=ids))
