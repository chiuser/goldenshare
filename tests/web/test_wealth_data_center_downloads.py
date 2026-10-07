"""DC3 actual routes, Parquet/SQLite/files and injected external transport; no formal writes."""
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI,APIRouter
from fastapi.testclient import TestClient

from test_announcement_catalog import query_archive,archive,row,pg,pg_cluster
from test_announcement_download_cli import PDF
from test_announcement_download_dg import raw_root,write_day
from src.foundation.clients.announcement_archive.binding import ArchiveBinding
from src.foundation.clients.announcement_archive.core import Blocked,Control,DownloadPolicy
from src.foundation.clients.announcement_archive.source import Source
from src.foundation.clients.announcement_archive.volume import Volume,SourceVolume
from src.foundation.clients.announcement_archive.names import NameInitials
from src.foundation.clients.announcement_archive.presence import ArchivePresence
from src.foundation.config.settings import Settings
from src.foundation.dao.announcement_archive.ledger import Ledger
from src.ops.runtime.announcement_archive.source_runtime import AnnouncementSourceRuntime
from src.ops.runtime.announcement_archive.supervisor import ArchiveSupervisor
from src.biz.services.wealth.data_center.download_service import AnnouncementDownloadService
from src.app.runtime.announcement_archive_lifespan import include_data_center,install_data_center
from src.app.exceptions import install_exception_handlers,WebAppError
from src.app.auth.dependencies import get_current_user

P='/api/v1/wealth/data-center/announcements'


@pytest.fixture
def downloads(query_archive,tmp_path,monkeypatch):
    query,a,source=query_archive
    oldvolume,oldledger,options,policy,*_=a
    policy=replace(policy,batch_size=500,backoff_seconds=0)
    binding=ArchiveBinding(tmp_path/'binding/web-archive.json',options.output_root)
    monkeypatch.setattr(binding,'ledger_path',lambda value=None:tmp_path/'local-state/downloads.sqlite')
    binding.remember(oldvolume);oldledger.close();oldvolume.close()
    query.presence.volume.close()
    query.presence.volume=SourceVolume(oldvolume.mount,policy,oldvolume.inspector).open()
    def source_factory(opts,control,root):
        return Source(opts,policy,control,SourceVolume(root,policy,oldvolume.inspector)).open()
    def resources(opts,control,*,source_required=True):
        v=Volume(opts.output_root,policy,oldvolume.inspector);s=l=None
        try:
            v.open()
            if source_required:s=source_factory(opts,control,raw_root(a))
            l=Ledger(binding.ledger_path(),v.volume_uuid,v.relative_root)
            return v,l,s
        except BaseException:
            if s:s.close()
            if l:l.close()
            v.close();raise
    calls=[];behavior={'handler':lambda r:httpx.Response(200,content=PDF)}
    def handle(req):calls.append(str(req.url));return behavior['handler'](req)
    supervisor=ArchiveSupervisor(binding,resources,lambda:query.controls,policy=policy,client_factory=lambda:httpx.Client(transport=httpx.MockTransport(handle)))
    previews=AnnouncementSourceRuntime(lambda wake:(query,query.fixture_preparation),query.policy).start()
    service=AnnouncementDownloadService(supervisor,supervisor.store,lambda:query.controls,lambda:query.presence.identity,previews.wake.set)
    settings=Settings(WEALTH_LOCAL_ANNOUNCEMENTS_ENABLED=True,APP_ENV='local')
    for module in ('home','announcements','downloads'):
        monkeypatch.setattr('src.biz.api.wealth.data_center.'+module+'.get_settings',lambda:settings)
    app=FastAPI();install_exception_handlers(app);install_data_center(app)
    router=APIRouter(prefix='/api/v1');include_data_center(router);app.include_router(router)
    app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(id=42)
    app.state.announcement_download=service
    with TestClient(app) as client:
        yield SimpleNamespace(client=client,service=service,supervisor=supervisor,previews=previews,catalog=query.controls,archive=a,binding=binding,calls=calls,behavior=behavior,settings=settings,app=app)
    supervisor.close();previews.close();query.presence.close()


def poll(d,url):
    for _ in range(500):
        response=d.client.get(url)
        assert response.status_code in {200,202},response.text
        body=response.json()
        preparing=body.get('state')=='preparing' or body.get('phase') in {'preparing','downloading','stopping'}
        checking=bool(body.get('check') and body['check']['state']=='checking')
        if not preparing and not checking:return body
        time.sleep(.01)
    raise AssertionError('task did not finish')


def preview(d,rows):
    with d.service.store.open() as old:
        records=[dict(r) for r in old.conn.execute("SELECT * FROM artifacts WHERE state='succeeded'").fetchmany(500)]
    if records:
        with d.catalog.transaction() as conn:
            for record in records:
                key=record['artifact_key']
                if not d.catalog.artifact_rows([key]):d.catalog.insert(conn,'artifacts',[record])
    write_day(raw_root(d.archive),'2026-09-30',rows)
    response=d.client.post(P+'/previews',json=dict(startDate='2026-09-30',endDate='2026-09-30',intervalSeconds=0))
    assert response.status_code==202,response.text
    return poll(d,P+'/previews/'+response.json()['previewId'])


def create(d,p,key=None):
    response=d.client.post(P+'/runs',json=dict(previewId=p['previewId']),headers={'Idempotency-Key':key or str(uuid.uuid4())})
    assert response.status_code==202,response.text
    return response.json()


def command(d,run,path,body=None,key=None):
    return d.client.post(P+'/runs/'+run+'/'+path,json=body or {},headers={'Idempotency-Key':key or str(uuid.uuid4())})


def test_preview_and_date_execution_records_vs_files(downloads):
    d=downloads;first=row();duplicate=dict(first,title='另一条公告',rec_time=None)
    p=preview(d,[first,duplicate,dict(row(2),url=None)])
    assert (p['recordCount'],p['artifactCount'],p['missingUrlCount'],p['downloadEstimate'])==(3,1,1,1)
    assert not d.calls
    run=create(d,p);final=poll(d,P+'/runs/'+run['runId'])
    assert final['phase']=='completed' and final['total']==1 and final['recordCount']==3
    assert final['succeeded']==final['processed']==1 and final['percent']==100 and final['missingUrlCount']==1
    files=d.client.get(P+'/runs/'+run['runId']+'/files').json()['items']
    assert len(files)==1 and files[0]['result']=='succeeded' and files[0]['attempts']==1
    assert len(d.calls)==1
    with d.service.store.open() as db:
        assert db.conn.execute('SELECT actor_id FROM runs WHERE run_id=?',(run['runId'],)).fetchone()[0]=='42'
    p2=preview(d,[first,duplicate,dict(row(2),url=None)])
    assert p2['reusableEstimate']==1 and p2['downloadEstimate']==0
    second=create(d,p2);done=poll(d,P+'/runs/'+second['runId'])
    assert done['reused']==1 and len(d.calls)==1


def test_preview_changed_and_expired_no_http_or_run(downloads):
    d=downloads;p=preview(d,[row()]);write_day(raw_root(d.archive),'2026-09-30',[row(),row(2)])
    response=d.client.post(P+'/runs',json={'previewId':p['previewId']},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert response.status_code==409 and response.json()['code']=='DC_PREVIEW_STALE'
    assert not d.calls and d.client.get(P+'/runs').json()['items']==[]
    fresh=preview(d,[row()])
    with d.catalog.transaction() as db:d.catalog.update(db,'preview',fresh['previewId'],dict(expires_at=0.))
    assert d.client.post(P+'/runs',json={'previewId':fresh['previewId']},headers={'Idempotency-Key':str(uuid.uuid4())}).status_code==409


def test_empty_preview_and_no_url_are_not_failed_downloads(downloads):
    d=downloads;p=preview(d,[dict(row(),url=None)])
    assert p['state']=='empty' and not p['canStart'] and p['missingUrlCount']==1
    assert d.client.post(P+'/runs',json={'previewId':p['previewId']},headers={'Idempotency-Key':str(uuid.uuid4())}).status_code==409
    assert not d.calls


def test_idempotency_same_key_and_conflicting_payload(downloads):
    d=downloads;p=preview(d,[row()]);key=str(uuid.uuid4())
    run=create(d,p,key);poll(d,P+'/runs/'+run['runId'])
    repeated=create(d,p,key)
    assert repeated['runId']==run['runId'] and len(d.calls)==1
    p2=preview(d,[row(2)])
    response=d.client.post(P+'/runs',json={'previewId':p2['previewId']},headers={'Idempotency-Key':key})
    assert response.status_code==409 and response.json()['code']=='DC_STATE_CONFLICT'
    assert len(d.client.get(P+'/runs').json()['items'])==1


def test_exact_all_failure_retry_preserves_original_and_ignores_new_raw(downloads):
    d=downloads;d.behavior['handler']=lambda r:httpx.Response(404) if r.url.path.endswith('/2.pdf') else httpx.Response(200,content=PDF)
    p=preview(d,[row(),row(2),dict(row(3),url=None)])
    initial=create(d,p);run=initial['runId'];done=poll(d,P+'/runs/'+run)
    assert (done['processed'],done['succeeded'],done['failed'],done['percent'])==(2,1,1,100)
    assert done['phase']=='partial_failed' and done['unresolvedFailureCount']==1
    write_day(raw_root(d.archive),'2026-09-30',[row(),row(2),row(99)])
    d.behavior['handler']=lambda r:httpx.Response(200,content=PDF)
    response=command(d,run,'retries',{'scope':'allFailed'})
    assert response.status_code==202,response.text
    retry=poll(d,P+'/runs/'+response.json()['runId'])
    assert retry['total']==1 and retry['recordCount']==3 and retry['missingUrlCount']==1
    assert retry['rootRunId']==run and retry['retryOfRunId']==run
    assert len(d.calls)==3 and not any('99.pdf' in url for url in d.calls)
    original=d.client.get(P+'/runs/'+run).json()
    assert original['failed']==1 and original['unresolvedFailureCount']==0 and not original['actions']['canRetryFailed']
    failed=d.client.get(P+'/runs/'+run+'/files?result=failed').json()['items'][0]
    assert failed['lastError']['httpStatus']==404 and not failed['canRetry']
    assert command(d,run,'retries',{'scope':'allFailed'}).status_code==409


def test_stop_continue_only_pending_and_no_automatic_resume(downloads):
    d=downloads;entered=threading.Event();release=threading.Event()
    def handle(req):entered.set();release.wait(3);return httpx.Response(200,content=PDF)
    d.behavior['handler']=handle;p=preview(d,[row(n) for n in range(1,4)])
    first=create(d,p);run=first['runId'];assert entered.wait(3)
    response=command(d,run,'stop');assert response.status_code==202 and response.json()['phase']=='stopping'
    release.set();done=poll(d,P+'/runs/'+run)
    assert done['phase']=='stopped' and done['processed']==0 and done['remaining']==3
    assert done['actions']['canContinue'] and len(d.calls)==1
    write_day(raw_root(d.archive),'2026-09-30',[row(n) for n in range(1,5)])
    d.behavior['handler']=lambda r:httpx.Response(200,content=PDF)
    response=command(d,run,'continue');assert response.status_code==202,response.text
    done=poll(d,P+'/runs/'+run)
    assert done['runId']==run and done['total']==done['processed']==3
    assert len(d.calls)==4 and not any('4.pdf' in x for x in d.calls)
    assert command(d,run,'stop').json()['phase']=='completed'


def test_remote_check_is_limited_and_never_continues(downloads):
    d=downloads;d.behavior['handler']=lambda r:httpx.Response(403)
    p=preview(d,[row(),row(2)]);run=create(d,p)['runId'];done=poll(d,P+'/runs/'+run)
    assert done['phase']=='blocked' and done['blockedReason']['code']=='DC_REMOTE_BLOCKED'
    d.behavior['handler']=lambda r:httpx.Response(200,content=PDF)
    response=command(d,run,'recheck',{'kind':'remoteSource'});assert response.status_code==202,response.text
    checked=poll(d,P+'/runs/'+run)
    assert checked['phase']=='blocked' and checked['check']['state']=='passed' and checked['processed']==0
    assert len(d.calls)==2
    assert command(d,run,'recheck',{'kind':'volume'}).status_code==202
    checked=poll(d,P+'/runs/'+run);assert checked['phase']=='blocked' and len(d.calls)==2


@pytest.mark.parametrize('body',[{}, {'startDate':'20260930','endDate':'2026-09-30'}, {'startDate':'2026-10-01','endDate':'2026-09-30'}, {'startDate':'2026-09-30','endDate':'2026-09-30','intervalSeconds':-1}, {'startDate':'2026-09-30','endDate':'2026-09-30','intervalSeconds':True}, {'startDate':'2026-09-30','endDate':'2026-09-30','tsCode':'600000.SH'}, {'startDate':'2026-09-30','endDate':'2026-09-30','outputRoot':'/tmp'}])
def test_public_download_contract_rejects_invalid_and_extra(downloads,body):
    d=downloads;assert d.client.post(P+'/previews',json=body).status_code==422
    assert not d.calls


def test_auth_prod_and_unknown_objects(downloads):
    d=downloads
    def unauthorized():raise WebAppError(status_code=401,code='unauthorized',message='请先登录')
    d.app.dependency_overrides[get_current_user]=unauthorized
    assert d.client.get(P+'/runs').status_code==401
    d.app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(id=1)
    d.settings.app_env='prod'
    assert d.client.get(P+'/runs').status_code==404
    d.settings.app_env='local'
    assert d.client.get(P+'/runs/'+str(uuid.uuid4())).status_code==404
    assert d.client.post(P+'/runs',json={'previewId':str(uuid.uuid4())}).status_code==422
    assert d.client.get(P+'/runs?limit=21').status_code==422
    assert d.client.get(P+'/runs?limit=1&limit=2').status_code==422


def test_deleted_success_new_date_run_restores_it(downloads):
    d=downloads;p=preview(d,[row()]);run=create(d,p)['runId'];poll(d,P+'/runs/'+run)
    with d.service.store.open() as db:task=dict(db.conn.execute('SELECT * FROM artifacts').fetchone())
    (d.binding.output/task['relative_path']).unlink()
    p=preview(d,[row()]);assert p['reusableEstimate']==0
    new=create(d,p)['runId'];done=poll(d,P+'/runs/'+new)
    assert done['succeeded']==1 and len(d.calls)==2


def test_single_failure_retry_and_per_batch_attempts(downloads):
    d=downloads;d.behavior['handler']=lambda r:httpx.Response(404)
    p=preview(d,[row(),row(2)]);run=create(d,p)['runId'];poll(d,P+'/runs/'+run)
    files=d.client.get(P+'/runs/'+run+'/files?result=failed').json()['items'];key=files[0]['artifactKey']
    d.behavior['handler']=lambda r:httpx.Response(200,content=PDF)
    retry=command(d,run,'retries',{'scope':'singleFailed','artifactKey':key})
    assert retry.status_code==202,retry.text
    final=poll(d,P+'/runs/'+retry.json()['runId'])
    assert final['total']==1 and final['succeeded']==1
    items=d.client.get(P+'/runs/'+final['runId']+'/files').json()['items']
    assert items[0]['attempts']==1 and len(d.calls)==3
    assert d.client.get(P+'/runs/'+run).json()['unresolvedFailureCount']==1
    assert command(d,run,'retries',{'scope':'singleFailed','artifactKey':key}).status_code==409


def test_validation_failure_reason_survives_later_artifact_changes(downloads):
    d=downloads;p=preview(d,[row(title='')]);run=create(d,p)['runId'];done=poll(d,P+'/runs/'+run)
    assert done['failed']==1 and not d.calls
    with d.service.store.open(write=True) as db:db.conn.execute("UPDATE artifacts SET error=NULL,state='succeeded'")
    item=d.client.get(P+'/runs/'+run+'/files').json()['items'][0]
    assert item['lastError']['code']=='DC_FILE_FAILED' and item['attempts']==0


def test_busy_cli_lock_and_history_remain_available_offline(downloads):
    from src.foundation.clients.announcement_archive.locking import ExecutionLock
    d=downloads;p=preview(d,[row()])
    held=ExecutionLock(d.binding.ledger_path().parent/'execution.lock').open()
    try:
        response=d.client.post(P+'/runs',json={'previewId':p['previewId']},headers={'Idempotency-Key':str(uuid.uuid4())})
        assert response.status_code==409 and response.json()['code']=='DC_ARCHIVE_BUSY'
    finally:held.close()
    run=create(d,p)['runId'];poll(d,P+'/runs/'+run)
    d.archive[6]['VolumeUUID']='changed-volume'
    assert d.client.get(P+'/runs').status_code==200
    assert d.client.get(P+'/runs/'+run).json()['phase']=='completed'
    assert not d.supervisor.store.receipt(str(uuid.uuid4()),'create',{'previewId':p['previewId']})


def test_cancel_preview_during_source_preparation_no_http(downloads,monkeypatch):
    d=downloads;entered=threading.Event();release=threading.Event();source=d.previews.service().source
    original=source.preview_keys
    def keys(*args):
        values=original(*args);entered.set();release.wait(3);return values
    monkeypatch.setattr(source,'preview_keys',keys)
    write_day(raw_root(d.archive),'2026-09-30',[row(n) for n in range(1,1100)])
    response=d.client.post(P+'/previews',json=dict(startDate='2026-09-30',endDate='2026-09-30',intervalSeconds=0))
    assert entered.wait(3)
    stopped=d.client.post(P+'/previews/'+response.json()['previewId']+'/stop',json={})
    assert stopped.status_code==200 and stopped.json()['state']=='cancelled'
    release.set();time.sleep(.05)
    assert not d.calls and d.catalog.preview_day(response.json()['previewId'],'2026-09-30') is None


def subprocess_run(d,mode,preview_id=None,run_id=None,key=None):
    import subprocess,sys,os
    path=d.binding.path.parent/'subprocess-config.json';calls=d.binding.path.parent/'process-calls.txt'
    config=dict(mount=str(d.archive[0].mount.resolve()),binding=str(d.binding.path),ledger=str(d.binding.ledger_path()),raw=str(raw_root(d.archive)),pg_url=d.catalog.database.engine.url.render_as_string(hide_password=False),pg_policy=dict(database=d.catalog.database.policy.database,port=d.catalog.database.policy.port),archive_id=d.catalog.archive_id,scope=d.catalog.scope,calls=str(calls),preview=preview_id,run=run_id,key=key or str(uuid.uuid4()))
    path.write_text(json.dumps(config))
    result=subprocess.run([sys.executable,'-B','tests/fixtures/announcement_web_process_runner.py',str(path),mode],env=dict(os.environ,PYTHONPATH=str(Path.cwd())),capture_output=True,text=True,timeout=30)
    return result,calls,config


@pytest.mark.parametrize('mode',['preparing','prepared','renamed','downloading','receipt'])
def test_process_exit_recovery_and_exact_continue(downloads,mode):
    d=downloads;p=preview(d,[row(),row(2)] if mode in {'preparing','downloading','receipt'} else [row()])
    key=str(uuid.uuid4());result,calls,_=subprocess_run(d,mode,p['previewId'],key=key)
    assert result.returncode==73,(result.stdout,result.stderr)
    with d.service.store.open() as db:original=dict(db.conn.execute('SELECT * FROM runs ORDER BY rowid DESC LIMIT 1').fetchone())
    before=len(calls.read_text().splitlines()) if calls.exists() else 0
    result,_,_=subprocess_run(d,'recover');assert result.returncode==0,result.stderr
    task=d.client.get(P+'/runs/'+original['run_id']).json()
    assert task['phase']=='interrupted'
    assert (len(calls.read_text().splitlines()) if calls.exists() else 0)==before
    with d.service.store.open() as db:
        assert db.conn.execute('SELECT active_run_id FROM archive_execution').fetchone()[0] is None
        assert not db.conn.execute('SELECT 1 FROM attempt_log WHERE ended_at IS NULL').fetchone()
    if mode in {'preparing','receipt'}:
        assert not task['actions']['canContinue'] and before==0
        replay=create(d,p,key);assert replay['runId']==original['run_id'] and not d.calls
    else:
        assert task['actions']['canContinue']
        write_day(raw_root(d.archive),'2026-09-30',[row(),row(2),row(99)])
        response=command(d,original['run_id'],'continue');assert response.status_code==202,response.text
        done=poll(d,P+'/runs/'+original['run_id'])
        assert done['phase']=='completed' and done['processed']==original['artifacts_total']
        assert not any('/99.pdf' in url for url in d.calls)
        assert len(d.calls)==(1 if mode=='downloading' else 0)


def test_legacy_catalog_schema_is_not_upgraded_by_runtime(tmp_path):
    from src.foundation.dao.announcement_archive.catalog import SCHEMA_V1
    from src.foundation.clients.announcement_archive.migration_source import LegacyCatalog
    path=tmp_path/'v1.sqlite'
    with sqlite3.connect(path) as db:
        for sql in SCHEMA_V1:db.execute(sql)
        db.execute("INSERT INTO catalog_meta(singleton,schema_version,source_scope,revision) VALUES(1,1,'scope',8)")
    with pytest.raises(Blocked,match='catalog_schema_invalid'):LegacyCatalog(path,Control(DownloadPolicy(),emit=lambda _:None)).open()
    with sqlite3.connect(path) as db:assert db.execute('SELECT schema_version FROM catalog_meta').fetchone()[0]==1


def test_original_failed_keys_ten_are_the_retry_denominator(downloads):
    d=downloads;d.behavior['handler']=lambda r:httpx.Response(404)
    p=preview(d,[row(n) for n in range(10)]);run=create(d,p)['runId'];done=poll(d,P+'/runs/'+run)
    assert done['total']==done['failed']==10
    d.behavior['handler']=lambda r:httpx.Response(200,content=PDF)
    response=command(d,run,'retries',{'scope':'allFailed'});assert response.status_code==202,response.text
    final=poll(d,P+'/runs/'+response.json()['runId'])
    assert final['total']==final['succeeded']==10 and final['percent']==100
    related=d.client.get(P+'/runs/'+run+'/related?limit=1').json()
    assert len(related['items'])==1 and related['nextCursor'] is not None
    other=d.client.get(P+'/runs/'+run+'/related',params={'limit':1,'cursor':related['nextCursor']}).json()
    assert other['items'][0]['runId']==run


def test_promoted_pdf_survives_result_write_failure_and_recovers_without_http(downloads,monkeypatch):
    d=downloads;p=preview(d,[row()]);original=Ledger.result
    def fail(self,*_):raise sqlite3.OperationalError('injected observer failure')
    monkeypatch.setattr(Ledger,'result',fail)
    run=create(d,p)['runId'];done=poll(d,P+'/runs/'+run)
    assert done['phase']=='blocked' and done['processed']==0 and len(d.calls)==1
    with d.service.store.open() as db:
        task=dict(db.conn.execute('SELECT * FROM artifacts').fetchone())
        assert task['state']=='succeeded' and (d.binding.output/task['relative_path']).read_bytes()==PDF
    monkeypatch.setattr(Ledger,'result',original)
    response=command(d,run,'continue');assert response.status_code==202,response.text
    final=poll(d,P+'/runs/'+run)
    assert final['phase']=='completed' and final['succeeded']==final['processed']==1 and len(d.calls)==1


def test_real_http_redirect_interval_and_zero_request_replay(downloads):
    from test_announcement_download_cli import local_http_fixture
    d=downloads
    def handler(path,number):
        if path=='/start.pdf':return 302,{'Location':'/final.pdf','Content-Length':'0'},b''
        return 200,{'Content-Type':'application/pdf','Content-Length':str(len(PDF))},PDF
    with local_http_fixture(handler) as (base,requests):
        d.supervisor.client_factory=lambda:httpx.Client(trust_env=False,follow_redirects=False)
        write_day(raw_root(d.archive),'2026-09-30',[row(url=base+'/start.pdf')])
        response=d.client.post(P+'/previews',json=dict(startDate='2026-09-30',endDate='2026-09-30',intervalSeconds=.05))
        p=poll(d,P+'/previews/'+response.json()['previewId']);assert not requests
        run=create(d,p)['runId'];done=poll(d,P+'/runs/'+run)
        assert done['phase']=='completed' and len(requests)==2
        assert requests[1]['started']-requests[0]['finished']>=.045
        response=d.client.post(P+'/previews',json=dict(startDate='2026-09-30',endDate='2026-09-30',intervalSeconds=.05))
        p=poll(d,P+'/previews/'+response.json()['previewId'])
        run=create(d,p)['runId'];done=poll(d,P+'/runs/'+run)
        assert done['reused']==1 and len(requests)==2


def test_recheck_cancel_during_cooldown_does_not_clear_it_or_send_http(downloads):
    d=downloads;d.behavior['handler']=lambda r:httpx.Response(403)
    p=preview(d,[row()]);run=create(d,p)['runId'];poll(d,P+'/runs/'+run)
    with d.service.store.open(write=True) as db:db.defer(time.time()+100,'http_429')
    response=command(d,run,'recheck',{'kind':'remoteSource'});assert response.status_code==202,response.text
    for _ in range(100):
        current=d.client.get(P+'/runs/'+run).json()
        if current['wait']:break
        time.sleep(.01)
    assert current['wait']['kind']=='cooldown' and current['check']['state']=='checking'
    assert command(d,run,'stop').status_code==202
    checked=poll(d,P+'/runs/'+run)
    assert checked['phase']=='blocked' and checked['check']['state']=='cancelled' and len(d.calls)==1
    with d.service.store.open() as db:assert db.cooldown()['next_request_not_before']>time.time()+90


def test_byte_progress_unknown_length_and_business_time(downloads):
    d=downloads;release=threading.Event();entered=threading.Event()
    d.supervisor.policy=replace(d.supervisor.policy,chunk_size=8,progress_seconds=.03)
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield PDF[:8];time.sleep(.04);yield PDF[8:16];entered.set();release.wait(3);yield PDF[16:]
    d.behavior['handler']=lambda r:httpx.Response(200,stream=Stream())
    p=preview(d,[row()]);run=create(d,p)['runId'];assert entered.wait(3)
    current=d.client.get(P+'/runs/'+run).json()
    assert current['current']['bytesReceived']==16 and current['current']['bytesTotal'] is None
    assert current['current']['attemptNumber']==1 and current['processed']==0
    assert current['businessUpdatedAt'] and current['heartbeatAt'] and current['etaSeconds'] is None
    release.set();done=poll(d,P+'/runs/'+run)
    assert done['phase']=='completed' and done['processed']==1


def test_history_and_files_are_bounded_and_old_schema_not_migrated(downloads):
    from test_announcement_download_dg import seed_v1
    d=downloads;path=d.binding.path.parent/'old.sqlite';seed_v1(path,d.archive)
    previous=d.binding.ledger_path;d.binding.ledger_path=lambda value=None:path
    before=path.read_bytes()
    try:
        assert d.client.get(P+'/runs').status_code==200
        with sqlite3.connect(path) as db:run=db.execute('SELECT run_id FROM runs').fetchone()[0]
        # Old sample IDs need not be UUIDs; observed listing remains available and recovery is not exposed.
        assert path.read_bytes()==before
    finally:d.binding.ledger_path=previous


@pytest.mark.parametrize('version',[1,2])
def test_upgraded_legacy_blocked_run_has_no_recheck_action(downloads,version):
    from test_announcement_download_dg import seed_v1
    from test_announcement_archive_runtime import seed_v2
    d=downloads;path=d.binding.path.parent/'upgraded-legacy.sqlite'
    (seed_v1 if version==1 else seed_v2)(path,d.archive)
    run=uuid.uuid4().hex
    with sqlite3.connect(path) as db:
        db.execute("UPDATE runs SET run_id=?,phase='blocked'",(run,))
        db.execute('UPDATE run_artifacts SET run_id=?',(run,))
        db.execute('UPDATE source_records SET first_seen_run=?,last_seen_run=?',(run,run))
    Ledger(path,d.archive[0].volume_uuid,d.archive[0].relative_root).close()
    previous=d.binding.ledger_path;d.binding.ledger_path=lambda value=None:path
    before=path.read_bytes()
    try:
        response=d.client.get(P+'/runs/'+run)
        assert response.status_code==200,response.text
        actions=response.json()['actions']
        assert not actions['canContinue'] and not actions['canRetryFailed']
        assert not actions['canRecheck']
        assert actions['reason']=='历史任务不支持精确恢复，可新建日期下载'
        assert path.read_bytes()==before and not d.calls
    finally:d.binding.ledger_path=previous


def test_binding_invalid_does_not_create_ledger(downloads):
    d=downloads;d.binding.path.write_text(json.dumps({'version':1,'archiveLocation':'/tmp'}))
    response=d.client.get(P+'/runs')
    assert response.status_code==503 and response.json()['code']=='DC_LEDGER_FAILED'
    assert not d.calls


def test_stop_during_enumeration_keeps_committed_rows_but_never_downloads(downloads,monkeypatch):
    d=downloads;p=preview(d,[row(n) for n in range(501)])
    entered=threading.Event();release=threading.Event();original=Ledger.ingest
    def ingest(self,*args):
        result=original(self,*args);entered.set();release.wait(3);return result
    monkeypatch.setattr(Ledger,'ingest',ingest)
    run=create(d,p)['runId'];assert entered.wait(3)
    assert command(d,run,'stop').status_code==202
    release.set();done=poll(d,P+'/runs/'+run)
    assert done['phase']=='cancelled' and done['recordCount']==500 and done['total'] is None
    assert not done['actions']['canContinue'] and not d.calls
    assert command(d,run,'continue').status_code==409


def test_source_changes_during_enumeration_block_before_any_http(downloads,monkeypatch):
    d=downloads;p=preview(d,[row()]);original=Ledger.ingest
    def ingest(self,*args):
        result=original(self,*args)
        write_day(raw_root(d.archive),'2026-09-30',[row(),row(99)])
        return result
    monkeypatch.setattr(Ledger,'ingest',ingest)
    run=create(d,p)['runId'];done=poll(d,P+'/runs/'+run)
    assert done['phase']=='blocked' and done['total'] is None and not d.calls
    assert not done['actions']['canContinue']


def test_active_receipt_replays_but_other_command_is_rejected(downloads):
    d=downloads;entered=threading.Event();release=threading.Event()
    def handler(req):entered.set();release.wait(3);return httpx.Response(200,content=PDF)
    d.behavior['handler']=handler;p=preview(d,[row()]);key=str(uuid.uuid4())
    run=create(d,p,key)['runId'];assert entered.wait(3)
    try:
        assert create(d,p,key)['runId']==run
        response=d.client.post(P+'/runs',json={'previewId':p['previewId']},headers={'Idempotency-Key':str(uuid.uuid4())})
        assert response.status_code==409 and response.json()['code']=='DC_ARCHIVE_BUSY'
        assert len(d.calls)==1
    finally:release.set()
    assert poll(d,P+'/runs/'+run)['phase']=='completed'


def test_volume_recheck_does_not_require_raw_to_be_available(downloads):
    d=downloads;d.behavior['handler']=lambda r:httpx.Response(403)
    p=preview(d,[row()]);run=create(d,p)['runId'];poll(d,P+'/runs/'+run)
    root=raw_root(d.archive);offline=root.with_name(root.name+'-offline');root.rename(offline)
    try:
        response=command(d,run,'recheck',{'kind':'volume'});assert response.status_code==202,response.text
        checked=poll(d,P+'/runs/'+run)
        assert checked['check']['state']=='passed' and len(d.calls)==1
    finally:offline.rename(root)


@pytest.mark.parametrize('number',['NaN','Infinity','-Infinity'])
def test_non_finite_intervals_are_rejected(downloads,number):
    response=downloads.client.post(P+'/previews',content='{"startDate":"2026-09-30","endDate":"2026-09-30","intervalSeconds":'+number+'}',headers={'Content-Type':'application/json'})
    assert response.status_code==422 and not downloads.calls


def test_preview_large_day_fifty_thousand_unique_files(downloads):
    d=downloads;write_day(raw_root(d.archive),'2026-09-30',[row(n) for n in range(50000)])
    response=d.client.post(P+'/previews',json=dict(startDate='2026-09-30',endDate='2026-09-30',intervalSeconds=0))
    assert response.status_code==202,response.text
    for _ in range(3000):
        value=d.client.get(P+'/previews/'+response.json()['previewId']).json()
        if value['state']!='preparing':break
        time.sleep(.01)
    assert value['state']=='ready',value
    assert value['recordCount']==value['artifactCount']==value['downloadEstimate']==50000
    assert value['preparation']['recordsScanned']==50000 and not d.calls


def test_preview_intent_is_one_atomic_pg_control_row(downloads,monkeypatch):
    d=downloads;pid=uuid.uuid4().hex;original=d.catalog.insert
    def fail(conn,*args,**kwargs):
        original(conn,*args,**kwargs);raise Blocked('fixture_after_insert')
    monkeypatch.setattr(d.catalog,'insert',fail)
    with pytest.raises(Blocked):d.catalog.create_preview(pid,'2026-09-30','2026-09-30',0,d.catalog.archive_id)
    assert d.catalog.query(pid) is None and d.catalog.preview(pid) is None
    monkeypatch.setattr(d.catalog,'insert',original)
    d.catalog.create_preview(pid,'2026-09-30','2026-09-30',0,d.catalog.archive_id)
    assert d.catalog.preview(pid)['state']=='preparing' and d.catalog.query(pid) is None
    d.catalog.cancel_preview(pid)


@pytest.mark.parametrize('initial_reason',['http_403','challenge_page'])
def test_remote_block_requires_passed_remote_check_before_continue(downloads,initial_reason):
    d=downloads
    d.behavior['handler']=lambda r:httpx.Response(403) if initial_reason=='http_403' else httpx.Response(200,headers={'Content-Type':'text/html'},content=b'captcha')
    p=preview(d,[row()]);run=create(d,p)['runId'];done=poll(d,P+'/runs/'+run)
    assert done['phase']=='blocked' and not done['actions']['canContinue']
    assert command(d,run,'continue').status_code==409 and len(d.calls)==1
    assert command(d,run,'recheck',{'kind':'volume'}).status_code==202
    done=poll(d,P+'/runs/'+run)
    assert done['check']['state']=='passed' and not done['actions']['canContinue']
    assert command(d,run,'continue').status_code==409 and len(d.calls)==1
    assert command(d,run,'recheck',{'kind':'remoteSource'}).status_code==202
    done=poll(d,P+'/runs/'+run)
    assert done['check']['state']=='blocked' and not done['actions']['canContinue']
    assert command(d,run,'continue').status_code==409 and len(d.calls)==2
    d.behavior['handler']=lambda r:httpx.Response(200,content=PDF)
    assert command(d,run,'recheck',{'kind':'remoteSource'}).status_code==202
    done=poll(d,P+'/runs/'+run)
    assert done['check']['state']=='passed' and done['actions']['canContinue'] and done['processed']==0
    assert len(d.calls)==3
    d.behavior['handler']=lambda r:httpx.Response(403)
    assert command(d,run,'continue').status_code==202
    done=poll(d,P+'/runs/'+run)
    assert done['phase']=='blocked' and done['check'] is None and not done['actions']['canContinue']
    assert command(d,run,'continue').status_code==409 and len(d.calls)==4
    d.behavior['handler']=lambda r:httpx.Response(200,content=PDF)
    assert command(d,run,'recheck',{'kind':'remoteSource'}).status_code==202
    assert poll(d,P+'/runs/'+run)['actions']['canContinue']
    assert command(d,run,'continue').status_code==202
    done=poll(d,P+'/runs/'+run)
    assert done['phase']=='completed' and done['succeeded']==1 and len(d.calls)==6


def test_failure_resolution_uses_indexed_family_keys_at_scale(downloads):
    from src.foundation.dao.announcement_archive.execution import unresolved_sql
    from src.foundation.clients.announcement_archive.budget import read_budget
    d=downloads;root=uuid.uuid4().hex;child=uuid.uuid4().hex;other=uuid.uuid4().hex
    with d.service.store.open(write=True) as ledger:
        # All capacity facts are local test rows; no PDF/Raw or formal dataset writes.
        for run,parent in [(root,None),(child,root),(other,None)]:
            ledger.conn.execute("INSERT INTO runs(run_id,parent_run_id,phase,updated_at,source_scope) VALUES(?,?,'completed','test','test')",(run,parent))
        ledger.conn.executemany('INSERT INTO run_artifacts(run_id,artifact_key,outcome) VALUES(?,?,?)',((root,f'{n:064x}','failed') for n in range(50000)))
        ledger.conn.executemany('INSERT INTO run_artifacts(run_id,artifact_key,outcome) VALUES(?,?,?)',((child,f'{n:064x}','succeeded') for n in range(10000)))
        ledger.conn.executemany('INSERT INTO run_artifacts(run_id,artifact_key,outcome) VALUES(?,?,?)',((other,f'{n:064x}','succeeded') for n in range(50000)))
    query='SELECT COUNT(*) FROM run_artifacts r WHERE r.run_id=:run AND '+unresolved_sql()
    with read_budget(4),d.service.store.open() as ledger:
        plan=[row[3] for row in ledger.conn.execute('EXPLAIN QUERY PLAN '+query,dict(run=root,root=root))]
        assert not any('SCAN fixed' in detail for detail in plan)
        assert ledger.conn.execute(query,dict(run=root,root=root)).fetchone()[0]==40000
    assert not d.calls
