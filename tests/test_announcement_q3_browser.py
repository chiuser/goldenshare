"""Explicit supervised Q3 browser fixture: real routes/PG/Parquet and injected PDF HTTP."""
import json
import os
from pathlib import Path
import socket
import threading
import time
import pytest
import httpx
from fastapi import FastAPI,APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from web.test_wealth_data_center_downloads import downloads,query_archive,archive,row,pg,pg_cluster
from test_announcement_download_cli import PDF
from test_announcement_download_dg import write_day,raw_root


@pytest.mark.skipif(os.environ.get('ANNOUNCEMENT_Q3_BROWSER')!='1',reason='explicit supervised browser acceptance only')
def test_browser_fixture(downloads,monkeypatch,tmp_path):
    d=downloads;service=d.previews.service();raw=raw_root(d.archive)
    write_day(raw,'2026-09-30',[row(i,title=f'PG公告验收{i}') for i in range(1,7)])
    context=service.context
    def local_context():
        value=context();value['queryDefaults'].update(startDate='2026-09-30',endDate='2026-09-30');return value
    monkeypatch.setattr(service,'context',local_context)
    failed={'once':False}
    def behavior(request):
        if request.url.path=='/2.pdf' and not failed['once']:
            failed['once']=True;return httpx.Response(404)
        return httpx.Response(200,content=PDF)
    d.behavior['handler']=behavior
    from src.app.runtime.announcement_archive_lifespan import include_data_center,install_data_center
    from src.app.exceptions import install_exception_handlers
    app=FastAPI();install_exception_handlers(app);install_data_center(app)
    router=APIRouter(prefix='/api/v1');include_data_center(router);app.include_router(router)
    app.dependency_overrides.update(d.app.dependency_overrides)
    app.state.announcement_source=d.previews;app.state.announcement_download=d.service
    @app.post('/api/v1/auth/login')
    def login():return dict(token='q3-fixture',refresh_token=None,username='fixture',display_name='Q3验收',access_token_expires_at=None)
    @app.get('/api/v1/auth/me')
    def me():return dict(id=42,username='fixture',is_active=True,display_name='Q3验收')
    app.mount('/wealth/assets',StaticFiles(directory='wealth/dist/assets'))
    @app.get('/wealth/{path:path}')
    def page(path):return FileResponse('wealth/dist/index.html')
    requests=[]
    @app.middleware('http')
    async def evidence(request,call_next):
        started=time.monotonic();result=await call_next(request)
        if request.url.path.startswith('/api/'):
            requests.append(dict(method=request.method,path=request.url.path,query=request.url.query,status=result.status_code,seconds=time.monotonic()-started))
        return result
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    directory=Path('reports/wealth_data_center_q3_browser_20261007');directory.mkdir(exist_ok=True)
    stop=tmp_path/'done'
    (directory/'fixture.json').write_text(json.dumps(dict(url=f'http://127.0.0.1:{port}/wealth/data-center/announcements',stop=str(stop)),indent=2))
    print('Q3_BROWSER_URL',f'http://127.0.0.1:{port}/wealth/data-center/announcements',flush=True)
    try:
        deadline=time.monotonic()+900
        while not stop.exists() and time.monotonic()<deadline:
            (directory/'api-evidence.json').write_text(json.dumps(dict(api=requests,pdfRequests=d.calls),ensure_ascii=False,indent=2)+'\n')
            time.sleep(.5)
        assert stop.exists(),'supervised browser fixture timed out'
    finally:
        server.should_exit=True;thread.join(timeout=5)
        (directory/'api-evidence.json').write_text(json.dumps(dict(api=requests,pdfRequests=d.calls),ensure_ascii=False,indent=2)+'\n')
