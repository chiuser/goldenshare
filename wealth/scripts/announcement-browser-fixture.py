"""DC4 bounded, disposable real API browser acceptance. No formal resources/network PDFs.

Uses the existing tested temporary Parquet/SQLite fixtures, actual Biz routes/query,
preview worker and download supervisor. Only auth, external-volume inspection,
market-shell decorations and the remote PDF transport are isolated test inputs.
Requires an already installed Playwright/Chromium. Never installs dependencies.
"""
from pathlib import Path
from contextlib import ExitStack
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import collections
import json
import socket
import subprocess
import sys
import threading
import time
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'tests/web')]
import httpx
import pytest
import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from test_announcement_download_cli import archive,PDF
from test_announcement_catalog import query_archive,row
from test_announcement_download_dg import write_day,raw_root
from test_wealth_data_center_downloads import downloads
from src.app.runtime.announcement_archive_lifespan import AnnouncementCatalogRuntime
from src.foundation.clients.announcement_archive.core import Blocked
from src.foundation.dao.announcement_archive.ledger import Ledger,timestamp


def enter_fixture(stack,fn,*args):
    generator=fn.__wrapped__(*args)
    value=next(generator)
    stack.callback(lambda:next(generator,None))
    return value


def main(output,playwright):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    assert output.is_relative_to(Path('/private/tmp')),output
    assert Path(playwright).is_file(), 'Use existing Playwright; installation is not authorized'
    assert (ROOT/'wealth/dist/index.html').is_file(),'Build Wealth first'
    with tempfile.TemporaryDirectory(prefix='dc4-',dir='/private/tmp') as temp,ExitStack() as stack:
        tmp=Path(temp);mp=pytest.MonkeyPatch();stack.callback(mp.undo)
        a=enter_fixture(stack,archive,tmp,mp)
        query=enter_fixture(stack,query_archive,a,tmp)
        d=enter_fixture(stack,downloads,query,tmp,mp)
        today=datetime.now(ZoneInfo('Asia/Shanghai')).date()
        for offset in range(30):
            day=today-timedelta(days=offset)
            rows=[]
            if day.isoformat()=='2026-09-30':
                rows=[row(i,title=('董事会决议公告' if i%2 else '关于召开股东大会的通知')+f'（样本 {i}）',code='000001.SZ' if i%3 else '600036.SH',day=day) for i in range(1,65)]
                rows += [dict(rows[0],title='另一条元数据，归档同一文件',rec_time=None),dict(row(99,day=day),url=None,rec_time=None),dict(row(100,day=day),url='',name=None)]
            write_day(raw_root(a),day.isoformat(),rows)
        runtime=AnnouncementCatalogRuntime(factory=lambda wake,control:query[0])
        query[0].wake=runtime.wake.set
        d.app.state.announcement_catalog=runtime.start();stack.callback(runtime.close)
        calls=collections.Counter();environment={'unplug':False,'source':False}
        original_check=query[0].presence.check
        def presence(keys):
            if environment['unplug']:raise Blocked('archive_presence_unavailable')
            return original_check(keys)
        mp.setattr(query[0].presence,'check',presence)
        original_source=query[0].builder.assert_source
        def assert_source(full=False):
            if environment['source']:raise Blocked('source_unavailable')
            return original_source(full=full)
        mp.setattr(query[0].builder,'assert_source',assert_source)
        def remote(req):
            calls[str(req.url)]+=1
            time.sleep(.12)
            if req.url.path in {'/1.pdf','/2.pdf'} and calls[str(req.url)]==1:return httpx.Response(404)
            return httpx.Response(200,content=PDF)
        d.behavior['handler']=remote
        requests=[]
        async def audit(req:Request,call_next):
            body=await req.body() if req.method=='POST' else b''
            response=await call_next(req)
            if req.url.path.startswith('/api/v1/wealth/data-center'):
                requests.append(dict(path=req.url.path,query=req.url.query,method=req.method,status=response.status_code,body=json.loads(body) if body else None))
            return response
        @d.app.get('/test-fixture')
        def identity():return dict(kind='announcements-isolated-real-api',temporaryRoot=str(tmp),calls=dict(calls),requests=requests)
        @d.app.post('/test-environment/{mode}')
        def mode(mode:str):
            if mode=='prod':d.settings.app_env='prod'
            elif mode=='local':d.settings.app_env='local'
            elif mode=='unplug':environment['unplug']=True
            elif mode=='plug':environment['unplug']=False
            elif mode=='source-error':environment['source']=True
            return dict(mode=mode)
        @d.app.post('/test-visual-state/{kind}')
        def visual_state(kind:str):
            # Durable synthetic Ledger facts for rare visual states; never an execution acceptance.
            assert kind in {'preparing','stopping','interrupted','volume-blocked','remote-blocked','retry','single-retry'}
            ledger=Ledger(d.binding.ledger_path(),a[0].volume_uuid,a[0].relative_root)
            try:
                total=1 if kind=='single-retry' else 10 if kind=='retry' else 1000
                run=ledger.begin_run(a[2],f'dc4-visual/{kind}',a[3],details={'batch_kind':'retry' if 'retry' in kind else 'date'})
                values=[row(i,title=f'关于部分限制性股票回购注销完成的公告（{i}）',code='000333.SZ',url=f'https://visual.example/{kind}/{i}.pdf') for i in range(total)]
                facts=dict(opened_dev=1,opened_ino=1,size=0,sha256='0'*64,footer_count=len(values))
                ledger.begin_day(run,'2026-09-30');ledger.describe_day(run,'2026-09-30',facts)
                for offset in range(0,len(values),500):ledger.ingest(run,f'dc4-visual/{kind}','2026-09-30',values[offset:offset+500])
                if kind!='preparing':ledger.complete_day(run,'2026-09-30',facts);ledger.seal(run)
                if kind!='preparing':
                    keys=[r[0] for r in ledger.conn.execute('SELECT artifact_key FROM run_artifacts WHERE run_id=? ORDER BY artifact_key',(run,))]
                    successes=0 if total==1 else 3 if total==10 else 300
                    for key in keys[:successes]:ledger.result(run,key,'succeeded')
                    if total==1000:
                        for key in keys[300:310]:ledger.result(run,key,'skipped')
                        for key in keys[310:320]:ledger.file_failure(run,key,'http_404');ledger.result(run,key,'failed')
                    if kind in {'volume-blocked','remote-blocked','interrupted'}:
                        ledger.phase(run,'interrupted' if kind=='interrupted' else 'blocked','volume_unavailable' if kind=='volume-blocked' else 'http_403' if kind=='remote-blocked' else 'process_exit_recovered')
                    elif kind=='stopping':ledger.phase(run,'stopping')
                    else:
                        current=keys[min(successes,len(keys)-1)]
                        ledger.conn.execute('UPDATE runs SET current_artifact_key=?,attempt_number=2,bytes_received=?,bytes_total=?,wait_kind=?,next_request_at=? WHERE run_id=?',(current,3200000,5800000,'backoff',time.time()+8,run));ledger.conn.commit()
                return dict(runId=run,kind=kind,evidence='synthetic-ledger-visual-only')
            finally:ledger.close()
        @d.app.get('/api/v1/wealth/market/context')
        def market():return dict(pageContext=dict(market='CN_A',tradeDate=today.isoformat(),isTradingDay=True,sessionStatus='CLOSED',timezone='Asia/Shanghai',generatedAt=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),source='default'))
        @d.app.get('/api/v1/wealth/market/major-indices')
        def tickers():return dict(pageStatus=dict(displayText='隔离行情样本',status='READY'),majorIndices=dict(rows=[]))
        d.app.mount('/wealth/assets',StaticFiles(directory=ROOT/'wealth/dist/assets'))
        @d.app.get('/wealth/{path:path}')
        def frontend(path:str):return FileResponse(ROOT/'wealth/dist/index.html')
        sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128);port=sock.getsockname()[1]
        from starlette.middleware.base import BaseHTTPMiddleware
        server=uvicorn.Server(uvicorn.Config(BaseHTTPMiddleware(d.app,dispatch=audit),log_level='error',lifespan='off'))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
        try:
            deadline=time.monotonic()+5
            while not server.started and time.monotonic()<deadline:time.sleep(.02)
            assert server.started
            result=subprocess.run(['node',str(ROOT/'wealth/scripts/announcement-browser-smoke.mjs'),f'http://127.0.0.1:{port}',str(output),playwright],timeout=180)
            evidence=dict(kind='real-routes-services-temporary-storage',requests=requests,pdfTransportCalls=dict(calls),formalWrites=0,sourceSiteRequests=0)
            (output/'api-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
            assert result.returncode==0,result.returncode
        finally:
            server.should_exit=True;thread.join(timeout=5);sock.close()

if __name__=='__main__':main(*sys.argv[1:])
