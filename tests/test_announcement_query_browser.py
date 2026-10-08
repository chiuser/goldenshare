"""Opt-in, automatically closed browser regression with real routes and temporary PG."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

import pytest
import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from web.test_wealth_data_center_downloads import downloads, query_archive, archive, row, pg, pg_cluster
from test_announcement_download_dg import raw_root, write_day


@pytest.mark.skipif(os.environ.get('ANNOUNCEMENT_QUERY_BROWSER') != '1', reason='explicit browser regression only')
def test_lowercase_candidates_and_tail_adjustment(downloads, monkeypatch):
    from src.app.runtime.announcement_archive_lifespan import include_data_center, install_data_center
    from src.app.exceptions import install_exception_handlers
    playwright = Path('/opt/homebrew/lib/node_modules/openclaw/dist/extensions/browser/node_modules/playwright-core/index.mjs')
    executable = Path.home()/'Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
    assert playwright.is_file() and executable.is_file(), 'Use installed browser only; never install'
    d = downloads
    service = d.previews.service()
    raw = raw_root(d.archive)
    write_day(raw, '2026-09-30', [row(i, code='000001.SZ', title=f'历史公告{i}') for i in (1, 2)])
    for day in range(1, 8):
        write_day(raw, f'2026-10-{day:02}', [])
    context = service.context
    def local_context():
        value = context()
        value['queryDefaults'].update(startDate='2026-09-30', endDate='2026-10-08')
        return value
    monkeypatch.setattr(service, 'context', local_context)
    app = FastAPI(); install_exception_handlers(app); install_data_center(app)
    router = APIRouter(prefix='/api/v1'); include_data_center(router); app.include_router(router)
    app.dependency_overrides.update(d.app.dependency_overrides)
    app.state.announcement_source = d.previews
    app.state.announcement_download = d.service
    @app.get('/api/v1/auth/me')
    def me():
        return dict(id=42, username='fixture', is_active=True, display_name='隔离验收')
    @app.get('/api/v1/wealth/market/context')
    def market():
        return dict(pageContext=dict(market='CN_A', tradeDate='2026-10-08', isTradingDay=True, sessionStatus='CLOSED', timezone='Asia/Shanghai', generatedAt='2026-10-08T00:00:00+08:00', source='default'))
    @app.get('/api/v1/wealth/market/major-indices')
    def tickers():
        return dict(pageStatus=dict(displayText='隔离行情样本', status='READY'), majorIndices=dict(rows=[]))
    requests = []
    @app.middleware('http')
    async def evidence(request, call_next):
        body = await request.body() if request.method == 'POST' else None
        result = await call_next(request)
        if request.url.path.startswith('/api/'):
            requests.append(dict(method=request.method, path=request.url.path, query=request.url.query,
                                 body=json.loads(body) if body else None, status=result.status_code))
        return result
    app.mount('/wealth/assets', StaticFiles(directory='wealth/dist/assets'))
    @app.get('/wealth/{path:path}')
    def page(path):
        return FileResponse('wealth/dist/index.html')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    output = Path('reports/wealth_data_center_query_tail_browser_20261008'); output.mkdir(exist_ok=True)
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        subprocess.run(['node', 'wealth/scripts/announcement-query-browser-smoke.mjs', f'http://127.0.0.1:{port}', str(output), str(playwright), str(executable)], check=True, timeout=120)
        assert d.calls == []
    finally:
        server.should_exit = True; thread.join(timeout=10)
        (output/'api-evidence.json').write_text(json.dumps(dict(requests=requests, pdfRequests=d.calls, formalWrites=0, serverStopped=not thread.is_alive()), ensure_ascii=False, indent=2)+'\n')
        assert not thread.is_alive(), 'Test server must be stopped'
