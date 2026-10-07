"""Q4 cleanup tests use disposable PG and five owned temporary SQLite fixtures."""
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import text

from test_announcement_pg_migration import pg, pg_cluster, fixture_inventory, migrate
from src.foundation.clients.announcement_archive.core import Blocked, Cancelled
from src.foundation.dao.announcement_archive.pg_schema import schema_exists
from src.ops.runtime.announcement_archive.cleanup import ArchiveCleanup, require_closed_files
from src.scripts import migrate_announcement_archive as cli


def ready(pg, tmp_path):
    inventory = fixture_inventory(tmp_path)
    migration = migrate(pg, inventory)
    migration.run(apply=True)
    return inventory, migration


def test_cleanup_plan_is_read_only_and_names_only_five_sources(pg, tmp_path):
    inventory, migration = ready(pg, tmp_path)
    before = {p: p.read_bytes() for p in (*inventory.ledgers, inventory.catalog)}
    guards = []
    original = migration.guard
    def guard(*args, **kwargs):
        guards.append(kwargs['apply'])
        return original(*args, **kwargs)
    migration.guard = guard
    result = ArchiveCleanup(migration).run()
    assert result['phase'] == 'cleanupPlanned' and len(result['files']) == 5
    assert {f['path'] for f in result['files']} == set(map(str, before))
    assert guards == [False]*4 and result['source_http_requests'] == 0
    assert all(p.read_bytes() == value for p, value in before.items())
    with pg.transaction(read_only=True) as conn:
        assert conn.scalar(text('SELECT count(*) FROM announcement_archive.archives WHERE import_state=\'ready\'')) == 4


def test_cleanup_removes_only_whitelist_and_preserves_pg_locks_binding_shared_and_pdf(pg, tmp_path):
    inventory, migration = ready(pg, tmp_path)
    preserved = [tmp_path/'shared.sqlite', tmp_path/'file.pdf', inventory.catalog.parent/'binding.json',
                 inventory.ledgers[0].parent/'execution.lock', inventory.ledgers[0].parent/'other.sqlite']
    for path in preserved: path.write_bytes(b'preserved')
    # A cold, empty journal is removable; an active/hot journal is covered below.
    companion = Path(str(inventory.catalog)+'-journal'); companion.write_bytes(b'')
    result = ArchiveCleanup(migration).run(cleanup=True)
    assert result['phase'] == 'cleaned' and len(result['removed']) == 6
    assert not any(p.exists() for p in (*inventory.ledgers, inventory.catalog, companion))
    assert all(p.read_bytes() == b'preserved' for p in preserved)
    assert (inventory.catalog.parent/'catalog-writer.lock').is_file()
    with pg.transaction(read_only=True) as conn:
        assert conn.scalar(text('SELECT count(*) FROM announcement_archive.archives')) == 4
        assert conn.scalar(text('SELECT count(*) FROM announcement_archive.source_records')) == 24


def test_missing_migration_blocks_cleanup_without_ddl_or_deletion(pg, tmp_path):
    inventory = fixture_inventory(tmp_path)
    with pytest.raises(Blocked): ArchiveCleanup(migrate(pg, inventory)).run(cleanup=True)
    assert all(p.is_file() for p in (*inventory.ledgers, inventory.catalog))
    with pg.transaction(read_only=True) as conn: assert not schema_exists(conn)


@pytest.mark.parametrize('change',[
    "UPDATE announcement_archive.archives SET import_state='importing'",
    "UPDATE announcement_archive.migration_checkpoints SET state='copying'",
    "UPDATE announcement_archive.migration_checkpoints SET rows_digest='changed'",
    "DELETE FROM announcement_archive.migration_checkpoints WHERE source_table='runs'",
])
def test_incomplete_or_changed_import_blocks_all_unlinks(pg, tmp_path, change):
    inventory, migration = ready(pg, tmp_path)
    # Only disposable q1_* tables are mutated; no formal dataset is cleared.
    assert pg.policy.database.startswith('q1_') and pg.policy.port != 5432
    with pg.transaction() as conn: conn.execute(text(change))
    with pytest.raises(Blocked): ArchiveCleanup(migration).run(cleanup=True)
    assert all(p.is_file() for p in (*inventory.ledgers, inventory.catalog))


def test_source_change_after_migration_blocks_cleanup(pg, tmp_path):
    inventory, migration = ready(pg, tmp_path)
    with sqlite3.connect(inventory.ledgers[0]) as conn:
        conn.execute("UPDATE artifacts SET title='changed after import'")
    with pytest.raises(Blocked, match='migration_checkpoint_source_changed'):
        ArchiveCleanup(migration).run(cleanup=True)
    assert all(p.is_file() for p in (*inventory.ledgers, inventory.catalog))


def test_open_external_reader_blocks_cleanup(pg, tmp_path):
    inventory, migration = ready(pg, tmp_path)
    script = 'import sqlite3,time,sys;c=sqlite3.connect(sys.argv[1]);c.execute("SELECT count(*) FROM artifacts").fetchone();print("ready",flush=True);time.sleep(30)'
    child = subprocess.Popen([sys.executable, '-c', script, str(inventory.ledgers[0])], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        with pytest.raises(Blocked, match='migration_sources_still_open'):
            ArchiveCleanup(migration).run(cleanup=True)
        assert all(p.is_file() for p in (*inventory.ledgers, inventory.catalog))
    finally:
        child.terminate(); child.wait(timeout=3); child.stdout.close()


@pytest.mark.parametrize('unsafe', ['symlink', 'hardlink', 'hotJournal'])
def test_unsafe_file_or_hot_journal_never_deletes_other_sources(pg, tmp_path, unsafe):
    inventory, migration = ready(pg, tmp_path)
    if unsafe == 'hotJournal': Path(str(inventory.ledgers[0])+'-journal').write_bytes(b'hot')
    elif unsafe == 'hardlink': (tmp_path/'linked.sqlite').hardlink_to(inventory.ledgers[0])
    else:
        original = inventory.ledgers[0].with_name('original.sqlite'); inventory.ledgers[0].rename(original)
        inventory.ledgers[0].symlink_to(original)
    with pytest.raises(Blocked): ArchiveCleanup(migration).run(cleanup=True)
    assert all(p.exists() for p in (*inventory.ledgers, inventory.catalog))


def test_native_updates_and_expired_control_gc_do_not_invalidate_import_receipt(pg, tmp_path):
    inventory, migration = ready(pg, tmp_path)
    assert pg.policy.database.startswith('q1_') and pg.policy.port != 5432
    with pg.transaction() as conn:
        conn.execute(text("UPDATE announcement_archive.archive_execution SET revision=revision+1,heartbeat='native heartbeat'"))
        conn.execute(text('DELETE FROM announcement_archive.query_snapshots'))
        conn.execute(text('DELETE FROM announcement_archive.previews'))
    assert ArchiveCleanup(migration).run()['phase'] == 'cleanupPlanned'


def test_cancel_before_first_unlink_preserves_all_sources(pg, tmp_path):
    inventory, migration = ready(pg, tmp_path)
    def stop(_paths): migration.control.stop.set()
    with pytest.raises(Cancelled): ArchiveCleanup(migration, closed_files=stop).run(cleanup=True)
    assert all(p.exists() for p in (*inventory.ledgers, inventory.catalog))


def test_unlink_failure_keeps_pg_ready_and_remaining_sources(pg, tmp_path, monkeypatch):
    inventory, migration = ready(pg, tmp_path)
    import os
    original = os.unlink; removed = []
    def fail(name, **kwargs):
        if removed: raise PermissionError('injected unlink failure')
        original(name, **kwargs); removed.append(name)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'unlink', fail)
        with pytest.raises(PermissionError): ArchiveCleanup(migration).run(cleanup=True)
    assert len(removed) == 1 and sum(p.exists() for p in (*inventory.ledgers, inventory.catalog)) == 4
    with pg.transaction(read_only=True) as conn:
        assert conn.scalar(text("SELECT count(*) FROM announcement_archive.archives WHERE import_state='ready'")) == 4


def test_file_replaced_during_closed_check_blocks_every_unlink(pg, tmp_path):
    inventory, migration = ready(pg, tmp_path)
    def replace_file(_paths):
        inventory.ledgers[0].write_bytes(b'changed')
    with pytest.raises(Blocked, match='migration_source_changed'):
        ArchiveCleanup(migration, closed_files=replace_file).run(cleanup=True)
    assert all(p.exists() for p in (*inventory.ledgers, inventory.catalog))


def test_cleanup_cli_has_explicit_mutually_exclusive_actions_and_local_switch_gate(monkeypatch, capsys):
    with pytest.raises(SystemExit) as error: cli.main(['--apply','--cleanup'])
    assert error.value.code == 2
    for environment, enabled in [('prod', True), ('local', False)]:
        monkeypatch.setattr(cli, 'get_settings', lambda: SimpleNamespace(app_env=environment, wealth_local_announcements_enabled=enabled))
        monkeypatch.setattr(cli, 'ArchiveDatabase', lambda *_: pytest.fail('must block before opening PG'))
        assert cli.main(['--cleanup-plan']) == 3
        assert 'migration_consumer_switch_required' in capsys.readouterr().out


def test_open_file_check_errors_never_silently_allow_deletion(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_k: SimpleNamespace(returncode=1, stdout='', stderr='permission denied'))
    with pytest.raises(Blocked, match='migration_open_files_check_failed'): require_closed_files([Path('/fixture')])
