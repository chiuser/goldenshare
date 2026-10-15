"""Read-only mixed-page/multi-tab acceptance with actual TypeScript clients.

No browser automation, app lifespan, account configuration or formal data writes.
Uses the already installed Node/esbuild; no dependency installation or download.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import duckdb
import uvicorn
from fastapi import Depends, FastAPI
from sqlalchemy import text
from src.app.dependencies import get_db_session
from src.app.auth.dependencies import require_quote_access
from src.app.exceptions import WebAppError, install_exception_handlers
from src.foundation.clients.local_lake.major_index_mins_contract import FORMAL_LAKE_ROOT
from src.foundation.clients.local_lake.major_index_mins_reader import MajorIndexMinsLakeReader
from src.foundation.clients.local_lake.index_nine_turn_reader import IndexNineTurnLakeReader
from src.biz.api.wealth.market import index_detail, index_detail_nine_turn, index_detail_minutes, index_detail_minute_nine_turn
from src.biz.api.wealth.market.index_detail_xxm import build_router as signal_router
from src.biz.api.wealth.market.index_detail_minute_xxm import build_router as minute_signal_router
from src.biz.api.wealth.market.index_detail_xxm_forecast import build_router as forecast_router
from src.biz.queries.wealth.market.index_detail_minutes.index_detail_minutes_query_service import IndexDetailMinutesQueryService
from src.biz.queries.wealth.market.index_minute_nine_turn.index_minute_nine_turn_query_service import IndexMinuteNineTurnQueryService
from src.biz.queries.wealth.market.index_detail_xxm import query_service as q, forecast_query_service as fq


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    local=threading.local();counts={};max_compute=0.;lock=threading.Lock()
    original_read=MajorIndexMinsLakeReader._read_complete_history
    def read(self,request,**kwargs):
        with lock: counts[str(request.freq)]=counts.get(str(request.freq),0)+1
        return original_read(self,request,**kwargs)
    MajorIndexMinsLakeReader._read_complete_history=read
    original_calendar,original_build=fq.future_calendar,fq.IndexDetailXxmForecastQueryService.build
    def calendar(*a,**kw):
        value=original_calendar(*a,**kw);local.compute_start=time.perf_counter();return value
    def build(self,*a,**kw):
        nonlocal max_compute
        local.compute_start=None
        try:return original_build(self,*a,**kw)
        finally:
            duration=time.perf_counter()-local.compute_start if local.compute_start else 0.
            with lock:max_compute=max(max_compute,duration)
    fq.future_calendar=calendar;fq.IndexDetailXxmForecastQueryService.build=build
    def readonly_session():
        generator=get_db_session()
        try:
            session=next(generator);session.execute(text('SET TRANSACTION READ ONLY'));yield session
        finally:generator.close()
    app=FastAPI();install_exception_handlers(app)
    app.dependency_overrides[get_db_session]=readonly_session
    common=dict(db_dependency=readonly_session,auth_dependency=require_quote_access,error_factory=WebAppError)
    app.include_router(signal_router(**common),prefix='/api/v1')
    app.include_router(minute_signal_router(**common,lake_dependency=lambda:FORMAL_LAKE_ROOT),prefix='/api/v1')
    app.include_router(forecast_router(**common,lake_dependency=lambda:FORMAL_LAKE_ROOT),prefix='/api/v1')
    # Explicit source dependency only in this isolated audit process; original
    # auth, parsers, contracts, query services and readers remain in the path.
    nine_reader=IndexNineTurnLakeReader(FORMAL_LAKE_ROOT)
    index_detail_minutes._service=lambda:IndexDetailMinutesQueryService(FORMAL_LAKE_ROOT)
    index_detail_minute_nine_turn._service=lambda:IndexMinuteNineTurnQueryService(FORMAL_LAKE_ROOT,reader=nine_reader)
    for router in (index_detail.router,index_detail_nine_turn.router,index_detail_minutes.router,index_detail_minute_nine_turn.router):
        app.include_router(router,prefix='/api/v1')
    @app.get('/__audit__/reset')
    def reset(fresh:int,_user=Depends(require_quote_access)):
        nonlocal max_compute
        if fresh:q._CACHE=q.XxmCache()
        with lock:counts.clear();max_compute=0.
        return {'ok':True}
    @app.get('/__audit__/metrics')
    def metrics(_user=Depends(require_quote_access)):
        with lock:
            return dict(completeReads=dict(counts),maxComputeSeconds=max_compute,
                        cacheBytes=sum(size for _,size in q._CACHE.entries.values()),cacheEntries=len(q._CACHE.entries))
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(32)
    base=f'http://127.0.0.1:{sock.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        while not server.started:
            if not thread.is_alive():raise RuntimeError('Audit server failed to start')
            time.sleep(.01)
        node=shutil.which('node')
        if not node:raise RuntimeError('Existing Node runtime is required; do not install automatically')
        subprocess.run([node,str(Path(__file__).with_suffix('.mjs')),base,str(out)],check=True)
    finally:
        server.should_exit=True;thread.join(10);sock.close()
        (out/'server.json').write_text(json.dumps(dict(serverStopped=not thread.is_alive(),formalWrites=False,
            auth='original require_quote_access',pageAutomation=False,installedDependencies=False),indent=2)+'\n')


if __name__=='__main__':main()
