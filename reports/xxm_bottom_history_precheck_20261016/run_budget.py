"""Read-only formal-source conservative service envelope, not migrated product HTTP acceptance."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from datetime import datetime
from bisect import bisect_right
import hashlib,json,time,sys
from sqlalchemy import text
from src.app.dependencies import get_db_session
from src.foundation.config.settings import get_settings
from sqlalchemy.engine import make_url
from src.foundation.clients.local_lake.major_index_mins_contract import FORMAL_LAKE_ROOT
from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService,XxmCache,_deep_size
from src.biz.queries.wealth.market.index_detail_xxm.forecast_query_service import future_calendar
from src.biz.queries.wealth.market.index_detail_xxm.source import CN_ZONE,ENDPOINTS
from src.biz.services.wealth.market.index_detail_xxm import forecast_detector
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast,inactive_result
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import build_display_context,make_display
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection,ProjectionPrecisionError
from candidate import CandidateCalculator,SPEC
from scripts.research.index_market.xxm.acceptance import load_source
ROOT=Path('/Users/congming/github/goldenshare');OUT=ROOT/'reports/xxm_bottom_history_precheck_20261016';SOURCE=ROOT/'reports/xxm_source_audit_20261013_213852'
NOW=datetime(2026,10,14,16,tzinfo=CN_ZONE)
rows=[];warm={};candidate_cache={}
url=make_url(get_settings().database_url)
metadata=dict(scope='conservative direct-service research envelope, NOT new HTTP/schema/mixed-tabs acceptance',configuredDatabase=dict(driver=url.drivername,host=url.host,port=url.port,database=url.database),readonly=True,now=NOW.isoformat(),formalLakeRoot=str(FORMAL_LAKE_ROOT),schemas=['core_serving'],tables={'trade_calendar':['exchange','trade_date','is_open','pretrade_date'],'index_factor_pro':['ts_code','trade_date','close','macd_dif_bfq','macd_dea_bfq','macd_bfq']},frozenSourceCompared=True,actualProductPatched=False,includesOldDetectorPlusFullCandidateOnCold=True,applicationColdDefinition='new query and candidate caches; OS/PostgreSQL buffer caches not evicted')

def save():
    (OUT/'budget_records.json').write_text(json.dumps(dict(metadata=metadata,requests=rows),ensure_ascii=False,indent=2)+'\n')

@contextmanager
def readonly():
    gen=get_db_session()
    try:
        s=next(gen);s.execute(text('SET TRANSACTION READ ONLY'));yield s
    finally:gen.close()


def calculate(period,entry,remaining):
    c=CandidateCalculator(period=period,source_identity=entry.calculator.source_identity);points=[];events=[];bottom={};top={};checkpoints={}
    for i,b in enumerate(entry.processed,1):
        if i%1000==0:remaining()
        step=c.step(b);points.append(step.point);events.extend(step.events);bottom.update({h['id']:h for h in step.bottomHistories});top.update({h['id']:h for h in step.histories})
        if i%1000==0:checkpoints[i]=c.snapshot()
    remaining();return dict(calculator=c,points=points,events=events,bottom=bottom,top=top,checkpoints=checkpoints)


def request(period,kind,iteration):
    start=time.perf_counter()
    def remaining():
        left=4-(time.perf_counter()-start)
        if left<=0:raise TimeoutError('4s research envelope')
        return left
    cache=XxmCache() if kind=='cold' else warm.setdefault(period,XxmCache())
    service=IndexDetailXxmQueryService(lake_root=FORMAL_LAKE_ROOT,cache=cache)
    with readonly() as s:
        with service.load_entry(s,period=period,now=NOW) as (entry,context,open_dates,source_remaining):
            read=time.perf_counter();remaining()
            assert context.trade_date.isoformat()=='2026-10-13'
            frozen=load_source(SOURCE,period)
            assert tuple(frozen)==entry.processed,(period,'formal source differs from frozen source')
            key=(period,entry.fingerprints[-1],SPEC.spec_hash)
            state=calculate(period,entry,remaining) if kind=='cold' or key not in candidate_cache else candidate_cache[key]
            if kind=='warm':candidate_cache[key]=state
            detector_done=time.perf_counter()
            c=state['calculator'];bars=entry.processed;through=bars[-1].time
            last=next((e for e in reversed(state['events']) if e['type']=='STRUCTURE'),None)
            is_confirmed=c.state=='STRUCTURE' or last and last['time']==through
            ends=() if is_confirmed else future_calendar(s,period,through,remaining)[0]
            compute_start=time.perf_counter()
            def model_check():
                remaining()
                if (time.perf_counter()-compute_start)*1000>200:raise TimeoutError('200ms forecast')
            old=forecast_detector.XxmCalculator;forecast_detector.XxmCalculator=CandidateCalculator
            try:
                child=forecast_detector.clone(c)
                if is_confirmed:r=inactive_result('CONFIRMED')
                else:
                    try:r=forecast(child,recover_projection(bars,period,model_check),ends,model_check)
                    except ProjectionPrecisionError as exc:r=inactive_result('PRECISION_PENDING',exc.reason)
                conf=r['status']=='CONFIRMED';r.update(confirmedAt=last['time'] if conf and last else None,confirmedDirection=last['direction'] if conf and last else None)
                r['direction']=r['confirmedDirection'] if conf else 'TOP' if bars[-1].hist>0 else 'BOTTOM' if bars[-1].hist<0 else None
                clocks=('15:00',) if period=='day' else tuple(t.strftime('%H:%M') for t in ENDPOINTS[int(period[1:])])
                r['display']=make_display(r,period,through,'REPLAY',build_display_context(bars,period,through,r,clocks,model_check),model_check)
                model_check()
            finally:forecast_detector.XxmCalculator=old
            model_ms=(time.perf_counter()-compute_start)*1000
            # Raw proposed payload size, not strict-DTO validation (B2 is not implemented).
            first=state['points'][max(0,len(bars)-2000)]['time']
            shadow=dict(tsCode='000001.SH',period=period,algorithmVersion=SPEC.algorithm_version,specHash=SPEC.spec_hash,points=state['points'][-2000:],events=[e for e in state['events'] if e['time']>=first],topHistories=list(state['top'].values()),bottomHistories=list(state['bottom'].values()))
            size=len(json.dumps(shadow,ensure_ascii=False,separators=(',',':')).encode());assert size<1048576
            fsize=len(json.dumps(r,ensure_ascii=False).encode())+2048;assert fsize<32768
            memory=_deep_size((entry,state));assert memory<64*1024*1024
            remaining();source_remaining()
            return dict(period=period,kind=kind,iteration=iteration,rows=len(bars),through=through,status=r['status'],totalSeconds=time.perf_counter()-start,sourceSeconds=read-start,candidateReplaySeconds=detector_done-read,forecastMs=model_ms,shadowMax2000ResponseBytes=size,forecastBytesWith2048Envelope=fsize,combinedBaseAndCandidateBytes=memory)

try:
    save()
    for period in ('day','m60','m90','m120'):
        for kind in ('cold','warm'):
            for i in range(1,21):
                row=request(period,kind,i);rows.append(row);save()
                if i in (1,10,20):print(json.dumps(row),flush=True)
    metadata['passed']=True;save()
except Exception as exc:
    # Never dump DB exception text/DSN; preserve safe error class and known contract code only.
    metadata.update(passed=False,failure=dict(type=type(exc).__name__,code=getattr(exc,'code',None),period=period,kind=kind,iteration=i))
    save();print(json.dumps(metadata['failure']),flush=True);sys.exit(1)
