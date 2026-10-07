"""Q1 isolated acceptance. A disposable PG cluster; never the local formal metadata DB."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import signal
import sys
import time
import tempfile
from types import SimpleNamespace
import uuid

import psycopg
import pytest
from sqlalchemy import text

from src.foundation.clients.announcement_archive.core import Blocked, Cancelled, Control, DownloadPolicy, identity
from src.foundation.clients.announcement_archive.migration_source import LegacyLedger, fingerprint, opened
from src.foundation.config.announcement_archive import ArchiveDatabasePolicy
from src.foundation.config.settings import Settings, get_settings
from src.foundation.dao.announcement_archive.ledger import SCHEMA
from src.foundation.dao.announcement_archive.schema import ADDITIONS, extend_schema
from src.foundation.dao.announcement_archive.pg_archive import ArchiveDAO, register_archive
from src.foundation.dao.announcement_archive.pg_database import ArchiveDatabase, guarded_url, configured_archive_database
from src.foundation.dao.announcement_archive.pg_schema import TABLES, LEDGER_TABLES, install_schema, schema_exists, validate_schema
from src.foundation.dao.announcement_archive.catalog import SCHEMA as CATALOG_SCHEMA
from src.ops.runtime.announcement_archive.migration import ArchiveMigration, MigrationInventory, archive_guard
from src.scripts import migrate_announcement_archive as cli


@pytest.fixture(scope='module')
def pg_cluster():
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary/'initdb').is_file():
        pytest.skip('existing PostgreSQL 18 binaries required; tests never install them')
    directory = Path(tempfile.mkdtemp(prefix='announcement-q1-pg-', dir='/private/tmp'))
    data = directory/'data'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    started = False
    try:
        subprocess.run([str(binary/'initdb'), '-D', str(data), '-A', 'trust', '-U', 'q1_fixture',
                        '--no-locale', '--encoding=UTF8'], check=True, capture_output=True)
        subprocess.run([str(binary/'pg_ctl'), '-D', str(data), '-l', str(directory/'pg.log'),
            '-o', f'-h 127.0.0.1 -p {port} -k {directory}', '-w', '-t', '10', 'start'], check=True, capture_output=True)
        started = True
        yield port
    finally:
        if started:
            subprocess.run([str(binary/'pg_ctl'), '-D', str(data), '-m', 'immediate', '-w', 'stop'],
                           check=True, capture_output=True)
        shutil.rmtree(directory)


@pytest.fixture
def pg(pg_cluster):
    name = 'q1_' + uuid.uuid4().hex
    with psycopg.connect(host='127.0.0.1', port=pg_cluster, user='q1_fixture', dbname='postgres', autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(name)))
    policy = replace(ArchiveDatabasePolicy(), database=name, port=pg_cluster)
    database = ArchiveDatabase(f'postgresql+psycopg://q1_fixture@localhost:{pg_cluster}/{name}', policy)
    try:
        yield database
    finally:
        database.close()


def quiet():
    return Control(DownloadPolicy(), emit=lambda _: None)


@contextmanager
def fixture_guard(*_args, **_kwargs):
    yield SimpleNamespace(assert_valid=lambda **_: None)


def fixture_inventory(tmp_path, *, records=6):
    paths, ids = [], []
    for i in range(4):
        root = 'announcements' + (f'/fixture-{i}' if i else '')
        aid = identity(['fixture-volume', root]); ids.append(aid)
        path = tmp_path/aid/'downloads.sqlite'; path.parent.mkdir()
        paths.append(path)
        with sqlite3.connect(path) as conn:
            for sql in SCHEMA: conn.execute(sql)
            conn.execute('INSERT INTO archive VALUES(1,2,?,?,?)', ('fixture-volume',root,'2026-10-01T00:00:00+00:00'))
            conn.execute('INSERT INTO cooldown VALUES(1,100.25,120.5,0,?)', ('preserved-cooldown',))
            if i in (0,3):
                extend_schema(conn)
                conn.execute("UPDATE archive_execution SET owner_token='terminal-owner',revision=7")
            for rowid, run_id, phase in [(7,'run-shared','completed'),(20,'run-second','blocked')]:
                conn.execute('INSERT INTO runs(rowid,run_id,start_date,end_date,interval_seconds,source_scope,phase,'
                    'source_policy,legacy_upper_id,legacy_after_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (rowid,run_id,'2026-09-30','2026-09-30',5.25,'dg/fixture',phase,'{ "batch_size": 500 }',
                     101,99,'2026-10-01T00:00:00+00:00'))
            if i in (0,3):
                conn.execute("UPDATE runs SET preview_id='old-preview',owner_token='historical-owner' WHERE run_id='run-shared'")
                conn.execute("INSERT INTO attempt_log VALUES('run-shared','shared-0',1,1,'start','end','failed','http_500',500,99)")
                conn.execute("INSERT INTO run_sessions VALUES('run-shared',1,'start','end','owner','done')")
                conn.execute("INSERT INTO command_receipts VALUES('command-shared','start','payload','run-shared','accepted','created')")
            states = ['succeeded','failed','pending','blocked','prepared']
            for j in range(5):
                state = states[(j+i)%5]
                conn.execute('INSERT INTO artifacts(artifact_key,ann_date,ts_code,title,url,relative_path,path_fold,'
                    'state,error,attempts,size,sha256,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (f'shared-{j}','2026-09-30','002245.SZ','原始标题','https://example.invalid/file.pdf',
                     f'2026-09-30/002245.SZ/{j}.pdf',f'2026-09-30/002245.sz/{j}.pdf',state,
                     '' if j==0 else None,j,111,'a'*64,'old-time'))
                conn.execute('INSERT INTO run_artifacts(run_id,artifact_key,outcome,attempts) VALUES(?,?,?,?)',
                             ('run-shared',f'shared-{j}',None if j==0 else state,j))
            for j in range(records):
                conn.execute('INSERT INTO source_records(rowid,source_scope,record_key,legacy_raw_id,metadata,'
                    'artifact_key,first_seen_run,last_seen_run) VALUES(?,?,?,?,?,?,?,?)',
                    (3+j*3,'dg/fixture',f'record-{j}',j+10,'{ "name": "中文", "rec_time": null, "url": "" }',
                     f'shared-{j}' if j<5 else None,'run-shared','run-second'))
            conn.execute("INSERT INTO run_source_days(run_id,ann_date,state,records_committed) VALUES('run-shared','2026-09-30','completed',6)")
    catalog = tmp_path/'catalog'/'catalog.sqlite'; catalog.parent.mkdir()
    with sqlite3.connect(catalog) as conn:
        for sql in CATALOG_SCHEMA: conn.execute(sql)
        conn.execute("INSERT INTO catalog_meta(singleton,schema_version,source_scope) VALUES(1,2,'dg/fixture')")
        for i, aid in enumerate(ids):
            conn.execute('INSERT INTO query_snapshots(query_id,conditions,state,archive_identity,dates_total,status_available,created_at,updated_at) '
                'VALUES(?,?,?,?,1,1,?,?)',(f'old-query-{i}','{ "startDate":"2026-09-30" }','ready',aid,'old-created','old-updated'))
            conn.execute('INSERT INTO previews VALUES(?,?,?,?,?,?,?,?,?)',
                ('old-preview','2026-09-30','2026-09-30',5.25,'dg/fixture',aid,'ready','{ "artifactCount": 5 }',999)) if i==0 else None
        # A large catalog copy must not be imported into PG.
        conn.execute("INSERT INTO catalog_records VALUES('2026-09-30','g','r','20260930','002245.SZ','中文','标题','u',NULL,'a','u')")
    return MigrationInventory(tuple(paths), catalog, tmp_path/'external')


def migrate(pg, inventory, control=None):
    return ArchiveMigration(pg, control or quiet(), inventory, guard=fixture_guard)


@pytest.mark.parametrize('dsn', ['', 'sqlite:///x', 'postgresql://x@127.0.0.1:5432/goldenshare_lake_meta',
    'postgresql+psycopg://x@remote.invalid:5432/goldenshare_lake_meta',
    'postgresql+psycopg://x@127.0.0.1:5432/goldenshare_dagster',
    'postgresql+psycopg://x@127.0.0.1:5433/goldenshare_lake_meta',
    'postgresql+psycopg://x@localhost:5432/goldenshare_lake_meta?host=remote.invalid',
    'postgresql+psycopg://x@localhost:5432/goldenshare_lake_meta?service=prod',
    'postgresql+psycopg://x@localhost:5432/goldenshare_lake_meta?options=-csearch_path%3Dpublic'])
def test_invalid_dsn_precedes_engine_creation(dsn,monkeypatch):
    from src.foundation.dao.announcement_archive import pg_database
    monkeypatch.setattr(pg_database,'create_engine',lambda *_a,**_k:pytest.fail('invalid config must not create pool'))
    with pytest.raises(Blocked):ArchiveDatabase(dsn)


def test_settings_default_priority_and_no_main_fallback(tmp_path,monkeypatch):
    assert Settings(_env_file=None).announcement_archive_database_url==''
    env=tmp_path/'local.env';env.write_text('ANNOUNCEMENT_ARCHIVE_DATABASE_URL=from-file\nDATABASE_URL=unrelated\n')
    monkeypatch.setenv('GOLDENSHARE_ENV_FILE',str(env));monkeypatch.setenv('ANNOUNCEMENT_ARCHIVE_DATABASE_URL','from-process')
    get_settings.cache_clear()
    try:
        settings=get_settings()
        assert settings.announcement_archive_database_url=='from-file' and settings.database_url=='unrelated'
        assert 'from-file' not in repr(settings)
    finally:get_settings.cache_clear()
    assert guarded_url('postgresql+psycopg://x@localhost:5432/goldenshare_lake_meta').host=='127.0.0.1'


def test_static_ddl_preserves_all_legacy_columns_defaults(pg):
    reference=sqlite3.connect(':memory:')
    for sql in SCHEMA:reference.execute(sql)
    reference.execute("INSERT INTO archive VALUES(1,2,'v','announcements','time')");extend_schema(reference)
    for table in LEDGER_TABLES:
        old={r[1]:r for r in reference.execute(f'PRAGMA table_info({table})') if r[1]!='singleton'}
        assert set(TABLES[table]['columns'])==set(old)|{'archive_id'}|({'row_seq'} if table in ('runs','source_records') else set())
        for name,column in old.items():
            actual=TABLES[table]['columns'][name]
            assert actual['type']=={'TEXT':'TEXT','INTEGER':'BIGINT','REAL':'DOUBLE PRECISION'}[column[2]]
            assert actual['nullable']==(not(column[3] or column[5]))
            assert actual['default']==column[4]
    with pg.transaction(read_only=True) as conn:assert not schema_exists(conn)
    with pg.transaction() as conn:assert install_schema(conn)
    with pg.transaction() as conn:assert not install_schema(conn)
    with pg.transaction() as conn:
        conn.execute(text('ALTER TABLE announcement_archive.artifacts DROP COLUMN title'))
    with pg.transaction(read_only=True) as conn:
        with pytest.raises(Blocked,match='schema_invalid'):validate_schema(conn)


def test_plan_is_read_only_and_apply_preserves_four_archives(pg,tmp_path,monkeypatch):
    inventory=fixture_inventory(tmp_path)
    before={p:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in (*inventory.ledgers,inventory.catalog)}
    m=migrate(pg,inventory)
    plan=m.run()
    assert len(plan['archives'])==4 and plan['catalog']['copied_metadata_rows']==0
    import math
    assert plan['expected_batches']==sum(math.ceil(f['rows_total']/500) for a in plan['archives']
        for f in (*a['tables'].values(),*a['expired_controls'].values()))
    assert not plan['schema_exists']
    with pg.transaction(read_only=True) as conn:assert not schema_exists(conn)
    result=m.run(apply=True);assert result['phase']=='completed'
    with pg.transaction(read_only=True) as conn:
        validate_schema(conn)
        assert conn.scalar(text('SELECT count(*) FROM announcement_archive.archives'))==4
        states=[]
        for aid in [p.parent.name for p in inventory.ledgers]:
            dao=ArchiveDAO(conn,aid)
            states.append(dao.get('artifacts',{'artifact_key':'shared-0'})['state'])
            assert dao.count('artifacts')==5 and dao.count('source_records')==6
            assert dao.get('cooldown',{})['next_request_not_before']==120.5
            assert [r['row_seq'] for r in dao.row_page('runs',descending=True)]==[20,7]
            assert [r['row_seq'] for r in dao.row_page('runs',cursor=20,descending=True)]==[7]
            assert [r['row_seq'] for r in dao.row_page('source_records',cursor=9,limit=2)]==[12,15]
        assert len(set(states))==4
        preview=ArchiveDAO(conn,inventory.ledgers[0].parent.name).get('previews',{'preview_id':'old-preview'})
        assert preview['reason']=='DC_PREVIEW_STALE' and preview['statistics']=='{ "artifactCount": 5 }'
        assert preview['expires_at'] is not None
        assert conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"))==0
    assert m.run(apply=True)['phase']=='completed'
    for path,facts in before.items():assert (hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns)==facts
    # Both identity sequences advance beyond every imported old rowid, without changing integer cursors.
    with pg.transaction() as conn:
        aid=inventory.ledgers[0].parent.name
        row=conn.execute(text("INSERT INTO announcement_archive.runs(archive_id,run_id,phase) VALUES(:a,'new','completed') RETURNING row_seq"),{'a':aid}).scalar()
        assert row>20


def test_cancel_resume_and_atomic_checkpoint(pg,tmp_path):
    inventory=fixture_inventory(tmp_path,records=1001);control=quiet()
    events=[]
    def emit(value):
        event=json.loads(value);events.append(event)
        if event.get('table')=='source_records' and event.get('rowsCommitted')==500:control.stop.set()
    control.emit=emit
    with pytest.raises(Cancelled):migrate(pg,inventory,control).run(apply=True)
    aid=inventory.ledgers[0].parent.name
    with pg.transaction(read_only=True) as conn:
        dao=ArchiveDAO(conn,aid,require_ready=False)
        assert dao.count('source_records')==500
        cp=dao.get('migration_checkpoints',{'source_table':'source_records'})
        assert cp['rows_committed']==500 and cp['state']=='cancelled'
        with pytest.raises(Blocked,match='import_incomplete'):ArchiveDAO(conn,aid)
    assert migrate(pg,inventory).run(apply=True)['phase']=='completed'
    with pg.transaction(read_only=True) as conn:assert ArchiveDAO(conn,aid).count('source_records')==1001


def test_target_conflict_never_overwrites_business_rows(pg,tmp_path):
    inventory=fixture_inventory(tmp_path);m=migrate(pg,inventory);m.run(apply=True)
    aid=inventory.ledgers[0].parent.name
    with pg.transaction() as conn:
        ArchiveDAO(conn,aid).update('artifacts',{'artifact_key':'shared-0'},{'title':'changed-target'})
    with pytest.raises(Blocked,match='conflict'):m.run()
    with pg.transaction(read_only=True) as conn:
        assert ArchiveDAO(conn,aid).get('artifacts',{'artifact_key':'shared-0'})['title']=='changed-target'


@pytest.mark.parametrize('change,reason',[
    ("UPDATE archive SET schema_version=1",'version_unsupported'),
    ("UPDATE runs SET phase='downloading' WHERE run_id='run-shared'",'active_run'),
    ("UPDATE archive_execution SET active_run_id='run-shared'",'active_run'),
    ("UPDATE runs SET check_state='checking'",'active_check'),
    ("UPDATE cooldown SET request_in_flight=1",'request_in_flight'),
])
def test_source_blocked_before_any_ddl(pg,tmp_path,change,reason):
    inventory=fixture_inventory(tmp_path)
    with sqlite3.connect(inventory.ledgers[0]) as conn:conn.execute(change)
    with pytest.raises(Blocked,match=reason):migrate(pg,inventory).run(apply=True)
    with pg.transaction(read_only=True) as conn:assert not schema_exists(conn)


def test_source_changed_after_committed_batch_blocks_resume(pg,tmp_path):
    inventory=fixture_inventory(tmp_path,records=501);control=quiet()
    control.emit=lambda s:control.stop.set() if json.loads(s).get('rowsCommitted')==500 else None
    with pytest.raises(Cancelled):migrate(pg,inventory,control).run(apply=True)
    with sqlite3.connect(inventory.ledgers[0]) as conn:conn.execute("UPDATE artifacts SET title='changed-source'")
    with pytest.raises(Blocked,match='source_changed'):migrate(pg,inventory).run(apply=True)


def test_short_transaction_rollback_and_archive_claim_lock(pg,tmp_path):
    inventory=fixture_inventory(tmp_path);migrate(pg,inventory).run(apply=True)
    aid=inventory.ledgers[0].parent.name
    with pytest.raises(RuntimeError):
        with pg.transaction() as conn:
            ArchiveDAO(conn,aid).update('artifacts',{'artifact_key':'shared-0'},{'title':'rollback'})
            raise RuntimeError('simulated process failure before commit')
    with pg.transaction(read_only=True) as conn:assert ArchiveDAO(conn,aid).get('artifacts',{'artifact_key':'shared-0'})['title']=='原始标题'
    with pg.transaction() as first:
        ArchiveDAO(first,aid).claim_run('run-shared','new-owner')
        with pytest.raises(Blocked,match='database_unavailable'):
            with pg.transaction() as second:ArchiveDAO(second,aid).claim_run('run-second','another-owner')
    with pg.transaction() as conn:
        with pytest.raises(Blocked,match='already_running'):ArchiveDAO(conn,aid).claim_run('run-second','another-owner')


def test_cli_plan_default_config_failure_and_no_dsn_flag(monkeypatch,capsys):
    monkeypatch.setattr(cli,'get_settings',lambda:SimpleNamespace(announcement_archive_database_url=''))
    assert cli.main([])==3
    assert json.loads(capsys.readouterr().out)['code']=='archive_database_config_missing'
    with pytest.raises(SystemExit) as error:cli.main(['--database-url','remote'])
    assert error.value.code==2


def test_wal_hash_and_hot_journal_are_not_ignored(tmp_path):
    path=tmp_path/'downloads.sqlite';path.write_bytes(b'source');control=quiet()
    first=fingerprint(path,control)
    Path(str(path)+'-wal').write_bytes(b'wal-v1')
    second=fingerprint(path,control)
    assert second!=first
    Path(str(path)+'-wal').write_bytes(b'wal-v2')
    assert fingerprint(path,control)!=second


@pytest.mark.parametrize('kind,reason',[('journal','hot_journal'),('wal','shared_memory_missing'),('symlink','symlink_path_forbidden')])
def test_unsafe_or_unsettled_source_blocks_before_ddl(pg,tmp_path,kind,reason):
    inventory=fixture_inventory(tmp_path);path=inventory.ledgers[0]
    if kind=='symlink':
        original=path.with_name('fixture-original.sqlite');path.rename(original);path.symlink_to(original)
    else:Path(str(path)+('-journal' if kind=='journal' else '-wal')).write_bytes(b'fixture-active-source')
    with pytest.raises(Blocked,match=reason):migrate(pg,inventory).run(apply=True)
    with pg.transaction(read_only=True) as conn:assert not schema_exists(conn)


@pytest.mark.parametrize('mode,exit_code',[('exit',77),('signal',130)])
def test_real_process_exit_sigint_resume_and_file_locks(pg,tmp_path,mode,exit_code):
    inventory=fixture_inventory(tmp_path,records=1001)
    spec=tmp_path/'runner.json'
    spec.write_text(json.dumps(dict(port=pg.policy.port,database=pg.policy.database,
        ledgers=[str(p) for p in inventory.ledgers],catalog=str(inventory.catalog),mount=str(inventory.mount))))
    # tests is not installed as a product package; run the existing fixture as a file.
    command=[sys.executable,'tests/fixtures/announcement_pg_migration_runner.py',str(spec)]
    import os
    process=subprocess.Popen(command+[mode],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                             env=dict(os.environ,PYTHONPATH=str(Path.cwd())))
    try:
        for line in process.stdout:
            event=json.loads(line)
            if event.get('table')=='source_records' and event.get('rowsCommitted')==500:
                if mode=='signal':
                    from src.foundation.clients.announcement_archive.locking import ExecutionLock
                    with pytest.raises(Blocked,match='already_running'):ExecutionLock(inventory.ledgers[0].parent/'execution.lock').open()
                    process.send_signal(signal.SIGINT)
                break
        assert process.wait(timeout=15)==exit_code,process.stderr.read()
    finally:
        if process.poll() is None:process.kill();process.wait()
        process.stdout.close();process.stderr.close()
    aid=inventory.ledgers[0].parent.name
    with pg.transaction(read_only=True) as conn:
        assert ArchiveDAO(conn,aid,require_ready=False).count('source_records')==500
    resumed=subprocess.run(command+['resume'],capture_output=True,text=True,
                           env=dict(os.environ,PYTHONPATH=str(Path.cwd())),timeout=30)
    assert resumed.returncode==0,resumed.stderr
    events=[json.loads(line) for line in resumed.stdout.splitlines()]
    committed=[e['rowsCommitted'] for e in events if e.get('phase')=='migrating' and e.get('archive')==aid and e.get('table')=='source_records']
    assert committed==sorted(committed) and min(committed)>=500
    with pg.transaction(read_only=True) as conn:assert ArchiveDAO(conn,aid).count('source_records')==1001


def test_crash_during_final_expiry_can_resume(pg,tmp_path,monkeypatch):
    inventory=fixture_inventory(tmp_path);m=migrate(pg,inventory)
    def crash(aid,catalog,anchor):
        with pg.transaction() as conn:
            ArchiveDAO(conn,aid,require_ready=False).update('query_snapshots',{'query_id':'old-query-0'},{'expires_at':999.})
        raise RuntimeError('simulated crash after temporary expiry update')
    monkeypatch.setattr(m,'finish_archive',crash)
    with pytest.raises(RuntimeError):m.run(apply=True)
    assert migrate(pg,inventory).run(apply=True)['phase']=='completed'


def test_batch_and_checkpoint_rollback_together(pg,tmp_path,monkeypatch):
    inventory=fixture_inventory(tmp_path,records=501)
    original=ArchiveDAO.update
    def failed_checkpoint(self,table,key,values,**kwargs):
        if table=='migration_checkpoints' and key['source_table']=='source_records' and values.get('rows_committed')==500:
            raise RuntimeError('simulated failure after business insert before checkpoint')
        return original(self,table,key,values,**kwargs)
    monkeypatch.setattr(ArchiveDAO,'update',failed_checkpoint)
    with pytest.raises(RuntimeError):migrate(pg,inventory).run(apply=True)
    aid=inventory.ledgers[0].parent.name
    with pg.transaction(read_only=True) as conn:
        dao=ArchiveDAO(conn,aid,require_ready=False)
        assert dao.count('artifacts')==5 and dao.count('source_records')==0
        assert dao.get('migration_checkpoints',{'source_table':'source_records'})['rows_committed']==0
    monkeypatch.setattr(ArchiveDAO,'update',original)
    assert migrate(pg,inventory).run(apply=True)['phase']=='completed'


def test_catalog_conflict_is_detected_by_readonly_plan(pg,tmp_path):
    inventory=fixture_inventory(tmp_path);m=migrate(pg,inventory);m.run(apply=True)
    with pg.transaction() as conn:
        ArchiveDAO(conn,inventory.ledgers[0].parent.name).update('query_snapshots',{'query_id':'old-query-0'},
                                                              {'conditions':'changed'})
    with pytest.raises(Blocked,match='conflict'):m.run()


@pytest.mark.parametrize('sql',[
    'DROP INDEX announcement_archive.artifact_success',
    'ALTER TABLE announcement_archive.artifacts DROP CONSTRAINT artifacts_pkey',
    'ALTER TABLE announcement_archive.runs ALTER COLUMN records_read SET DEFAULT 99',
    'UPDATE announcement_archive.schema_info SET version=999',
])
def test_runtime_rejects_incomplete_unknown_schema_without_repair(pg,sql):
    with pg.transaction() as conn:install_schema(conn)
    with pg.transaction() as conn:conn.execute(text(sql))
    with pg.transaction(read_only=True) as conn:
        with pytest.raises(Blocked):validate_schema(conn)


def test_prod_disabled_factory_creates_no_pool(monkeypatch):
    from src.foundation.dao.announcement_archive import pg_database
    monkeypatch.setattr(pg_database,'ArchiveDatabase',lambda *_:pytest.fail('disabled must not create pool'))
    assert configured_archive_database(SimpleNamespace(app_env='prod',wealth_local_announcements_enabled=True)) is None
    assert configured_archive_database(SimpleNamespace(app_env='local',wealth_local_announcements_enabled=False)) is None


def test_volume_identity_and_existing_double_locks(tmp_path,monkeypatch):
    import os
    from src.ops.runtime.announcement_archive import migration
    from src.foundation.clients.announcement_archive.locking import ExecutionLock
    inventory=fixture_inventory(tmp_path)
    class TestVolume:
        volume_uuid='fixture-volume'
        def __init__(self,output,_policy):self.output=output
        def open(self):return self
        def assert_valid(self,**_):pass
        def close(self):pass
        @contextmanager
        def directory(self,relative):
            fd=os.open(self.output/relative,os.O_RDONLY|os.O_DIRECTORY)
            try:yield fd
            finally:os.close(fd)
    monkeypatch.setattr(migration,'SourceVolume',TestVolume)
    with opened(LegacyLedger(inventory.ledgers[0],quiet())) as source:
        root=inventory.mount/source.archive['root_relative_path'];(root/'.state').mkdir(parents=True)
        before=list(tmp_path.rglob('*'))
        with archive_guard(source,inventory.mount,apply=False,policy=ArchiveDatabasePolicy()):pass
        assert list(tmp_path.rglob('*'))==before
        with archive_guard(source,inventory.mount,apply=True,policy=ArchiveDatabasePolicy()):
            for lock_path in (source.path.parent/'execution.lock',root/'.state/archive.lock'):
                with pytest.raises(Blocked,match='already_running'):ExecutionLock(lock_path).open()
        monkeypatch.setattr(TestVolume,'volume_uuid','another-volume')
        with pytest.raises(Blocked,match='identity_mismatch'):
            with archive_guard(source,inventory.mount,apply=False,policy=ArchiveDatabasePolicy()):pass


def test_pool_statement_lock_budgets(pg):
    budget=ArchiveDatabase(str(pg.engine.url),replace(pg.policy,pool_size=1,pool_seconds=.02,statement_milliseconds=50))
    try:
        with budget.transaction() as first:
            assert first.scalar(text("SELECT current_setting('lock_timeout')"))=='500ms'
            with pytest.raises(Blocked,match='database_unavailable'):
                with budget.transaction():pytest.fail('pool must be exhausted')
        with pytest.raises(Blocked,match='database_unavailable'):
            with budget.transaction() as conn:conn.execute(text('SELECT pg_sleep(.2)'))
    finally:budget.close()


def test_readonly_wal_rows_preserved_and_source_never_upgraded(pg,tmp_path):
    inventory=fixture_inventory(tmp_path)
    writer=sqlite3.connect(inventory.ledgers[1])
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("UPDATE artifacts SET title='in-wal' WHERE artifact_key='shared-0'");writer.commit()
        before=fingerprint(inventory.ledgers[1],quiet())
        assert migrate(pg,inventory).run(apply=True)['phase']=='completed'
        assert fingerprint(inventory.ledgers[1],quiet())==before
        with pg.transaction(read_only=True) as conn:
            assert ArchiveDAO(conn,inventory.ledgers[1].parent.name).get('artifacts',{'artifact_key':'shared-0'})['title']=='in-wal'
        assert writer.execute('SELECT schema_version FROM archive').fetchone()[0]==2
    finally:writer.close()


def test_legacy_public_tables_and_alembic_are_not_used(pg,tmp_path,monkeypatch):
    names=('index_daily_active_pool','index_daily_active_pool_history','market_major_indices','market_major_indices_change_history')
    with pg.transaction() as conn:
        for name in names:
            conn.execute(text(f'CREATE TABLE public.{name}(marker TEXT)'))
            conn.execute(text(f"INSERT INTO public.{name} VALUES('unchanged')"))
    inventory=fixture_inventory(tmp_path)
    statements=[]
    from sqlalchemy import event
    event.listen(pg.engine,'before_cursor_execute',lambda _c,_cu,s,_p,_co,_e:statements.append(s))
    assert migrate(pg,inventory).run(apply=True)['phase']=='completed'
    assert not any('alembic' in s.lower() or any('public.'+n in s for n in names) for s in statements)
    with pg.transaction(read_only=True) as conn:
        for name in names:assert conn.scalar(text(f'SELECT marker FROM public.{name}'))=='unchanged'


def test_permission_failure_does_not_create_schema(pg):
    with pytest.raises(Blocked,match='database_unavailable'):
        with pg.transaction() as conn:
            conn.execute(text('SET LOCAL ROLE pg_read_all_data'))
            install_schema(conn)
    with pg.transaction(read_only=True) as conn:assert not schema_exists(conn)


def test_complete_schema3_values_and_nullable_relations(pg,tmp_path):
    inventory=fixture_inventory(tmp_path)
    path=inventory.ledgers[0]
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE runs SET batch_kind='retry',parent_run_id='run-second',retry_of_run_id='run-second',"
            "actor_id='actor',started_at='start',finished_at='finish',heartbeat_at='heartbeat',"
            "business_updated_at='business',stop_requested_at='stop',resume_count=2,current_artifact_key='shared-0',"
            "attempt_number=3,bytes_received=4294967296,bytes_total=4294967297,wait_kind='cooldown',next_request_at=999.25,"
            "revision=31,check_state='unknown',check_kind='presence',check_code='missing',check_updated_at='checked',"
            "source_contract_version=1,days_total=3,days_completed=2,current_day='2026-09-30',enumeration_sealed=1")
        conn.execute("UPDATE artifacts SET created_run_id='run-shared',representative_record_key='record-0'")
        conn.execute("UPDATE run_artifacts SET representative_record_key='record-0',claimed_owner='old-owner',claimed_at='old-claim'")
        conn.execute("UPDATE run_source_days SET opened_dev=123,opened_ino=456,size=789,sha256='sha',footer_count=6,reason='',updated_at='old'")
        conn.execute("UPDATE source_records SET first_seen_run=NULL WHERE record_key='record-5'")
    m=migrate(pg,inventory);m.run(apply=True)
    # Every mapped column, including raw JSON bytes, large integers and nullable references, is compared.
    with opened(LegacyLedger(path,quiet())) as source:
        for table in LEDGER_TABLES:
            after=0
            while batch:=source.batch(table,after):
                with pg.transaction(read_only=True) as connection:
                    ArchiveDAO(connection,source.archive_id).verify_identical(table,[r for _,r in batch])
                after=batch[-1][0]


def test_representative_batch_performance(pg,tmp_path):
    inventory=fixture_inventory(tmp_path,records=8500)
    # Match the real ledger distribution: source + file + run/file rows, about 102k total rows.
    for path in inventory.ledgers:
        with sqlite3.connect(path) as conn:
            conn.executemany('INSERT INTO artifacts(artifact_key,ann_date,ts_code,title,url,state) VALUES(?,?,?,?,?,?)',
                ((f'bulk-{i}','2026-09-30','002245.SZ','公告标题','https://example.invalid/file.pdf','pending') for i in range(5,8500)))
            conn.executemany('INSERT INTO run_artifacts(run_id,artifact_key) VALUES(?,?)',
                             (('run-shared',f'bulk-{i}') for i in range(5,8500)))
    elapsed_sql=[];sql_started=[]
    from sqlalchemy import event
    event.listen(pg.engine,'before_cursor_execute',lambda *_:sql_started.append(time.monotonic()))
    event.listen(pg.engine,'after_cursor_execute',lambda *_:elapsed_sql.append(time.monotonic()-sql_started.pop()))
    descriptors=[];control=quiet()
    import os,resource
    control.emit=lambda _:descriptors.append(len(os.listdir('/dev/fd')))
    started=time.monotonic();result=migrate(pg,inventory,control).run(apply=True);elapsed=time.monotonic()-started
    rows=sum(t['rows_total'] for a in result['archives'] for t in a['tables'].values())
    assert rows>102000 and result['expected_batches']>=200 and max(elapsed_sql)<4
    metrics=dict(rows=rows,batches=result['expected_batches'],seconds=round(elapsed,3),
                 max_sql_seconds=round(max(elapsed_sql),4),sql_calls=len(elapsed_sql),source_http_requests=0,
                 rss_peak_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=='darwin' else 1024),2),
                 process_fd_peak=max(descriptors))
    print('Q1_PERFORMANCE '+json.dumps(metrics),flush=True)
    (tmp_path/'q1-performance.json').write_text(json.dumps(metrics))
