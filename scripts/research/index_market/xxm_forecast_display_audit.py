"""Read-only XXM HTTP budget audit; no app lifespan, jobs or page automation.

Run from the repository root. Candidate code is an explicit local precheck input;
product mode uses the normal query unchanged. Reports never contain credentials.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import resource
import socket
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import duckdb  # Match the normal minute startup import, not a source warmup.
from fastapi import FastAPI
from sqlalchemy import text
import uvicorn
from src.app.dependencies import get_db_session
from src.app.auth.dependencies import require_quote_access
from src.app.exceptions import WebAppError, install_exception_handlers
from src.foundation.clients.local_lake.major_index_mins_contract import FORMAL_LAKE_ROOT
from src.biz.api.wealth.market.index_detail_xxm_forecast import build_router
from src.biz.queries.wealth.market.index_detail_xxm import query_service as q, forecast_query_service as fq
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import ForecastResponseDto

PERIODS = ('day', 'm60', 'm90', 'm120')
PATH = '/api/v1/wealth/market/index-detail/xxm-key-point-forecast'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--candidate', help='Explicit local candidate module, precheck only')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    local = threading.local()
    measured = {}
    candidate = None
    if args.candidate:
        path = Path(args.candidate).resolve()
        spec = importlib.util.spec_from_file_location('xxm_display_audit_candidate', path)
        candidate = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = candidate
        spec.loader.exec_module(candidate)
        (out/'candidate_identity.json').write_text(json.dumps(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),spec=candidate.SPEC.__dict__),indent=2)+'\n')
    original_calendar, original_build = fq.future_calendar, fq.IndexDetailXxmForecastQueryService.build
    original_recover = fq.recover_projection
    def calendar(*a, **kw):
        value = original_calendar(*a, **kw)
        local.compute_start = time.perf_counter()
        return value
    def recover(bars, *a, **kw):
        local.bars = bars
        return original_recover(bars, *a, **kw)
    if candidate:
        def display(result, period, through, mode, *_product_context, **_product_options):
            def check():
                if local.compute_start and time.perf_counter()-local.compute_start > .2:
                    raise q.XxmQueryError('XXM_BUDGET_EXCEEDED','预测计算超过预算。',503)
            clocks = ('15:00',) if period=='day' else tuple(t.strftime('%H:%M') for t in fq.ENDPOINTS[int(period[1:])])
            before = json.dumps(result, sort_keys=True)
            context = candidate.build_display_context(local.bars or (),period,through,result,clocks,check)
            value = candidate.make_display(result,period,through,mode,context,check)
            assert json.dumps(result,sort_keys=True)==before
            local.display_context = context
            return value
        fq.make_display = display
        fq.recover_projection = recover
    def build(self, *a, **kw):
        local.compute_start = None
        local.bars = None
        local.display_context = None
        started = time.perf_counter()
        try:
            value = original_build(self, *a, **kw)
            measured[kw['period']] = dict(buildSeconds=time.perf_counter()-started,
                computeSeconds=time.perf_counter()-local.compute_start if local.compute_start else 0.,
                displayContext=local.display_context)
            return value
        except Exception:
            measured[kw['period']] = dict(buildSeconds=time.perf_counter()-started,
                computeSeconds=time.perf_counter()-local.compute_start if local.compute_start else None)
            raise
    fq.future_calendar = calendar
    fq.IndexDetailXxmForecastQueryService.build = build
    def readonly_session():
        generator = get_db_session()
        try:
            session = next(generator)
            session.execute(text('SET TRANSACTION READ ONLY'))
            yield session
        finally:
            generator.close()
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(build_router(db_dependency=readonly_session,auth_dependency=require_quote_access,
        lake_dependency=lambda:FORMAL_LAKE_ROOT,error_factory=WebAppError),prefix='/api/v1')
    sock = socket.socket()
    sock.bind(('127.0.0.1',0))
    sock.listen(32)
    base = f'http://127.0.0.1:{sock.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off',access_log=False))
    thread = threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError('Audit server failed to start')
        time.sleep(.01)
    def request(period, as_of=None):
        params = dict(tsCode='000001.SH',period=period)
        if as_of:
            params['asOf'] = as_of
        started = time.perf_counter()
        try:
            with urlopen(base+PATH+'?'+urlencode(params),timeout=6) as response:
                body = response.read(32769)
        except HTTPError as error:
            failure=dict(period=period,httpStatus=error.code,body=json.loads(error.read(32769)),measurement=measured.get(period),seconds=time.perf_counter()-started)
            (out/'failure.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2)+'\n')
            raise RuntimeError(f'HTTP audit failed: {period} {error.code}') from None
        duration = time.perf_counter()-started
        value = json.loads(body)
        ForecastResponseDto(**value)
        row = dict(seconds=duration,bytes=len(body),status=value['status'],through=value['computedThrough'],**measured[period])
        assert value['dataStatus']=='READY' and duration<=4 and len(body)<=32768 and row['computeSeconds']<=.2,row
        assert not any(s in value['display']['conditionsText'] for s in ('前置收盘','目标收盘','充分条件','差异举例','临界点'))
        return value,row
    class ColdCache(q.XxmCache):
        def get(self,key):
            return None
    records=[]
    try:
        for mode in ('cold','warm'):
            q._CACHE = ColdCache() if mode=='cold' else q.XxmCache()
            for period in PERIODS:
                anchor = '2026-10-13' if period=='day' else '2026-10-13T15:00:00+08:00'
                samples=[]
                for i in range(20):
                    value,row=request(period,anchor)
                    samples.append(row)
                    if i==0:
                        (out/f'http_{mode}_{period}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
                record=dict(mode=mode,period=period,p95Seconds=sorted(r['seconds'] for r in samples)[18],maxSeconds=max(r['seconds'] for r in samples),maxComputeSeconds=max(r['computeSeconds'] for r in samples),maxBytes=max(r['bytes'] for r in samples),samples=samples)
                records.append(record)
                (out/'http_p95.json').write_text(json.dumps(dict(mode='candidate' if candidate else 'product',records=records,rssMaxBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),ensure_ascii=False,indent=2)+'\n')
                print(json.dumps({k:v for k,v in record.items() if k!='samples'}),flush=True)
        q._CACHE=ColdCache()
        parallel=[]
        for group in (('day','m60'),('m60','m90'),('m90','m120')):
            with ThreadPoolExecutor(max_workers=2) as pool:
                for attempt in range(3):
                    pending={p:pool.submit(request,p,'2026-10-13' if p=='day' else '2026-10-13T15:00:00+08:00') for p in group}
                    rows={p:f.result()[1] for p,f in pending.items()}
                    parallel.append(dict(group=group,attempt=attempt,rows=rows))
                    (out/'concurrent_cold.json').write_text(json.dumps(parallel,ensure_ascii=False,indent=2)+'\n')
                    print(json.dumps(dict(group=group,attempt=attempt,maxSeconds=max(r['seconds'] for r in rows.values()))),flush=True)
        q._CACHE=q.XxmCache()
        for period in PERIODS:
            value,row=request(period)
            (out/f'http_latest_{period}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(dict(latest=period,measurement=row)),flush=True)
    finally:
        server.should_exit=True
        thread.join(10)
        sock.close()
    print(json.dumps(dict(status='PASS',budgetRequests=160+len(parallel)*2,latestRequests=4,serverStopped=not thread.is_alive())),flush=True)


if __name__=='__main__':
    main()
