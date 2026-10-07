"""Explicit browser fixture. Serves built Wealth + actual Q2 routes on disposable PG."""
import json
import os
from pathlib import Path
import socket
import threading
import time
from types import SimpleNamespace
import pytest
from fastapi import FastAPI,APIRouter,Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from test_announcement_direct_query import direct,pg,pg_cluster,write_day,row
from src.foundation.config.settings import Settings
from src.app.runtime.announcement_archive_lifespan import include_data_center,install_data_center
from src.app.auth.dependencies import get_current_user
from src.ops.runtime.announcement_archive.source_runtime import AnnouncementSourceRuntime

@pytest.mark.skipif(os.environ.get('ANNOUNCEMENT_Q2_BROWSER')!='1',reason='explicit supervised browser acceptance only')
def test_browser_fixture(direct,monkeypatch,tmp_path):
    service,preparation,downloads,raw,*_=direct
    write_day(raw,'2026-09-30',[dict(row(f'公告{i}'),url=f'https://ann.example/{i}.pdf') for i in range(65)])
    settings=Settings(APP_ENV='local',WEALTH_LOCAL_ANNOUNCEMENTS_ENABLED=True)
    for module in ('home','announcements','downloads'):monkeypatch.setattr('src.biz.api.wealth.data_center.'+module+'.get_settings',lambda:settings)
    context=service.context
    def local_context():
        value=context();value['queryDefaults'].update(startDate='2026-09-30',endDate='2026-09-30');return value
    monkeypatch.setattr(service,'context',local_context)
    app=FastAPI();install_data_center(app);router=APIRouter(prefix='/api/v1');include_data_center(router);app.include_router(router)
    app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(id=1)
    runtime=AnnouncementSourceRuntime(lambda wake:(service,preparation),service.policy).start()
    service.wake=runtime.wake.set;downloads.wake_preview=runtime.wake.set
    app.state.announcement_source=runtime;app.state.announcement_download=downloads
    requests=[]
    @app.middleware('http')
    async def evidence(request,call_next):
        start=time.monotonic();result=await call_next(request)
        if request.url.path.startswith('/api/'):
            requests.append(dict(method=request.method,path=request.url.path,query=request.url.query,status=result.status_code,seconds=time.monotonic()-start))
        return result
    @app.post('/api/v1/auth/login')
    def login():return dict(token='q2-fixture',refresh_token=None,username='fixture',display_name='Q2验收',access_token_expires_at=None)
    @app.get('/api/v1/auth/me')
    def me():return dict(id=1,username='fixture',is_active=True,display_name='Q2验收')
    @app.post('/_fixture/restore')
    def restore():
        write_day(raw,'2026-10-01',[]);return dict(ok=True)
    app.mount('/wealth/assets',StaticFiles(directory='wealth/dist/assets'))
    @app.get('/wealth/{path:path}')
    def page(path):return FileResponse('wealth/dist/index.html')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    evidence_dir=Path('reports/wealth_data_center_q2_browser_20261007');evidence_dir.mkdir(exist_ok=True)
    stop=tmp_path/'done'
    (evidence_dir/'fixture.json').write_text(json.dumps(dict(url=f'http://127.0.0.1:{port}/wealth/data-center/announcements',stop=str(stop)),indent=2))
    print('Q2_BROWSER_URL',f'http://127.0.0.1:{port}/wealth/data-center/announcements',flush=True)
    try:
        deadline=time.monotonic()+900
        while not stop.exists() and time.monotonic()<deadline:
            (evidence_dir/'api-evidence.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2)+'\n')
            time.sleep(.5)
        assert stop.exists(),'supervised browser fixture timed out'
    finally:
        server.should_exit=True;thread.join(timeout=5);runtime.close()
        (evidence_dir/'api-evidence.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2)+'\n')
