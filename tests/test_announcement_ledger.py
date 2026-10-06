"""Local ledger maintenance contract tests. No formal archive, Lake or PDF service."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from src.scripts import announcement_ledger as cli
from src.ops.runtime.announcement_archive import maintenance as runtime
from src.foundation.clients.announcement_archive.core import Blocked, Cancelled
from src.foundation.clients.announcement_archive.files import Files
from src.foundation.dao.announcement_archive.ledger import Ledger
from src.foundation.dao.announcement_archive.maintenance import LedgerQuery, LedgerQueryPolicy
from src.foundation.clients.announcement_archive.files import verify_one
from src.ops.runtime.announcement_archive.maintenance import repair_one
from src.foundation.clients.announcement_archive.volume import SourceVolume, Volume
from test_announcement_download_cli import archive, row, run, stage_rows, PDF
from test_announcement_download_dg import seed_v1, OLD_KEY


def populate(archive, rows):
    ledger, options = archive[1:3]
    run_id = ledger.begin_run(options, 'dg/test/anns_d')
    stage_rows(ledger,run_id,'dg/test/anns_d',rows,seal=True)
    ledger.phase(run_id,'cancelled','fixture_enumeration_only')
    return run_id


def reader(archive, path=None, policy=LedgerQueryPolicy()):
    path = path or Path(archive[1].conn.execute('PRAGMA database_list').fetchone()[2])
    db = Ledger(path,archive[0].volume_uuid,archive[0].relative_root,read_only=True)
    return db, LedgerQuery(db,archive[5],policy)


def tasks(archive):
    return [dict(r) for r in archive[1].conn.execute('SELECT * FROM artifacts ORDER BY artifact_key')]


def protected(ledger):
    return {table:[tuple(r) for r in ledger.conn.execute(f'SELECT * FROM {table} ORDER BY rowid')]
            for table in ('runs','run_artifacts','source_records','cooldown')}


def patch_main(archive, monkeypatch):
    vol=archive[0]
    path=Path(archive[1].conn.execute('PRAGMA database_list').fetchone()[2])
    monkeypatch.setattr(Volume,'ledger_path',lambda self:path)
    monkeypatch.setattr(runtime,'SourceVolume',lambda output,policy:SourceVolume(output,archive[3],vol.inspector))
    monkeypatch.setattr(runtime,'Volume',lambda output,policy:Volume(output,archive[3],vol.inspector))
    monkeypatch.setattr(httpx.Client,'send',lambda *_a,**_k:pytest.fail('maintenance must never send HTTP'))
    return path


@pytest.mark.parametrize('args',[
    ['files','--limit','0'],['runs','--limit','101'],['show','--artifact-key','bad'],
    ['repair'],['repair','--artifact-key','A'*64],['verify','--artifact-key','../bad'],
    ['files','--start-date','20260930'],['files','--start-date','2026-10-01','--end-date','2026-09-30'],
    ['files','--state','unknown'],['runs','--before-rowid','-1'],['show','--artifact-key','0'*64,'--after-rowid','0'],
    ['runs','--run-id',"x' OR 1=1"],
])
def test_bad_input_precedes_all_io(args,monkeypatch):
    monkeypatch.setattr(runtime,'SourceVolume',lambda *_:pytest.fail('disk must not be touched'))
    with pytest.raises(SystemExit) as error:cli.main(args)
    assert error.value.code==2


@pytest.mark.parametrize('version',[1,3])
def test_read_only_schema_and_bytes_unchanged(archive,tmp_path,version):
    if version==1:
        path=tmp_path/'old.sqlite';seed_v1(path,archive)
    else:
        populate(archive,[row()]);path=Path(archive[1].conn.execute('PRAGMA database_list').fetchone()[2])
    before=path.read_bytes();tree={p.relative_to(tmp_path) for p in tmp_path.rglob('*')}
    db,q=reader(archive,path)
    try:
        assert q.archive['schema_version']==version
        assert q.summary()['dates']['file_tasks']==(5 if version==1 else 1)
        assert q.summary()['physical_status']=='not_checked'
        assert q.runs(20)['items'][0]['source_kind']==('prod_postgres' if version==1 else 'dg_raw_parquet')
        with pytest.raises(sqlite3.OperationalError):db.conn.execute('UPDATE artifacts SET state="failed"')
    finally:db.close()
    assert before==path.read_bytes() and tree=={p.relative_to(tmp_path) for p in tmp_path.rglob('*')}


def test_missing_empty_unknown_and_wrong_identity_do_not_create_or_upgrade(archive,tmp_path):
    missing=tmp_path/'missing/downloads.sqlite'
    with pytest.raises(Blocked,match='archive_ledger_missing'):
        Ledger(missing,'volume','archive',read_only=True)
    assert not missing.parent.exists()
    path=tmp_path/'old.sqlite';seed_v1(path,archive);before=path.read_bytes()
    with pytest.raises(Blocked,match='identity_mismatch'):Ledger(path,'wrong','announcements',read_only=True)
    assert path.read_bytes()==before
    empty=tmp_path/'empty.sqlite';sqlite3.connect(empty).close()
    with pytest.raises(Blocked,match='schema_invalid'):Ledger(empty,'volume','archive',read_only=True)
    with sqlite3.connect(path) as db:db.execute('UPDATE archive SET schema_version=99')
    before=path.read_bytes()
    with pytest.raises(Blocked,match='version_unsupported'):
        Ledger(path,archive[0].volume_uuid,archive[0].relative_root,read_only=True)
    assert path.read_bytes()==before


def test_files_keyset_filters_and_source_metadata_nulls(archive):
    rows=[row(i,title="引号'_%公告" if i==0 else '其他公告') for i in range(101)]
    rows[0]['rec_time']=None
    run_id=populate(archive,rows)
    another=dict(rows[0],name='另一名称',rec_time='')
    populate(archive,[another])
    missing=dict(row(999),url=None);populate(archive,[missing])
    db,q=reader(archive)
    try:
        first=q.files(100,run_id=run_id);assert len(first['items'])==100 and first['has_more']
        second=q.files(100,after_key=first['next_after_key'],run_id=run_id)
        keys=[r['artifact_key'] for r in first['items']+second['items']]
        assert len(keys)==len(set(keys))==101 and len(second['items'])==1 and not second['has_more']
        assert not q.files(20,title="' OR 1=1")['items']
        selected=q.files(20,title="'_%",ts_code='600000.SH',state='pending',
                         start_date='2026-09-30',end_date='2026-09-30')['items']
        assert len(selected)==1 and selected[0]['physical_status']=='not_checked'
        assert not q.files(20,ts_code='NO.SZ')['items']
        assert not q.files(20,end_date='2026-09-29')['items']
        show=q.show(selected[0]['artifact_key'],1);assert show['sources']['has_more']
        next_sources=q.show(selected[0]['artifact_key'],1,show['sources']['next_after_rowid'])
        metadata=[show['sources']['items'][0]['metadata'],next_sources['sources']['items'][0]['metadata']]
        assert {r['name'] for r in metadata}=={'样本公司','另一名称'}
        assert [r['rec_time'] for r in metadata]==[None,'']
        assert q.summary()['sources']=={'records':103,'missing_url':1}
        runs=q.runs(1);assert runs['has_more'] and runs['items'][0]['run_id']!=run_id
        assert q.runs(1,runs['next_before_rowid'])['items'][0]['ledger_rowid']<runs['items'][0]['ledger_rowid']
        assert q.runs(20,run_id=run_id)['items'][0]['run_id']==run_id
    finally:db.close()


LONG_SQL='WITH RECURSIVE x(n) AS (SELECT 0 UNION ALL SELECT n+1 FROM x WHERE n<100000000) SELECT SUM(n) FROM x'


def test_sql_timeout_and_handler_removed(archive):
    db,q=reader(archive,policy=replace(LedgerQueryPolicy(),query_timeout_seconds=.01,sql_progress_steps=1))
    try:
        started=time.monotonic()
        with pytest.raises(Blocked,match='query_timeout'):q.query(LONG_SQL)
        assert time.monotonic()-started<1
        assert db.conn.execute('SELECT 42').fetchone()[0]==42
    finally:db.close()


def test_sql_cancellation_and_handler_removed(archive):
    db,q=reader(archive);timer=threading.Timer(.02,archive[5].stop.set)
    try:
        timer.start()
        with pytest.raises(Cancelled):q.query(LONG_SQL)
        archive[5].stop.clear()
        assert q.query('SELECT 42 AS value')==[{'value':42}]
    finally:timer.join();db.close()


def test_verify_is_readonly_and_succeeded_is_not_physical_proof(archive):
    assert run(archive,[row()])[0]==0
    task=tasks(archive)[0];path=archive[2].output_root/task['relative_path'];before=protected(archive[1])
    assert verify_one(task,archive[0],archive[3],archive[5])['final']['status']=='matched'
    path.unlink()
    assert verify_one(task,archive[0],archive[3],archive[5])['final']['status']=='missing'
    assert archive[1].artifact(task['artifact_key'])==task
    assert protected(archive[1])==before
    result=repair_one(task['artifact_key'],archive[0],archive[1],archive[3],archive[5])
    assert result['after']['state']=='pending' and result['outcome']=='ready_for_download'
    assert result['after']['attempts']==task['attempts'] and protected(archive[1])==before
    assert result['http_requests']==0
    requests=[]
    assert run(archive,[row()],lambda req:requests.append(req) or httpx.Response(200,content=PDF))[0]==0
    assert len(requests)==1 and path.read_bytes()==PDF


def test_corruption_preserved_then_only_one_file_redownloads(archive):
    assert run(archive,[row(1),row(2)])[0]==0
    damaged,valid=tasks(archive);path=archive[2].output_root/damaged['relative_path'];path.write_bytes(b'corrupt')
    before=protected(archive[1])
    assert verify_one(damaged,archive[0],archive[3],archive[5])['final']['status']=='mismatch'
    result=repair_one(damaged['artifact_key'],archive[0],archive[1],archive[3],archive[5])
    assert path.read_bytes()==b'corrupt' and result['after']['relative_path']!=damaged['relative_path']
    assert result['after']['state']=='pending' and protected(archive[1])==before
    unchanged=repair_one(valid['artifact_key'],archive[0],archive[1],archive[3],archive[5])
    assert unchanged['outcome']=='already_valid' and unchanged['before']==unchanged['after']
    requests=[]
    assert run(archive,[row(1),row(2)],lambda req:requests.append(req) or httpx.Response(200,content=PDF))[0]==0
    assert len(requests)==1 and path.read_bytes()==b'corrupt'


@pytest.mark.parametrize('window',['part','final','lost'])
def test_prepared_repair_windows_preserve_history(archive,window):
    populate(archive,[row()]);ledger=archive[1];files=Files(archive[0],ledger,archive[3],archive[5])
    task=files.allocate(tasks(archive)[0]);final=archive[2].output_root/task['relative_path'];final.parent.mkdir(parents=True)
    path=final.parent/(files.part_name(task) if window=='part' else final.name)
    if window!='lost':path.write_bytes(PDF)
    ledger.prepared(task['artifact_key'],len(PDF),hashlib.sha256(PDF).hexdigest())
    task=ledger.artifact(task['artifact_key']);before=protected(ledger)
    inspection=verify_one(task,archive[0],archive[3],archive[5])
    assert inspection['ledger_state']=='prepared'
    result=repair_one(task['artifact_key'],archive[0],ledger,archive[3],archive[5])
    assert protected(ledger)==before
    if window=='lost':
        assert result['outcome']=='failed' and result['after']['error']=='prepared_evidence_mismatch'
    else:
        assert result['outcome']=='recovered' and result['after']['state']=='succeeded' and final.read_bytes()==PDF


@pytest.mark.parametrize('kind',['fifo','symlink','hardlink','escape'])
def test_verify_blocks_unsafe_file_without_hang_or_mutation(archive,tmp_path,kind):
    assert run(archive,[row()])[0]==0
    task=tasks(archive)[0];final=archive[2].output_root/task['relative_path'];before=dict(task)
    if kind=='fifo':final.unlink();os.mkfifo(final)
    elif kind=='symlink':final.unlink();final.symlink_to(tmp_path/'absent')
    elif kind=='hardlink':os.link(final,tmp_path/'hardlink')
    else:task['relative_path']='../escape.pdf'
    started=time.monotonic()
    with pytest.raises((Blocked,OSError)):verify_one(task,archive[0],archive[3],archive[5])
    assert time.monotonic()-started<1 and archive[1].artifact(before['artifact_key'])==before


def test_repair_cancel_and_promote_state_failure_keep_evidence(archive,monkeypatch):
    populate(archive,[row()]);ledger=archive[1];files=Files(archive[0],ledger,archive[3],archive[5])
    task=files.allocate(tasks(archive)[0]);path=archive[2].output_root/task['relative_path'];path.parent.mkdir(parents=True)
    part=path.parent/files.part_name(task);part.write_bytes(PDF)
    ledger.prepared(task['artifact_key'],len(PDF),hashlib.sha256(PDF).hexdigest());before=protected(ledger)
    archive[5].stop.set()
    with pytest.raises(Cancelled):repair_one(task['artifact_key'],archive[0],ledger,archive[3],archive[5])
    assert part.read_bytes()==PDF and not path.exists();archive[5].stop.clear()
    original=ledger.state
    def fail(key,state,error=None):
        if state=='succeeded':raise sqlite3.OperationalError('injected ledger failure')
        return original(key,state,error)
    with monkeypatch.context() as patch:
        patch.setattr(ledger,'state',fail)
        with pytest.raises(sqlite3.OperationalError):repair_one(task['artifact_key'],archive[0],ledger,archive[3],archive[5])
    assert path.read_bytes()==PDF and ledger.artifact(task['artifact_key'])['state']=='prepared'
    assert repair_one(task['artifact_key'],archive[0],ledger,archive[3],archive[5])['outcome']=='recovered'
    assert protected(ledger)==before


def test_real_main_queries_missing_key_and_lock_conflict(archive,monkeypatch,capsys):
    assert run(archive,[row()])[0]==0
    path=patch_main(archive,monkeypatch);before=path.read_bytes();root=['--output-root',str(archive[2].output_root)]
    assert cli.main(root+['summary'])==0
    summary=json.loads(capsys.readouterr().out);assert summary['result']['dates']['file_tasks']==1
    assert path.read_bytes()==before
    assert cli.main(root+['repair','--artifact-key','0'*64])==3
    assert json.loads(capsys.readouterr().out)['error']=='artifact_not_found'
    assert path.read_bytes()==before
    key=tasks(archive)[0]['artifact_key']
    assert cli.main(root+['repair','--artifact-key',key])==3
    assert json.loads(capsys.readouterr().out)['error']=='archive_already_running'
    assert path.read_bytes()==before
    archive[0].close()
    assert cli.main(root+['repair','--artifact-key',key])==0
    assert json.loads(capsys.readouterr().out)['result']['outcome']=='already_valid'
    assert path.read_bytes()==before


def test_real_main_verify_missing_returns_one_and_no_write(archive,monkeypatch,capsys):
    assert run(archive,[row()])[0]==0
    path=patch_main(archive,monkeypatch);task=tasks(archive)[0];(archive[2].output_root/task['relative_path']).unlink()
    before=path.read_bytes()
    assert cli.main(['--output-root',str(archive[2].output_root),'verify','--artifact-key',task['artifact_key']])==1
    assert json.loads(capsys.readouterr().out)['result']['final']['status']=='missing' and path.read_bytes()==before


def test_query_paths_do_not_initialize_archive_or_read_lake(archive,monkeypatch,capsys):
    path=patch_main(archive,monkeypatch)
    assert cli.main(['--output-root',str(archive[2].output_root/'absent'),'summary'])==3
    assert not (archive[2].output_root/'absent').exists()
    lake=archive[0].mount/'data_lake';lake.mkdir()
    before=path.read_bytes()
    assert cli.main(['--output-root',str(lake),'summary'])==3
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['error']=='lake_path_forbidden'
    assert path.read_bytes()==before


def test_real_main_v1_repair_upgrades_only_selected_known_archive(archive,tmp_path,monkeypatch,capsys):
    old=tmp_path/'v1.sqlite';seed_v1(old,archive)
    patch_main(archive,monkeypatch)
    monkeypatch.setattr(Volume,'ledger_path',lambda self:old)
    root=['--output-root',str(archive[2].output_root)]
    before=old.read_bytes()
    assert cli.main(root+['show','--artifact-key',OLD_KEY])==0
    assert json.loads(capsys.readouterr().out)['schema_version']==1 and old.read_bytes()==before
    with sqlite3.connect(old) as db:
        history={t:list(db.execute('SELECT * FROM '+t+' ORDER BY rowid')) for t in ('run_artifacts','cooldown')}
    assert cli.main(root+['repair','--artifact-key','0'*64])==3
    capsys.readouterr();assert old.read_bytes()==before
    archive[0].close()
    assert cli.main(root+['repair','--artifact-key',OLD_KEY])==0
    assert json.loads(capsys.readouterr().out)['schema_version']==3
    with sqlite3.connect(old) as db:
        assert db.execute('SELECT schema_version FROM archive').fetchone()[0]==3
        assert {t:[tuple(row[:len(history[t][0])]) for row in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in history}==history
        assert db.execute('SELECT COUNT(*) FROM source_records').fetchone()[0]==5


@pytest.mark.parametrize('state',['failed','blocked','downloading'])
def test_failed_or_interrupted_single_task_can_retry_without_resetting_history(archive,state):
    populate(archive,[row()]);ledger=archive[1];key=tasks(archive)[0]['artifact_key']
    ledger.state(key,state,'old error');before=protected(ledger)
    result=repair_one(key,archive[0],ledger,archive[3],archive[5])
    assert result['after']['state']=='pending' and result['after']['error'] is None
    assert result['outcome']=='ready_for_download' and result['after']['attempts']==result['before']['attempts']
    assert protected(ledger)==before


def test_query_budget_is_for_whole_snapshot_and_limit_is_checked(archive):
    db,q=reader(archive,policy=replace(LedgerQueryPolicy(),query_timeout_seconds=.01))
    try:
        with pytest.raises(ValueError):q.files(101)
        time.sleep(.015)
        with pytest.raises(Blocked,match='query_timeout'):q.summary()
        assert db.conn.execute('SELECT 1').fetchone()[0]==1
    finally:db.close()


def test_cli_real_sigint_interrupts_long_sql_without_writes(archive,tmp_path):
    import signal
    import subprocess
    import sys
    populate(archive,[row()])
    path=Path(archive[1].conn.execute('PRAGMA database_list').fetchone()[2]);before=path.read_bytes()
    script=tmp_path/'cancel_query.py'
    script.write_text('''import sys,json\nfrom pathlib import Path\nfrom src.scripts import announcement_ledger as cli\nfrom src.ops.runtime.announcement_archive import maintenance as runtime\nfrom src.foundation.clients.announcement_archive.volume import SourceVolume,Volume\nfrom src.foundation.dao.announcement_archive.maintenance import LedgerQuery\nfrom src.foundation.clients.announcement_archive import volume as mod\nmount=Path(sys.argv[1]);root=Path(sys.argv[2]);db=Path(sys.argv[3])\nmod.sys.platform='darwin'\nmod.os.path.ismount=lambda value:Path(value)==mount\ninfo=dict(MountPoint=str(mount),VolumeUUID='test-external-volume',DeviceIdentifier='disk7s1',Internal=False,VirtualOrPhysical='Physical')\nruntime.SourceVolume=lambda output,policy:SourceVolume(output,policy,lambda value:info)\nVolume.ledger_path=lambda self:db\ndef summary(self):\n print('sql_started',flush=True)\n return self.query("WITH RECURSIVE x(n) AS (SELECT 0 UNION ALL SELECT n+1 FROM x WHERE n<100000000) SELECT SUM(n) FROM x")\nLedgerQuery.summary=summary\nraise SystemExit(cli.main(['--output-root',str(root),'summary']))\n''')
    env=dict(os.environ,PYTHONPATH=str(Path.cwd()))
    p=subprocess.Popen([sys.executable,'-B',str(script),str(archive[0].mount),str(archive[2].output_root),str(path)],
                       env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        import select
        assert select.select([p.stdout],[],[],5)[0], 'no live query marker'
        assert p.stdout.readline().strip()=='sql_started'
        time.sleep(.02);p.send_signal(signal.SIGINT)
        out,err=p.communicate(timeout=5)
        assert p.returncode==130 and json.loads(out)['error']=='user_cancelled' and not err
        assert path.read_bytes()==before
    finally:
        if p.poll() is None:p.kill();p.wait()


@pytest.mark.parametrize('change',[{'page_default':0},{'page_max':101},{'query_timeout_seconds':0},
                                  {'query_timeout_seconds':float('inf')},{'query_timeout_seconds':float('nan')},
                                  {'sql_progress_steps':0}])
def test_invalid_policy_fails_without_starting_snapshot(archive,change):
    with pytest.raises(ValueError,match='policy_invalid'):
        LedgerQuery(archive[1],archive[5],replace(LedgerQueryPolicy(),**change))
    assert not archive[1].conn.in_transaction


def test_cross_device_fingerprint_is_rejected(archive):
    from types import SimpleNamespace
    assert run(archive,[row()])[0]==0
    task=tasks(archive)[0];path=Path(task['relative_path'])
    files=Files(SimpleNamespace(device=archive[0].device+1),archive[1],archive[3],archive[5])
    with archive[0].directory(str(path.parent)) as fd:
        with pytest.raises(Blocked,match='archive_file_device_changed'):files.fingerprint(fd,path.name)


def test_cancel_after_prepared_part_verification_preserves_then_recovers(archive,monkeypatch):
    populate(archive,[row()]);ledger=archive[1];files=Files(archive[0],ledger,archive[3],archive[5])
    task=files.allocate(tasks(archive)[0]);final=archive[2].output_root/task['relative_path'];final.parent.mkdir(parents=True)
    part=final.parent/files.part_name(task);part.write_bytes(PDF)
    ledger.prepared(task['artifact_key'],len(PDF),hashlib.sha256(PDF).hexdigest())
    before=protected(ledger);original=Files.fingerprint
    def cancel_on_part(self,fd,name):
        result=original(self,fd,name)
        if name==files.part_name(task):archive[5].stop.set()
        return result
    with monkeypatch.context() as patch:
        patch.setattr(Files,'fingerprint',cancel_on_part)
        with pytest.raises(Cancelled):repair_one(task['artifact_key'],archive[0],ledger,archive[3],archive[5])
    assert part.read_bytes()==PDF and not final.exists() and ledger.artifact(task['artifact_key'])['state']=='prepared'
    archive[5].stop.clear()
    assert repair_one(task['artifact_key'],archive[0],ledger,archive[3],archive[5])['outcome']=='recovered'
    assert protected(ledger)==before


def test_main_ledger_symlink_and_wrong_volume_are_readonly_failures(archive,tmp_path,monkeypatch,capsys):
    populate(archive,[row()]);path=patch_main(archive,monkeypatch);before=path.read_bytes()
    link=tmp_path/'alias.sqlite';link.symlink_to(path)
    monkeypatch.setattr(Volume,'ledger_path',lambda self:link)
    root=['--output-root',str(archive[2].output_root)]
    assert cli.main(root+['summary'])==3
    assert json.loads(capsys.readouterr().out)['error']=='symlink_path_forbidden'
    monkeypatch.setattr(Volume,'ledger_path',lambda self:path)
    archive[6]['VolumeUUID']='wrong-volume'
    assert cli.main(root+['repair','--artifact-key',tasks(archive)[0]['artifact_key']])==3
    assert json.loads(capsys.readouterr().out)['error']=='archive_identity_mismatch'
    archive[6]['VolumeUUID']=archive[0].volume_uuid
    assert path.read_bytes()==before


def test_cancel_at_write_gate_does_not_upgrade_old_ledger(archive,tmp_path,monkeypatch,capsys):
    old=tmp_path/'v1.sqlite';seed_v1(old,archive);before=old.read_bytes()
    patch_main(archive,monkeypatch);monkeypatch.setattr(Volume,'ledger_path',lambda self:old)
    control=archive[5];monkeypatch.setattr(runtime,'Control',lambda policy:control)
    original=Volume.open
    def cancel_after_open(self):
        result=original(self);control.stop.set();return result
    monkeypatch.setattr(Volume,'open',cancel_after_open);archive[0].close()
    assert cli.main(['--output-root',str(archive[2].output_root),'repair','--artifact-key',OLD_KEY])==130
    assert json.loads(capsys.readouterr().out)['error']=='user_cancelled'
    assert old.read_bytes()==before


@pytest.mark.parametrize('read_only',[True,False])
def test_malformed_archive_header_is_structured_failure_without_changes(archive,tmp_path,read_only):
    path=tmp_path/'old.sqlite';seed_v1(path,archive)
    with sqlite3.connect(path) as db:db.execute('ALTER TABLE archive RENAME COLUMN volume_uuid TO malformed')
    before=path.read_bytes()
    with pytest.raises(Blocked,match='archive_schema_invalid'):
        Ledger(path,archive[0].volume_uuid,archive[0].relative_root,read_only=read_only)
    assert path.read_bytes()==before
