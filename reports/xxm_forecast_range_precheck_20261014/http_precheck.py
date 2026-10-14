"""Ephemeral loopback HTTP harness: normal DB config + same quote auth.

No app lifespan, scheduler, credentials probe/reuse, writes, or prod route change.
Prototype transport, NOT acceptance of the future production DTO.
"""
import sys,json,time,threading,socket,math,resource
from bisect import bisect_right
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from datetime import datetime
from urllib.request import urlopen
from urllib.parse import urlencode
from fastapi import FastAPI,Depends,HTTPException
from sqlalchemy import text
import uvicorn
# The real enabled local-minute app imports DuckDB during capability resolution.
# Match that normal server-startup stage, without warming source/query caches.
import duckdb
from src.app.dependencies import get_db_session
from src.app.auth.dependencies import require_quote_access
from src.foundation.config.settings import get_settings
from src.foundation.config.local_minute_capability import resolve_index_minute_capability
from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService,XxmCache,XxmQueryError
from src.biz.queries.wealth.market.index_detail_xxm.forecast_query_service import future_calendar,digest
from src.biz.queries.wealth.market.index_detail_xxm.source import expected_through
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection,ProjectionPrecisionError
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from reports.xxm_forecast_range_precheck_20261014.range_model import make_result,clone
from reports.xxm_forecast_range_precheck_20261014.text_model import make_display
from reports.xxm_forecast_range_precheck_20261014.run_precheck import OUT

class ColdCache(XxmCache):
    def get(self,key):return None

cap=resolve_index_minute_capability(get_settings())
# Research-only source injection, same explicit root already approved in LLD.
# This does not alter or open the application's minute API capability.
from src.foundation.clients.local_lake.major_index_mins_contract import FORMAL_LAKE_ROOT
lake_root=FORMAL_LAKE_ROOT
assert lake_root.is_dir()
services={mode:IndexDetailXxmQueryService(lake_root=lake_root,cache=ColdCache() if mode=='cold' else XxmCache()) for mode in ('cold','warm')}
app=FastAPI()

@app.get('/probe/{mode}',dependencies=[Depends(require_quote_access)])
def probe(mode:str,period:str,asOf:str|None=None,session=Depends(get_db_session)):
    # Scope the transaction read-only; never print DSNs or auth settings.
    session.execute(text('SET TRANSACTION READ ONLY'))
    request_started=time.perf_counter();stage='source';source_seconds=None;started=None
    try:
        with services[mode].load_entry(session,period=period) as (entry,now,open_dates,remaining):
            source_seconds=time.perf_counter()-request_started;stage='prefix'
            expected=asOf or expected_through(period,open_dates,now,None)
            n=bisect_right([b.time for b in entry.processed],expected) if expected else 0
            bars=entry.processed[:n];through=bars[-1].time if bars else None
            data='EMPTY' if not through else 'DELAYED' if through<expected else 'READY'
            ordinary=entry.points[n-1]['ordinaryState'] if n else None
            calendar=None;compute_seconds=0.;result={}
            if data!='READY':result=dict(status=data,reasonCode='SOURCE_EMPTY' if data=='EMPTY' else 'SOURCE_DELAYED',targetEndpoint=None,barsAhead=None,activation=None,assumption=None,targetEntryRanges=[],targetEntryExclusions=[],relations=[],commonConditions=[],examples=[])
            elif ordinary=='STRUCTURE':result=dict(status='CONFIRMED',reasonCode=None,targetEndpoint=None,barsAhead=None,activation=None,assumption=None,targetEntryRanges=[],targetEntryExclusions=[],relations=[],commonConditions=[],examples=[])
            else:
                stage='calendar'
                slots,calendar=future_calendar(session,period,through,remaining)
                started=time.perf_counter();stage='compute'
                def check():
                    remaining()
                    if time.perf_counter()-started>.2:raise XxmQueryError('XXMF_BUDGET_EXCEEDED','new compute >200ms',503)
                if n==len(entry.processed):c=clone(entry.calculator)
                else:
                    c=XxmCalculator(period=period,source_identity=entry.calculator.source_identity)
                    for i,b in enumerate(bars):
                        if i%1000==0:check()
                        c.step(b)
                p=recover_projection(bars,period,check)
                result=make_result(c,p,slots,check)
                compute_seconds=time.perf_counter()-started
            result['direction']='TOP' if n and entry.points[n-1]['hist']>0 else 'BOTTOM' if n and entry.points[n-1]['hist']<0 else None
            confirmation=next((e for e in reversed(entry.events) if e['time']<=through and e['type']=='STRUCTURE'),None) if through else None
            result['confirmedAt']=confirmation['time'] if result['status']=='CONFIRMED' and confirmation else None
            result['confirmedDirection']=confirmation['direction'] if result['status']=='CONFIRMED' and confirmation else None
            payload=dict(tsCode='000001.SH',period=period,forecastVersion='xxm-key-point-forecast-v0.2',forecastSpecHash=digest({'approvedRangeModel':2}),detectorSpecHash=MAIN_SPEC.spec_hash,
                         sourceInputId=entry.fingerprints[n-1] if n else None,calendarInputId=calendar,computedThrough=through,requestedAsOf=asOf,mode='REPLAY' if asOf else 'LATEST',dataStatus=data,ordinaryState=ordinary,
                         precisionPolicy='rounded3_guarded' if period=='day' else 'full_float',refreshAfterMs=60000,**result)
            payload['display']=make_display(result,period,through,payload['mode']);payload['applicabilityText']='目标适用前置范围见正文。';payload['invalidationText']='钝化消失、零柱或前序走势变化时重算。'
            payload['forecastId']=digest(payload)
            body=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
            if len(body)>32768:raise XxmQueryError('XXMF_BUDGET_EXCEEDED','response >32KiB',503)
            remaining()
            if data=='READY' and ordinary!='STRUCTURE':check()
            if data=='READY' and ordinary!='STRUCTURE':compute_seconds=time.perf_counter()-started
            payload['_precheck']=dict(computeSeconds=compute_seconds,rows=n,sourceRows=len(entry.processed),researchRootInjected=True)
            return payload
    except XxmQueryError as exc:
        diagnostic=dict(code=exc.code,message=str(exc),stage=stage,totalSeconds=time.perf_counter()-request_started,sourceSeconds=source_seconds,computeSeconds=time.perf_counter()-started if started else None)
        raise HTTPException(exc.status,diagnostic) from exc

if __name__=='__main__':
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(32);port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    while not server.started:time.sleep(.01)
    records=[]
    try:
        import argparse
        parser=argparse.ArgumentParser();parser.add_argument('--period',choices=('day','m60','m90','m120'));parser.add_argument('--after-day',action='store_true');parser.add_argument('--only-latest',action='store_true');args=parser.parse_args()
        if args.after_day:
            for i in range(20):
                with urlopen(f'http://127.0.0.1:{port}/probe/cold?period=day&asOf=2026-10-13',timeout=6) as r:r.read(32769)
            print('Completed 20 preceding daily cold requests',flush=True)
        for mode in (() if args.only_latest else ('cold','warm')):
            for period in ((args.period,) if args.period else ('day','m60','m90','m120')):
                samples=[]
                for i in range(20):
                    params=dict(period=period,asOf='2026-10-13' if period=='day' else '2026-10-13T15:00:00+08:00')
                    started=time.perf_counter()
                    from urllib.error import HTTPError
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/probe/{mode}?'+urlencode(params),timeout=6) as r:body=r.read(32769)
                    except HTTPError as exc:
                        diagnostic=json.loads(exc.read(32769))
                        failure=dict(mode=mode,period=period,sample=i,httpStatus=exc.code,seconds=time.perf_counter()-started,error=diagnostic)
                        (OUT/'http_budget_failure.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2))
                        print('BUDGET_FAILURE '+json.dumps(failure,ensure_ascii=False),flush=True)
                        raise
                    v=json.loads(body);seconds=time.perf_counter()-started
                    if seconds>4 or len(body)>32768:
                        failure=dict(mode=mode,period=period,sample=i,seconds=seconds,bytes=len(body),diagnostic=v.get('_precheck'),status=v.get('status'))
                        print('BUDGET_FAILURE '+json.dumps(failure),flush=True)
                        (OUT/'http_budget_failure.json').write_text(json.dumps(failure,indent=2))
                        raise AssertionError(failure)
                    assert v['dataStatus']=='READY',v['dataStatus']
                    samples.append(dict(seconds=seconds,computeSeconds=v['_precheck']['computeSeconds'],bytes=len(body),status=v['status'],rows=v['_precheck']['rows']))
                    if i==0:(OUT/f'http_{mode}_{period}.json').write_text(json.dumps(v,ensure_ascii=False,indent=2))
                record=dict(mode=mode,period=period,samples=samples,p95Seconds=sorted(x['seconds'] for x in samples)[math.ceil(.95*20)-1],maxSeconds=max(x['seconds'] for x in samples),maxComputeSeconds=max(x['computeSeconds'] for x in samples))
                records.append(record);print(json.dumps({k:v for k,v in record.items() if k!='samples'}),flush=True)
                (OUT/('http_p95_'+args.period+'.json' if args.period else 'http_p95.json')).write_text(json.dumps(dict(kind='prototype source/context/normal-auth HTTP precheck, not final DTO/route acceptance',records=records,rssMaxBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),ensure_ascii=False,indent=2))
        for period in ('day','m60','m90','m120'):
            with urlopen(f'http://127.0.0.1:{port}/probe/warm?'+urlencode(dict(period=period)),timeout=6) as r:v=json.loads(r.read(32769))
            (OUT/f'http_latest_{period}.json').write_text(json.dumps(v,ensure_ascii=False,indent=2))
            print(json.dumps(dict(latest=period,through=v['computedThrough'],status=v['status'])),flush=True)
    finally:
        server.should_exit=True;thread.join(10);sock.close()
