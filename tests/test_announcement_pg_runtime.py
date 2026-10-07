"""Q3 PG execution acceptance; never addresses the formal archive database."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import time
from types import SimpleNamespace
import threading

import httpx
import pytest
from sqlalchemy import text

from test_announcement_pg_migration import pg,pg_cluster
from test_announcement_download_cli import archive,row,run,stage_rows,latest_run,PDF,FakeSource
from src.foundation.clients.announcement_archive.core import Blocked,Control,identity
from src.foundation.clients.announcement_archive.files import Files
from src.foundation.dao.announcement_archive.ledger import Ledger
from src.foundation.dao.announcement_archive.execution import ExecutionLedger
from src.foundation.dao.announcement_archive.pg_schema import install_schema,schema_exists,validate_schema
from src.ops.runtime.announcement_archive import executor,maintenance
from src.ops.runtime.announcement_archive.control import WebControl
from src.scripts import announcement_ledger,download_announcements


def test_constructor_requires_explicit_schema_and_read_never_creates_archive(pg):
    with pytest.raises(Blocked,match='schema'):Ledger(pg,'volume','announcements',initialize=True)
    with pg.transaction(read_only=True) as conn:assert not schema_exists(conn)
    with pg.transaction() as conn:install_schema(conn)
    for writable in (False,True):
        with pytest.raises(Blocked,match='archive_not_found'):Ledger(pg,'volume','announcements',read_only=not writable)
    with pg.transaction(read_only=True) as conn:
        assert conn.scalar(text('SELECT count(*) FROM announcement_archive.archives'))==0
    ledger=Ledger(pg,'volume','announcements',initialize=True)
    assert ledger.archive['source_schema_version']==0 and ledger.archive['import_state']=='ready'
    assert ledger.active() is None and ledger.cooldown()['request_in_flight']==0
    assert pg.engine.pool.checkedout()==0


def test_archive_isolation_recovery_cooldown_same_file_key(archive):
    first=archive[1];second=Ledger(first.database,'other-volume','announcements',initialize=True)
    runs=[]
    for ledger in (first,second):
        rid=ledger.begin_run(archive[2],'same-scope');stage_rows(ledger,rid,'same-scope',[row()],seal=True)
        runs.append(rid)
    key=first.next_task(runs[0])['artifact_key']
    assert second.next_task(runs[1])['artifact_key']==key
    first.defer(123.5,'http_429');second.defer(987.5,'cooldown')
    ExecutionLedger(first).recover_abandoned()
    assert first.run(runs[0])['phase']=='interrupted'
    assert second.run(runs[1])['phase']=='downloading' and second.active()==runs[1]
    assert first.cooldown()['next_request_not_before']==123.5
    assert second.cooldown()['next_request_not_before']==987.5
    with pytest.raises(Blocked,match='run_not_found'):first.run(runs[1])


def test_concurrent_pg_claim_has_one_owner(archive):
    ledger=archive[1];rid=ledger.begin_run(archive[2],'scope');stage_rows(ledger,rid,'scope',[row()],seal=True)
    ledger.phase(rid,'stopped')
    contenders=[Ledger(ledger.database,archive[0].volume_uuid,archive[0].relative_root) for _ in range(2)]
    barrier=threading.Barrier(2);outcomes=[]
    def claim(value):
        barrier.wait()
        try:ExecutionLedger(value).claim(rid,resume=True);outcomes.append('claimed')
        except Blocked as error:outcomes.append(str(error))
    threads=[threading.Thread(target=claim,args=(value,)) for value in contenders]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=5);assert not thread.is_alive()
    assert sorted(outcomes)==['archive_already_running','claimed']
    assert ledger.run(rid)['resume_count']==1


@pytest.mark.parametrize('offline_at',['before_run','before_http','after_first_pdf'])
def test_pg_failure_never_sends_new_http_and_preserves_pdf(archive,monkeypatch,offline_at):
    ledger=archive[1];database=ledger.database;original=database.transaction;offline={'value':offline_at=='before_run'};calls=[]
    @contextmanager
    def unavailable(*args,**kwargs):
        if offline['value']:raise Blocked('archive_database_unavailable')
        with original(*args,**kwargs) as conn:yield conn
    monkeypatch.setattr(database,'transaction',unavailable)
    if offline_at=='before_run':
        with pytest.raises(Blocked):run(archive,[row()],lambda request:pytest.fail('no HTTP without PG'))
        assert not list(archive[2].output_root.rglob('*.pdf'));return
    if offline_at=='before_http':
        def started():offline['value']=True;raise Blocked('archive_database_unavailable')
        monkeypatch.setattr(ledger,'request_started',started)
    else:
        original_result=ledger.result
        def result(*args):original_result(*args);offline['value']=True
        monkeypatch.setattr(ledger,'result',result)
    code,_=run(archive,[row(1),row(2)],lambda request:calls.append(str(request.url)) or httpx.Response(200,content=PDF))
    assert code==3 and len(calls)==(1 if offline_at=='after_first_pdf' else 0)
    files=list(archive[2].output_root.rglob('*.pdf'))
    assert len(files)==len(calls) and all(path.read_bytes()==PDF for path in files)
    offline['value']=False
    assert database.engine.pool.checkedout()==0


def test_observation_failure_does_not_stop_file_business_commit(archive,monkeypatch):
    ledger=archive[1];rid=ledger.begin_run(archive[2],'scope');stage_rows(ledger,rid,'scope',[row()],seal=True)
    class Store:
        def heartbeat(self,*args,**kwargs):return False
    control=WebControl(archive[3],Store(),ledger,rid);control.wait=archive[4].wait
    def fail(*args,**kwargs):raise Blocked('injected_observation_failure')
    monkeypatch.setattr(ExecutionLedger,'observe',fail)
    calls=[]
    code=executor.execute_run(rid,archive[2],archive[3],control,archive[0],ledger,FakeSource([row()],archive[2]),'scope',httpx.Client(transport=httpx.MockTransport(lambda request:calls.append(request) or httpx.Response(200,content=PDF))),archive[4],enumerate_source=False,web=True)
    assert code==0 and len(calls)==1 and ledger.run(rid)['succeeded_count']==1
    assert control.observation_error=='archive_observation_failed' and control.fault is None
    files=list(archive[2].output_root.rglob('*.pdf'));assert len(files)==1 and files[0].read_bytes()==PDF


def test_cli_json_storage_and_integer_cursor_round_trip(archive,monkeypatch,capsys):
    from test_announcement_ledger import patch_main
    assert run(archive,[row()])[0]==0
    assert run(archive,[row(2)])[0]==0
    patch_main(archive,monkeypatch)
    base=['--output-root',str(archive[2].output_root)]
    assert announcement_ledger.main(base+['runs','--limit','1'])==0
    value=json.loads(capsys.readouterr().out)
    assert 'ledger_path' not in value and 'schema_version' not in value
    assert value['storage']==archive[1].storage
    cursor=value['result']['next_before_rowid'];assert type(cursor) is int and cursor>0
    assert announcement_ledger.main(base+['runs','--before-rowid',str(cursor)])==0
    second=json.loads(capsys.readouterr().out)
    assert second['result']['items'][0]['ledger_rowid']<cursor
    with pytest.raises(ValueError):
        from src.foundation.dao.announcement_archive.maintenance import LedgerQuery
        LedgerQuery(archive[1],archive[5]).runs(1,True)


def test_download_cli_uses_only_archive_dsn_after_volume_gates(archive,monkeypatch,capsys):
    from test_announcement_download_dg import raw_root,write_day
    from src.foundation.clients.announcement_archive.source import Source
    from src.foundation.clients.announcement_archive.volume import SourceVolume
    from pathlib import Path
    write_day(raw_root(archive),'2026-09-30',[])
    monkeypatch.setenv('DATABASE_URL','invalid://must-not-use')
    monkeypatch.setattr(executor,'get_settings',lambda:SimpleNamespace(announcement_archive_database_url='archive-only'))
    used=[]
    monkeypatch.setattr(executor,'ArchiveDatabase',lambda value:used.append(value) or archive[1].database)
    class Output:
        def open(self):return self
        def close(self):pass
        def __getattr__(self,name):return getattr(archive[0],name)
    monkeypatch.setattr(executor,'Volume',lambda *_:Output())
    monkeypatch.setattr(executor,'Source',lambda options,policy,control:Source(options,policy,control,SourceVolume(raw_root(archive),policy,archive[0].inspector)))
    assert download_announcements.main(['--start-date','2026-09-30','--end-date','2026-09-30','--interval-seconds','0'])==0
    logs=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert used==['archive-only'] and logs[-1]['storage']==archive[1].storage
    assert not any('ledger_path' in value or 'schema_version' in value for value in logs)


def test_runtime_import_graph_excludes_sqlite_and_legacy_readers():
    import ast
    from pathlib import Path
    roots=[Path('src/ops/runtime/announcement_archive'),Path('src/biz/queries/wealth/data_center')]
    paths=[p for root in roots for p in root.glob('*.py') if p.name!='migration.py']
    paths += [Path('src/foundation/dao/announcement_archive')/name for name in ('ledger.py','execution.py','maintenance.py')]
    for path in paths:
        imports=[n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,(ast.Import,ast.ImportFrom))]
        for node in imports:
            names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or '']
            assert not any('sqlite' in name or 'migration_source' in name or 'legacy_schema' in name for name in names),path


def test_real_pg_read_only_blocks_http_gate(archive):
    """The real PG server accepts reads but rejects writes; zero source requests."""
    import psycopg
    database=archive[1].database;name=database.policy.database
    assert name.startswith('q1_') and database.policy.port!=5432
    admin=dict(host='127.0.0.1',port=database.policy.port,user='q1_fixture',dbname='postgres',autocommit=True)
    rid=archive[1].begin_run(archive[2],'scope');stage_rows(archive[1],rid,'scope',[row()],seal=True)
    calls=[]
    try:
        with psycopg.connect(**admin) as conn:
            conn.execute(psycopg.sql.SQL('ALTER DATABASE {} SET default_transaction_read_only=on').format(psycopg.sql.Identifier(name)))
        database.engine.dispose()
        assert archive[1].run(rid)['phase']=='downloading'
        code=executor.execute_run(rid,archive[2],archive[3],archive[5],archive[0],archive[1],FakeSource([row()],archive[2]),'scope',httpx.Client(transport=httpx.MockTransport(lambda request:calls.append(request) or httpx.Response(200,content=PDF))),archive[4],enumerate_source=False)
        assert code==3 and not calls and not list(archive[2].output_root.rglob('*.pdf'))
        from src.foundation.clients.announcement_archive.http import Limiter
        with pytest.raises(Blocked,match='database_unavailable'):
            Limiter(archive[1],0,archive[5],archive[0],archive[4]).before()
        assert not calls
    finally:
        with psycopg.connect(**admin) as conn:
            conn.execute(psycopg.sql.SQL('ALTER DATABASE {} RESET default_transaction_read_only').format(psycopg.sql.Identifier(name)))
        database.engine.dispose()


def test_failure_family_at_scale_and_batch_timing(archive):
    from sqlalchemy import event
    import os,resource
    from pathlib import Path
    ledger=archive[1];database=ledger.database
    root=ledger.begin_run(archive[2],'scope');ledger.phase(root,'completed')
    child=ledger.begin_run(archive[2],'scope',details=dict(parent_run_id=root));ledger.phase(child,'completed')
    other=ledger.begin_run(archive[2],'scope');ledger.phase(other,'completed')
    sql_times=[]
    def before(conn,*_):conn.info['q3_start']=time.monotonic()
    def after(conn,*_):sql_times.append(time.monotonic()-conn.info.pop('q3_start'))
    event.listen(database.engine,'before_cursor_execute',before);event.listen(database.engine,'after_cursor_execute',after)
    try:
        with ledger.transaction() as conn:
            for rid,count,outcome in [(root,50000,'failed'),(child,10000,'succeeded'),(other,50000,'succeeded')]:
                ledger.write(conn,'INSERT INTO announcement_archive.run_artifacts(archive_id,run_id,artifact_key,outcome) SELECT :a,:run,lpad(i::text,64,\'0\'),:outcome FROM generate_series(0,:last) i',dict(run=rid,last=count-1,outcome=outcome))
        from src.foundation.dao.announcement_archive.execution import unresolved_sql
        sql='SELECT count(*) AS count FROM announcement_archive.run_artifacts r WHERE r.archive_id=:a AND r.run_id=:run AND '+unresolved_sql()
        started=time.monotonic();rows=ledger.rows(sql,dict(run=root,root=root));seconds=time.monotonic()-started
        assert rows[0]['count']==40000 and seconds<4
        plan=ledger.rows('EXPLAIN (ANALYZE,FORMAT JSON) '+sql,dict(run=root,root=root))[0]['QUERY PLAN']
        assert 'run_artifacts_pkey' in json.dumps(plan) or 'run_pending' in json.dumps(plan)
        rid=ledger.begin_run(archive[2],'scope');ledger.begin_day(rid,'2026-09-30')
        facts=dict(opened_dev=1,opened_ino=1,size=0,sha256='0'*64,footer_count=500)
        ledger.describe_day(rid,'2026-09-30',facts)
        started=time.monotonic();ledger.ingest(rid,'scope','2026-09-30',[row(i) for i in range(500)]);batch_seconds=time.monotonic()-started
        assert ledger.run(rid)['records_read']==500 and batch_seconds<4
        report=dict(kind='isolated PG native runtime',sourceRows=500,sourceFiles=1,sourceRowGroups=0,sourceBytes=0,sourceKind='controlled six-field fixture, not Lake performance',pgBatchRows=500,ingestSeconds=batch_seconds,failureFamilyRows=110000,unresolved=40000,unresolvedSeconds=seconds,sqlMaxSeconds=max(sql_times),sqlCalls=len(sql_times),fdCount=len(os.listdir('/dev/fd')),rssMiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024*1024),sourceHttpRequests=0,formalWrites=0)
        Path('reports/wealth_data_center_q3_profile_20261007.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    finally:
        event.remove(database.engine,'before_cursor_execute',before);event.remove(database.engine,'after_cursor_execute',after)
