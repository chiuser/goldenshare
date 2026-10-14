"""Real production route/DTO against readonly formal sources, ephemeral server.

No app lifespan or jobs. Minute source injection is confined to this harness;
application capability/auth/config and formal sources are never changed.
"""
import sys,json,time,threading,socket,math,resource
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
from fastapi import FastAPI
from sqlalchemy import text
import uvicorn
import duckdb  # normal minute-capability startup import, not source/cache warming
from src.app.dependencies import get_db_session
from src.app.auth.dependencies import require_quote_access
from src.app.exceptions import WebAppError,install_exception_handlers
from src.foundation.clients.local_lake.major_index_mins_contract import FORMAL_LAKE_ROOT
from src.biz.api.wealth.market.index_detail_xxm_forecast import build_router
from src.biz.queries.wealth.market.index_detail_xxm import query_service as q,forecast_query_service as fq
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import ForecastResponseDto
OUT=Path(__file__).resolve().parent
class ColdCache(q.XxmCache):
    def get(self,key):return None
caches={'cold':ColdCache(),'warm':q.XxmCache()}
last={};local=threading.local()
# Diagnostic timing only; no source/cache implementation is changed.
from src.foundation.clients.local_lake.major_index_mins_reader import MajorIndexMinsLakeReader
stages={}
last_by_period={}
def current_stages():
    if not hasattr(local,'stages'):local.stages={}
    return local.stages
def timed(target,name,label):
    original=getattr(target,name)
    def wrapper(*args,**kwargs):
        started=time.perf_counter()
        try:return original(*args,**kwargs)
        finally:current_stages()[label]=current_stages().get(label,0)+time.perf_counter()-started
    setattr(target,name,wrapper)
for target,name,label in [(q,'calendar_dates','sourceCalendar'),(q,'read_minutes','readMinutes'),(q,'assert_continuous','continuity'),(q.XxmCache,'put','cachePut'),(MajorIndexMinsLakeReader,'history_source_signature','sourceSignature')]:timed(target,name,label)
original_calendar=fq.future_calendar;original_build=fq.IndexDetailXxmForecastQueryService.build
original_recover=fq.recover_projection;original_forecast=fq.forecast
def measured_recover(*args,**kwargs):
    current_stages()['historicalReplay']=time.perf_counter()-local.compute_start
    started=time.perf_counter()
    try:return original_recover(*args,**kwargs)
    finally:current_stages()['calibration']=time.perf_counter()-started
def measured_forecast(*args,**kwargs):
    started=time.perf_counter()
    try:return original_forecast(*args,**kwargs)
    finally:current_stages()['rangeSolve']=time.perf_counter()-started
fq.recover_projection=measured_recover;fq.forecast=measured_forecast

def measured_calendar(*args,**kwargs):
    result=original_calendar(*args,**kwargs);local.compute_start=time.perf_counter();return result

def measured_build(self,*args,**kwargs):
    local.compute_start=None;started=time.perf_counter();local.stages={}
    try:
        result=original_build(self,*args,**kwargs)
        measurement=dict(totalBuildSeconds=time.perf_counter()-started,computeSeconds=time.perf_counter()-local.compute_start if local.compute_start else 0.,stages=dict(current_stages()))
        last_by_period[kwargs['period']]=measurement
        return result
    except Exception:
        last_by_period[kwargs['period']]=dict(totalBuildSeconds=time.perf_counter()-started,computeSeconds=time.perf_counter()-local.compute_start if local.compute_start else None,stages=dict(current_stages()))
        raise

fq.future_calendar=measured_calendar;fq.IndexDetailXxmForecastQueryService.build=measured_build

def readonly_session():
    generator=get_db_session()
    try:
        session=next(generator);session.execute(text('SET TRANSACTION READ ONLY'));yield session
    finally:generator.close()
app=FastAPI();install_exception_handlers(app)
app.include_router(build_router(db_dependency=readonly_session,auth_dependency=require_quote_access,lake_dependency=lambda:FORMAL_LAKE_ROOT,error_factory=WebAppError),prefix='/api/v1')
PATH='/api/v1/wealth/market/index-detail/xxm-key-point-forecast'

def request(base,period,as_of=None):
    params=dict(tsCode='000001.SH',period=period)
    if as_of:params['asOf']=as_of
    started=time.perf_counter()
    try:
        with urlopen(base+PATH+'?'+urlencode(params),timeout=6) as r:body=r.read(32769)
    except HTTPError as exc:
        failure=dict(period=period,asOf=as_of,httpStatus=exc.code,body=json.loads(exc.read(32769)),seconds=time.perf_counter()-started,measurement=dict(last_by_period.get(period,{})))
        (OUT/'http_failure.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2));print(json.dumps(failure,ensure_ascii=False),flush=True);raise
    seconds=time.perf_counter()-started;value=json.loads(body)
    ForecastResponseDto(**value)
    assert value['dataStatus']=='READY' and seconds<=4 and len(body)<=32768,(period,value['status'],seconds,len(body))
    assert last_by_period[period]['computeSeconds']<=.2,(period,last_by_period[period])
    return value,dict(seconds=seconds,bytes=len(body),status=value['status'],**last_by_period[period])

if __name__=='__main__':
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(32);port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    while not server.started:time.sleep(.01)
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--diagnose-source',action='store_true');parser.add_argument('--only-concurrent',action='store_true');parser.add_argument('--compute-diagnostics',action='store_true');args=parser.parse_args()
    records=[]
    try:
        if args.compute_diagnostics:
            q._CACHE=caches['warm'];diagnostics=[]
            for i in range(30):
                value,row=request(f'http://127.0.0.1:{port}','m90','2026-10-13T15:00:00+08:00');diagnostics.append(row)
                print(json.dumps(row),flush=True)
                (OUT/'compute_diagnostics.json').write_text(json.dumps(diagnostics,indent=2))
            sys.exit(0)
        if args.diagnose_source:
            q._CACHE=caches['cold'];diagnostics=[]
            for i in range(20):
                value,row=request(f'http://127.0.0.1:{port}','m60','2026-10-13T15:00:00+08:00');diagnostics.append(row);print(json.dumps(row),flush=True)
                (OUT/'source_diagnostics.json').write_text(json.dumps(diagnostics,indent=2))
            sys.exit(0)
        for mode in (() if args.only_concurrent else ('cold','warm')):
            q._CACHE=caches[mode]
            for period in ('day','m60','m90','m120'):
                samples=[];anchor='2026-10-13' if period=='day' else '2026-10-13T15:00:00+08:00'
                for i in range(20):
                    value,row=request(f'http://127.0.0.1:{port}',period,anchor);samples.append(row)
                    if i==0:(OUT/f'http_{mode}_{period}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2))
                record=dict(mode=mode,period=period,p95Seconds=sorted(r['seconds'] for r in samples)[18],maxSeconds=max(r['seconds'] for r in samples),maxComputeSeconds=max(r['computeSeconds'] for r in samples),maxBytes=max(r['bytes'] for r in samples),samples=samples)
                records.append(record);print(json.dumps({k:v for k,v in record.items() if k!='samples'}),flush=True)
                (OUT/'http_p95.json').write_text(json.dumps(dict(kind='final product reader/forecast route/query/DTO; readonly formal sources; no page automation',records=records,rssMaxBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),ensure_ascii=False,indent=2))
        from concurrent.futures import ThreadPoolExecutor
        q._CACHE=caches['cold'];parallel=[]
        for group in (('day','m60'),('m60','m90'),('m90','m120')):
            with ThreadPoolExecutor(max_workers=2) as pool:
                for attempt in range(3):
                    futures={p:pool.submit(request,f'http://127.0.0.1:{port}',p,'2026-10-13' if p=='day' else '2026-10-13T15:00:00+08:00') for p in group}
                    rows={p:f.result()[1] for p,f in futures.items()}
                    parallel.append(dict(group=group,attempt=attempt,rows=rows));print(json.dumps(parallel[-1]),flush=True)
                    (OUT/'concurrent_cold.json').write_text(json.dumps(parallel,indent=2))
        q._CACHE=caches['warm']
        for period in ('day','m60','m90','m120'):
            value,row=request(f'http://127.0.0.1:{port}',period)
            (OUT/f'http_latest_{period}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2))
            print(json.dumps(dict(latest=period,through=value['computedThrough'],status=value['status'],measurement=row)),flush=True)
    finally:
        server.should_exit=True;thread.join(10);sock.close()
