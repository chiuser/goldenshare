"""DC1 integration gates, using only temporary SQLite, volumes, streams and processes."""
from __future__ import annotations

import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from dataclasses import replace

import httpcore
import httpx
import pytest

from src.foundation.clients.announcement_archive.core import Blocked, Cancelled, Control, DownloadPolicy, FileFailed
from src.foundation.clients.announcement_archive.files import valid_url
from src.foundation.clients.announcement_archive.locking import ExecutionLock
from src.foundation.clients.announcement_archive.transport import PublicHTTPTransport, PublicNetworkBackend, public_address
from src.foundation.clients.announcement_archive.volume import Volume
from src.foundation.dao.announcement_archive.ledger import Ledger, SCHEMA
from src.foundation.dao.announcement_archive.maintenance import LedgerQuery
from test_announcement_download_cli import archive, row, run, stage_rows, latest_run, PDF
from test_announcement_download_dg import seed_v1


def seed_v2(path, archive):
    with sqlite3.connect(path) as db:
        for sql in SCHEMA:
            db.execute(sql)
        db.execute('INSERT INTO archive VALUES(1,2,?,?,?)', (archive[0].volume_uuid,archive[0].relative_root,'old-date'))
        db.execute("INSERT INTO cooldown VALUES(1,10,9999999999,1,'http_429')")
        db.execute("INSERT INTO runs(run_id,phase,source_kind,enumeration_sealed) VALUES('old2','completed','dg_raw_parquet',1)")
        db.execute("INSERT INTO artifacts(artifact_key,ann_date,ts_code,title,url,relative_path,path_fold,state,attempts) VALUES(?,?,?,?,?,?,?,'succeeded',7)",
                   ('0'*64,'2026-09-30','600000.SH','旧标题','https://example.com/a.pdf','old.pdf','old.pdf'))
        db.execute("INSERT INTO run_artifacts VALUES('old2',?,'succeeded',7)", ('0'*64,))
        db.execute("INSERT INTO source_records VALUES('oldscope','oldkey',NULL,?,?,'old2','old2')", ('{"name":null,"rec_time":""}','0'*64))


@pytest.mark.parametrize('version',[1,2,3])
def test_all_schema_versions_are_observed_without_any_writes(archive,tmp_path,version):
    path=tmp_path/f'v{version}.sqlite'
    if version==1: seed_v1(path,archive)
    else:
        seed_v2(path,archive)
        if version==3:
            Ledger(path,archive[0].volume_uuid,archive[0].relative_root).close()
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    db=Ledger(path,archive[0].volume_uuid,archive[0].relative_root,read_only=True)
    try:
        query=LedgerQuery(db,archive[5]);assert query.version==version
        assert query.files(20)['items']
        assert query.show(query.files(20)['items'][0]['artifact_key'],20)['sources']['items']
    finally: db.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before


@pytest.mark.parametrize('version',[1,2])
def test_atomic_upgrade_preserves_every_original_column(archive,tmp_path,version):
    path=tmp_path/'upgrade.sqlite'
    (seed_v1 if version==1 else seed_v2)(path,archive)
    with sqlite3.connect(path) as db:
        before={t:[dict(zip([c[1] for c in db.execute(f'PRAGMA table_info({t})')],r))
                   for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')]
                for t in ('artifacts','run_artifacts','source_records','runs','cooldown')}
    db=Ledger(path,archive[0].volume_uuid,archive[0].relative_root)
    try:
        assert db.conn.execute('SELECT schema_version FROM archive').fetchone()[0]==3
        rename={'upper_id':'legacy_upper_id','after_id':'legacy_after_id','row_key_hash':'record_key','raw_id':'legacy_raw_id'}
        for table, rows in before.items():
            after=[dict(r) for r in db.conn.execute(f'SELECT * FROM {table} ORDER BY rowid')]
            assert len(after)==len(rows)
            for old,new in zip(rows,after):
                assert all(new[rename.get(k,k)]==v for k,v in old.items())
        assert db.conn.execute('SELECT active_run_id FROM archive_execution').fetchone()[0] is None
        assert not db.conn.execute('SELECT 1 FROM attempt_log').fetchone()
        assert db.conn.execute('PRAGMA journal_mode').fetchone()[0]=='delete'
    finally: db.close()
    Ledger(path,archive[0].volume_uuid,archive[0].relative_root).close()


@pytest.mark.parametrize('version',[1,2])
def test_upgrade_rollback_never_leaves_intermediate_v2_or_v3(archive,tmp_path,monkeypatch,version):
    path=tmp_path/'rollback.sqlite'
    (seed_v1 if version==1 else seed_v2)(path,archive)
    before=path.read_bytes()
    original=Ledger._validate_schema
    def fail(self,v):
        if v==3: raise sqlite3.OperationalError('injected validation failure')
        return original(self,v)
    with monkeypatch.context() as patch:
        patch.setattr(Ledger,'_validate_schema',fail)
        with pytest.raises(sqlite3.OperationalError): Ledger(path,archive[0].volume_uuid,archive[0].relative_root)
    assert path.read_bytes()==before
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT schema_version FROM archive').fetchone()[0]==version
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='attempt_log'").fetchone()


def test_schema3_tampering_and_unknown_version_do_not_write(archive,tmp_path):
    path=tmp_path/'bad.sqlite';seed_v2(path,archive)
    Ledger(path,archive[0].volume_uuid,archive[0].relative_root).close()
    with sqlite3.connect(path) as db:db.execute('ALTER TABLE run_sessions ADD COLUMN surprise TEXT')
    before=path.read_bytes()
    with pytest.raises(Blocked,match='schema_invalid'):Ledger(path,archive[0].volume_uuid,archive[0].relative_root)
    assert path.read_bytes()==before
    with sqlite3.connect(path) as db:db.execute('UPDATE archive SET schema_version=99')
    before=path.read_bytes()
    with pytest.raises(Blocked,match='version_unsupported'):Ledger(path,archive[0].volume_uuid,archive[0].relative_root)
    assert path.read_bytes()==before


def test_run_slot_attempt_history_and_terminal_release(archive):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls)==1 else httpx.Response(200,content=PDF)
    assert run(archive,[row()],handler)[0]==0
    ledger=archive[1];rid=latest_run(ledger)['run_id']
    assert ledger.conn.execute('SELECT active_run_id FROM archive_execution').fetchone()[0] is None
    attempts=[dict(r) for r in ledger.conn.execute('SELECT * FROM attempt_log ORDER BY attempt_seq')]
    assert [(a['attempt_seq'],a['outcome'],a['http_status']) for a in attempts]==[(1,'retryable',503),(2,'succeeded',200)]
    assert all(a['ended_at'] and a['session_seq']==1 for a in attempts)
    assert attempts[1]['bytes']==len(PDF)
    assert ledger.conn.execute('SELECT ended_at FROM run_sessions WHERE run_id=?',(rid,)).fetchone()[0]
    key=ledger.conn.execute('SELECT artifact_key FROM artifacts').fetchone()[0]
    before=ledger.stats(rid)
    ledger.result(rid,key,'succeeded');assert ledger.stats(rid)==before
    with pytest.raises(Blocked,match='already_final'):ledger.result(rid,key,'failed')
    assert ledger.stats(rid)==before


def test_same_owner_cannot_admit_two_active_runs(archive):
    ledger=archive[1];rid=ledger.begin_run(archive[2],'scope')
    with pytest.raises(Blocked,match='already_running'):ledger.begin_run(archive[2],'scope')
    assert ledger.conn.execute('SELECT active_run_id FROM archive_execution').fetchone()[0]==rid
    ledger.phase(rid,'cancelled')
    assert ledger.begin_run(archive[2],'scope')!=rid


def test_reopen_never_resumes_http_and_orphan_attempt_remains_evidence(archive):
    ledger=archive[1];rid=ledger.begin_run(archive[2],'scope')
    stage_rows(ledger,rid,'scope',[row()],seal=True)
    key=ledger.next_task(rid)['artifact_key'];ledger.attempt(rid,key)
    ledger.close()
    db=Ledger(archive[0].ledger_path(),archive[0].volume_uuid,archive[0].relative_root)
    try:
        # Opening/migrating the ledger alone does not receive/execute a task.
        assert db.conn.execute('SELECT COUNT(*) FROM attempt_log').fetchone()[0]==1
        db.begin_run(archive[2],'scope')
        assert db.conn.execute('SELECT phase FROM runs WHERE run_id=?',(rid,)).fetchone()[0]=='interrupted'
        attempt=db.conn.execute('SELECT * FROM attempt_log').fetchone()
        assert attempt['outcome']=='interrupted' and attempt['ended_at']
    finally:db.close()


def test_title_choice_is_deterministic_without_renaming_existing_artifact(archive):
    values=[row(title=None),row(title='董事会A'),row(title='董事会B')]
    assert run(archive,values)[0]==0
    before=dict(archive[1].conn.execute('SELECT * FROM artifacts').fetchone())
    assert before['title'] in ('董事会A','董事会B')
    assert run(archive,list(reversed(values)),lambda _:pytest.fail('existing file reused'))[0]==0
    after=archive[1].artifact(before['artifact_key'])
    assert (after['title'],after['relative_path'],after['representative_record_key'])==(before['title'],before['relative_path'],before['representative_record_key'])
    assert archive[1].conn.execute('SELECT COUNT(*) FROM source_records').fetchone()[0]==3


def test_local_lock_prevents_mount_lock_inode_replacement_race(archive):
    external=archive[2].output_root/'.state/archive.lock'
    external.unlink()  # This is a temporary simulated volume, not a real archive.
    other=Volume(archive[2].output_root,archive[3],archive[0].inspector)
    try:
        with pytest.raises(Blocked,match='already_running'):other.open()
    finally:other.close()
    assert not external.exists()  # Failure preceded external lock/probe creation.


def test_local_lock_is_released_by_real_process_exit(tmp_path):
    path=tmp_path/'execution.lock'
    script="from pathlib import Path; import os,sys; from src.foundation.clients.announcement_archive.locking import ExecutionLock; lock=ExecutionLock(Path(sys.argv[1])).open(); print('locked',flush=True); sys.stdin.readline(); os._exit(73)"
    process=subprocess.Popen([sys.executable,'-c',script,str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert process.stdout.readline().strip()=='locked'
        with pytest.raises(Blocked,match='already_running'):ExecutionLock(path).open()
        process.stdin.write('\n');process.stdin.flush();assert process.wait(timeout=5)==73
        ExecutionLock(path).open().close()
    finally:
        if process.poll() is None:process.kill();process.wait()
        process.stdin.close();process.stdout.close()


@pytest.mark.parametrize('address',['127.0.0.1','10.0.0.1','172.16.1.1','192.168.1.1','169.254.169.254','0.0.0.0','::1','fc00::1','fe80::1','::ffff:127.0.0.1','192.0.2.1','2002:0a00:0001::1','64:ff9b::a00:1','224.0.0.1','ff02::1'])
def test_private_and_reserved_targets_are_rejected(address):
    with pytest.raises(FileFailed):public_address(address)


def answers(*addresses):
    return [(socket.AF_INET6 if ':' in value else socket.AF_INET,socket.SOCK_STREAM,6,'',(value,443)) for value in addresses]


def test_mixed_dns_answers_never_connect_and_dns_rebinding_has_no_second_lookup():
    control=Control(DownloadPolicy(),lambda _:None);calls=[];dns=[]
    def resolver(*args,**kwargs):dns.append(args);return answers('1.1.1.1')
    backend=PublicNetworkBackend(control,resolver,lambda host,*a,**k:calls.append(host) or object())
    backend.connect_tcp('static.cninfo.com.cn',443,timeout=1)
    assert calls==['1.1.1.1'] and len(dns)==1
    backend=PublicNetworkBackend(control,lambda *a,**k:answers('1.1.1.1','127.0.0.1'),lambda *a,**k:pytest.fail('unsafe answer'))
    with pytest.raises(FileFailed):backend.connect_tcp('example.com',443,timeout=1)


def test_public_ipv6_is_pinned():
    calls=[];control=Control(DownloadPolicy(),lambda _:None)
    backend=PublicNetworkBackend(control,lambda *a,**k:answers('2606:4700:4700::1111'),lambda host,*a,**k:calls.append(host) or object())
    backend.connect_tcp('example.com',443,1)
    assert calls==['2606:4700:4700::1111']


def test_dns_stall_is_bounded_and_cancel_is_checked():
    finished=threading.Event();control=Control(replace(DownloadPolicy(),wait_slice=.01),lambda _:None)
    def stall(*a,**k):finished.wait(1);return answers('1.1.1.1')
    backend=PublicNetworkBackend(control,stall)
    try:
        with pytest.raises(Blocked,match='dns_timeout'):backend.connect_tcp('example.com',443,.02)
        control.stop.set()
        with pytest.raises(Cancelled):backend.connect_tcp('example.com',443,.1)
    finally:finished.set()


def test_original_host_and_tls_name_survive_ip_binding():
    sent=[];tls=[];connections=[];control=Control(DownloadPolicy(),lambda _:None)
    class Stream(httpcore.NetworkStream):
        def __init__(self):self.body=b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok'
        def read(self,max_bytes,timeout=None):result,self.body=self.body[:max_bytes],self.body[max_bytes:];return result
        def write(self,buffer,timeout=None):sent.append(buffer)
        def close(self):pass
        def get_extra_info(self,info):return None
        def start_tls(self,ssl_context,server_hostname=None,timeout=None):tls.append(server_hostname);return self
    def connect(host,*args,**kwargs):connections.append(host);return Stream()
    backend=PublicNetworkBackend(control,lambda *a,**k:answers('1.1.1.1'),connect)
    with httpx.Client(transport=PublicHTTPTransport(control,backend),trust_env=False) as client:
        assert client.get('https://static.cninfo.com.cn/a.pdf').text=='ok'
    assert connections==['1.1.1.1'] and tls==['static.cninfo.com.cn']
    assert b'Host: static.cninfo.com.cn' in b''.join(sent)


def test_redirect_private_target_never_sends_second_request(archive):
    calls=[];control=archive[5]
    class Stream(httpcore.NetworkStream):
        def __init__(self):self.body=b'HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/private\r\nContent-Length: 0\r\n\r\n'
        def read(self,max_bytes,timeout=None):out,self.body=self.body,b'';return out
        def write(self,buffer,timeout=None):pass
        def close(self):pass
        def get_extra_info(self,info):return None
        def start_tls(self,*a,**k):return self
    backend=PublicNetworkBackend(control,lambda *a,**k:answers('1.1.1.1'),lambda host,*a,**k:calls.append(host) or Stream())
    from src.ops.runtime.announcement_archive.executor import execute
    from test_announcement_download_cli import FakeSource
    client=httpx.Client(transport=PublicHTTPTransport(control,backend),trust_env=False)
    assert execute(archive[2],archive[3],control,archive[0],archive[1],FakeSource([row()],archive[2]),'scope',client,archive[4])==1
    assert calls==['1.1.1.1'] and not list(archive[2].output_root.rglob('*.pdf'))


def test_cli_entrypoints_keep_arguments_and_no_legacy_core_imports():
    from src.scripts.download_announcements import parse_options
    options=parse_options(['--start-date','2026-09-30','--end-date','2026-09-30','--interval-seconds','0'])
    assert options.interval_seconds==0
    root=Path(__file__).parents[1]
    assert not (root/'src/scripts/announcement_download').exists()
    for path in [*root.joinpath('src').rglob('*.py'),*root.joinpath('tests').glob('test_announcement*.py')]:
        assert 'src.scripts.'+'announcement_download' not in path.read_text()


def test_pypinyin_is_pinned_optional_and_python3_13_samples_work():
    import tomllib
    project=tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text())['project']
    assert 'pypinyin==0.55.0' in project['optional-dependencies']['local-lake']
    assert not any('pypinyin' in item for item in project['dependencies'])
    pypinyin=pytest.importorskip("pypinyin")
    assert pypinyin.__version__=='0.55.0'
    for name,expected in [('平安银行','PAYH'),('招商银行','ZSYH'),('深发展A','SFZA'),('重庆银行','CQYH'),('ST平安银行','STPAYH')]:
        assert ''.join(pypinyin.lazy_pinyin(name,style=pypinyin.Style.FIRST_LETTER)).upper()==expected


def test_result_observation_failure_after_physical_success_preserves_pdf(archive,monkeypatch):
    def fail(*args,**kwargs):
        raise sqlite3.OperationalError('injected after successful file commit')
    with monkeypatch.context() as patch:
        patch.setattr(archive[1],'finish_attempt',fail)
        assert run(archive,[row()])[0]==3
    task=dict(archive[1].conn.execute('SELECT * FROM artifacts').fetchone())
    assert task['state']=='succeeded'
    assert (archive[2].output_root/task['relative_path']).read_bytes()==PDF
    assert run(archive,[row()],lambda _:pytest.fail('must recover without HTTP'))[0]==0
    assert latest_run(archive[1])['skipped_count']==1


def test_representative_selection_across_batches_does_not_depend_on_source_order(archive,tmp_path):
    values=[row(title=None),row(title='公告A'),row(title='公告B')]
    representatives=[]
    for number,items in enumerate((values,list(reversed(values)))):
        ledger=Ledger(tmp_path/f'ordering{number}.sqlite',archive[0].volume_uuid,archive[0].relative_root)
        try:
            rid=ledger.begin_run(archive[2],'scope')
            facts=dict(opened_dev=1,opened_ino=1,size=0,sha256='0'*64,footer_count=3)
            ledger.begin_day(rid,'2026-09-30');ledger.describe_day(rid,'2026-09-30',facts)
            for item in items:ledger.ingest(rid,'scope','2026-09-30',[item])
            ledger.complete_day(rid,'2026-09-30',facts);ledger.seal(rid)
            task=ledger.next_task(rid)
            representatives.append((task['title'],task['representative_record_key']))
        finally:ledger.close()
    assert representatives[0]==representatives[1] and representatives[0][0] is not None


def test_new_ledger_and_local_lock_are_private_files(archive):
    assert archive[0].ledger_path().stat().st_mode & 0o777 == 0o600
    assert archive[0].ledger_path().parent.stat().st_mode & 0o777 == 0o700
    assert (archive[0].ledger_path().parent/'execution.lock').stat().st_mode & 0o777 == 0o600
