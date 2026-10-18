"""Explicitly isolated 2020+ daily input; never changes the formal source.

Capture uses read-only PostgreSQL. Check uses only that frozen projection in
an in-memory SQLite fixture and the unique product routes/query/calculator/DTO.
Its timings are NOT formal PostgreSQL, deployed API or page acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import threading
import time

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from . import bottom_history_acceptance as b
from .acceptance import load_source, sha
from .reference_rescue_acceptance import MATH_KEYS, semantic
from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.queries.wealth.market.index_detail_xxm import query_service as q, forecast_query_service as fq
from src.biz.queries.wealth.market.index_detail_xxm.source import assert_continuous, CN_ZONE
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar

START = date(2020, 1, 1)
MAX_ROWS, MAX_CALENDAR = 2000, 3000
CASE_INDICES = (0, 1, 2, 5, 12)
ROOT = Path(__file__).resolve().parents[4]


def validate_window(bars, calendar, end):
    if not bars or len(bars) > MAX_ROWS or not calendar or len(calendar) > MAX_CALENDAR:
        raise ValueError('Window empty or over budget')
    days = [date.fromisoformat(day) for day in calendar]
    if days != sorted(set(days)) or days[0] != START or days[-1] < end:
        raise ValueError('Calendar bounds/order invalid')
    if any(right-left != timedelta(days=1) for left,right in zip(days,days[1:])):
        raise ValueError('Calendar contains missing dates')
    if any(type(value) is not bool for value in calendar.values()):
        raise ValueError('Calendar open flag must be boolean')
    expected = tuple(day for day,opened in calendar.items() if opened and START.isoformat() <= day <= end.isoformat())
    for bar in bars:
        bar.validate('day')
    if tuple(bar.time for bar in bars) != expected:
        raise ValueError('Explicit window has missing/duplicate/out-of-range bars')
    assert_continuous(tuple(bars),period='day',open_dates=tuple(day for day in days if calendar[day.isoformat()]))


def read_window(session, end):
    """Real producer projection: IndexFactorPro and TradeCalendar ORM fields."""
    values, after = [], None
    while True:
        conditions = [IndexFactorPro.ts_code=='000001.SH',IndexFactorPro.trade_date>=START,
                      IndexFactorPro.trade_date<=end]
        if after is not None:
            conditions.append(IndexFactorPro.trade_date>after)
        rows = session.execute(select(IndexFactorPro.trade_date,IndexFactorPro.close,
            IndexFactorPro.macd_dif_bfq,IndexFactorPro.macd_dea_bfq,IndexFactorPro.macd_bfq)
            .where(*conditions).order_by(IndexFactorPro.trade_date).limit(1000)).all()
        if not rows:
            break
        values.extend(XxmBar(row[0].isoformat(),*(float(v) for v in row[1:])) for row in rows)
        if len(values)>MAX_ROWS:
            raise ValueError('Daily capture exceeds bounded window')
        after=rows[-1][0]
    rows=session.execute(select(TradeCalendar.trade_date,TradeCalendar.is_open).where(
        TradeCalendar.exchange=='SSE',TradeCalendar.trade_date>=START,
        TradeCalendar.trade_date<=end+timedelta(days=FORECAST_SPEC.future_calendar_days))
        .order_by(TradeCalendar.trade_date).limit(MAX_CALENDAR+1)).all()
    calendar={day.isoformat():opened for day,opened in rows}
    if len(rows)!=len(calendar):
        raise ValueError('Duplicate calendar dates')
    validate_window(values,calendar,end)
    return tuple(values),calendar


def capture(out):
    with b.readonly_session() as session:
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        context=MarketPageContextQuery().resolve_context(session,market='CN_A',requested_trade_date=None)
        bars,calendar=read_window(session,context.trade_date)
    with (out/'daily_source.csv').open('w',newline='') as stream:
        writer=csv.writer(stream,lineterminator='\n')
        writer.writerow(['trade_date','close','macd_dif_bfq','macd_dea_bfq','macd_bfq'])
        writer.writerows((v.time,v.close,v.dif,v.dea,v.hist) for v in bars)
    b.save(out,'calendar.json',calendar)
    manifest=dict(scope='ISOLATED_DAILY_2020_WINDOW',formalApiAccepted=False,formalWrites=False,
        startDate=START.isoformat(),businessDate=context.trade_date.isoformat(),
        capturedAt=context.generated_at.isoformat(),rows=len(bars),calendarRows=len(calendar),
        algorithmVersion=MAIN_SPEC.algorithm_version,specHash=MAIN_SPEC.spec_hash,
        sourceProjection='core_serving.index_factor_pro: trade_date, close, macd_dif_bfq, macd_dea_bfq, macd_bfq',
        calendarProjection='core_serving.trade_calendar: SSE, trade_date, is_open',
        batchRows=1000,maxRows=MAX_ROWS,maxCalendarRows=MAX_CALENDAR,
        files=[dict(name=name,sha256=sha(out/name)) for name in ('daily_source.csv','calendar.json')])
    b.save(out,'manifest.json',manifest)
    return manifest


@contextmanager
def isolated_client(bars,calendar,now):
    """Temporary fixture based on the real read_daily producer projection.

    Replaces only storage, clock and auth. Business queries/calculation/DTO,
    source validators and all runtime limits are the unchanged product code.
    """
    from fastapi.testclient import TestClient
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def attach(connection,_):
        connection.execute("ATTACH DATABASE ':memory:' AS core_serving")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE core_serving.index_factor_pro (ts_code TEXT, trade_date DATE, close FLOAT, macd_dif_bfq FLOAT, macd_dea_bfq FLOAT, macd_bfq FLOAT)'))
        connection.execute(text('CREATE TABLE core_serving.trade_calendar (exchange TEXT, trade_date DATE, is_open BOOLEAN, pretrade_date DATE)'))
        connection.execute(text("INSERT INTO core_serving.index_factor_pro VALUES ('000001.SH',:day,:close,:dif,:dea,:hist)"),
            [dict(day=v.time,close=v.close,dif=v.dif,dea=v.dea,hist=v.hist) for v in bars])
        connection.execute(text("INSERT INTO core_serving.trade_calendar (exchange,trade_date,is_open) VALUES ('SSE',:day,:opened)"),
            [dict(day=day,opened=opened) for day,opened in calendar.items()])
        connection.execute(text('PRAGMA query_only=ON'))
    def session():
        with Session(engine) as value:
            yield value
    original_load,original_cache=q.IndexDetailXxmQueryService.load_entry,q._CACHE
    def load(self,session,*,period,now=None):
        return original_load(self,session,period=period,now=frozen_now)
    frozen_now=now
    q.IndexDetailXxmQueryService.load_entry=load
    q._CACHE=q.XxmCache()
    try:
        with TestClient(b.app_for(session,None,lambda:None)) as client:
            yield client,session
    finally:
        q.IndexDetailXxmQueryService.load_entry=original_load;q._CACHE=original_cache
        engine.dispose()


def replay_checks(bars,out):
    calculator=XxmCalculator(period='day',source_identity='isolated-daily-2020')
    steps=[];snapshots={};cuts={min(249,len(bars)),min(250,len(bars)),min(1000,len(bars)),len(bars)}
    for index,bar in enumerate(bars,1):
        step=calculator.step(bar);steps.append(step)
        if step.events:
            cuts.add(index)
        if index in cuts:
            snapshots[index]=calculator.snapshot()
    for cut in sorted(cuts):
        child=XxmCalculator(period='day',source_identity=calculator.source_identity)
        assert [child.step(v) for v in bars[:cut]]==steps[:cut]
        assert child.snapshot()==snapshots[cut]
        restored=XxmCalculator(period='day',source_identity=calculator.source_identity)
        restored.restore(snapshots[cut])
        assert [restored.step(v) for v in bars[cut:cut+250]]==steps[cut:cut+250]
    events=[e for step in steps for e in step.events]
    # Independent observed screenshot labels, not expected generated by replay.
    for stamp in ('2024-07-23','2024-08-05','2024-08-22'):
        assert any(e['time']==stamp and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL' and e['direction']=='BOTTOM' for e in events)
    assert any(e['time']=='2024-08-15' and e['type']=='STRUCTURE' and e['direction']=='BOTTOM' for e in events)
    b.save(out,'recognition_ledger.json',dict(points=[s.point for s in steps],events=events,
        prefixRestoreCuts=sorted(cuts),finalSnapshot=calculator.snapshot()))
    return dict(rows=len(bars),events=len(events),prefixRestoreCuts=len(cuts),softwareLiteralCases=4)



def validate_capture_identity(source,manifest):
    # A newly captured r2 source is still legal. Approved r1 capture bytes can
    # also be reused as source facts; they are never restored as old state.
    if manifest['specHash']==MAIN_SPEC.spec_hash:
        assert manifest['algorithmVersion']==MAIN_SPEC.algorithm_version
        return
    from .frozen_inputs import expected_unit
    approved=expected_unit('manifest')['sources']
    relative=str((source/'manifest.json').resolve().relative_to(ROOT))
    assert relative in approved and sha(source/'manifest.json')==approved[relative], 'Unapproved capture manifest'
    assert manifest['specHash']=='533a9b441e49c1b2c076482ad6815f61e49494f63ec2c8c922a03d868e4ce730'

def check(source,out):
    manifest=json.loads((source/'manifest.json').read_text())
    assert manifest['scope']=='ISOLATED_DAILY_2020_WINDOW' and not manifest['formalApiAccepted']
    validate_capture_identity(source,manifest)
    for item in manifest['files']:
        assert sha(source/item['name'])==item['sha256'],'Capture SHA changed'
    bars=tuple(load_source(source,'day'));calendar=json.loads((source/'calendar.json').read_text())
    validate_window(bars,calendar,date.fromisoformat(manifest['businessDate']))
    prior=load_source(ROOT/'reports/xxm_source_audit_20261013_213852','day')
    actual={v.time:v for v in bars};assert all(actual.get(v.time)==v for v in prior)
    summary=dict(scope=manifest['scope'],fixtureOnly=True,formalApiAccepted=False,formalWrites=False,
        sourceManifestSha256=sha(source/'manifest.json'),rows=len(bars),frozenOverlap=len(prior),
        recognition=replay_checks(bars,out),forecasts=0,statuses={},oldCases=[],budget=[])
    model_times=[]
    step_total=[0];step_lock=threading.Lock();original_step=XxmCalculator.step
    def step_counted(self,*args,**kwargs):
        with step_lock:step_total[0]+=1
        return original_step(self,*args,**kwargs)
    XxmCalculator.step=step_counted
    local=threading.local();original_calendar,original_build=fq.future_calendar,fq.IndexDetailXxmForecastQueryService.build
    def calendar_timed(*args,**kwargs):
        value=original_calendar(*args,**kwargs);local.start=time.perf_counter();return value
    def build(self,*args,**kwargs):
        local.start=None
        try:return original_build(self,*args,**kwargs)
        finally:local.elapsed=time.perf_counter()-local.start if local.start else 0.
    fq.future_calendar=calendar_timed;fq.IndexDetailXxmForecastQueryService.build=build
    def predict(client,stamp):
        started=time.perf_counter();response=b.prediction(client,'day',stamp);elapsed=time.perf_counter()-started
        if response.status_code!=200:
            b.save(out,'failed_response.json',dict(through=stamp,status=response.status_code,body=response.json()))
        assert response.status_code==200 and elapsed<=4,(stamp,'isolated request budget/status')
        value=response.json();model=model_times[-1] if model_times else 0.
        assert model<=.2,(stamp,'isolated model budget')
        return value,dict(through=value['computedThrough'],httpSeconds=elapsed,
                          modelEnvelopeMs=1000*model,forecastBytes=len(response.content))
    try:
        with isolated_client(bars,calendar,datetime.fromisoformat(manifest['capturedAt'])) as (client,session):
            # Capture timings inside the worker without sharing a mutable start
            # across concurrent requests. Main-thread local values are not used.
            measured=fq.IndexDetailXxmForecastQueryService.build
            def collect(self,*args,**kwargs):
                try:return measured(self,*args,**kwargs)
                finally:model_times.append(getattr(local,'elapsed',0.))
            fq.IndexDetailXxmForecastQueryService.build=collect
            generator=session();db=next(generator)
            with q.IndexDetailXxmQueryService().load_entry(db,period='day') as (entry,_,_,_):
                real_snapshot=entry.calculator.snapshot()
            generator.close()
            statuses=Counter();max_http=0.;max_bytes=0
            with (out/'forecasts.jsonl').open('w') as stream:
                for index,bar in enumerate(bars,1):
                    value,row=predict(client,bar.time)
                    assert value['computedThrough']==bar.time and value['dataStatus']=='READY'
                    assert row['forecastBytes']<=32768
                    statuses[(value['status'],value['reasonCode'])]+=1
                    max_http=max(max_http,row['httpSeconds']);max_bytes=max(max_bytes,row['forecastBytes'])
                    stream.write(json.dumps(dict(**row,payload=value),ensure_ascii=False)+'\n')
                    if index%100==0 or index==len(bars):
                        summary.update(forecasts=index,statuses={str(k):v for k,v in statuses.items()})
                        b.save(out,'progress.json',summary);stream.flush()
                        print(json.dumps(dict(stage='forecasts',completed=index,total=len(bars))),flush=True)
            generator=session();db=next(generator)
            with q.IndexDetailXxmQueryService().load_entry(db,period='day') as (entry,_,_,_):
                assert entry.calculator.snapshot()==real_snapshot,'Forecast altered real state'
            generator.close();summary['realStateUnchanged']=True
            fixture=ROOT/'reports/xxm_reference_rescue_r1_implementation_20261017/api_02'
            for index in CASE_INDICES:
                old=json.loads((fixture/f'api_forecast_{index}_day.json').read_text())
                value,row=predict(client,old['computedThrough'])
                signal=b.recognition(client,'day',old['computedThrough'])
                assert signal.status_code==200
                if index==12:
                    assert value['status']=='CONFIRMED' and value['confirmedAt']=='2024-08-15'
                changed=[k for k in (*MATH_KEYS,'display') if value[k]!=old[k]]
                summary['oldCases'].append(dict(through=old['computedThrough'],oldStatus=old['status'],
                    newStatus=value['status'],oldReason=old['reasonCode'],newReason=value['reasonCode'],changedFields=changed))
                b.save(out,f'case_{index}_forecast.json',value);b.save(out,f'case_{index}_recognition.json',signal.json())
            for kind in ('cold','warm'):
                for index in range(1,21):
                    if kind=='cold':q._CACHE=q.XxmCache()
                    before_steps=step_total[0]
                    value,row=predict(client,bars[-1].time)
                    started=time.perf_counter();signal=b.recognition(client,'day',bars[-1].time)
                    assert signal.status_code==200 and time.perf_counter()-started<=4
                    row.update(kind=kind,iteration=index,recognitionSeconds=time.perf_counter()-started,
                        cacheBytes=sum(size for _,size in q._CACHE.entries.values()),cacheEntries=len(q._CACHE.entries),
                        calculatorSteps=step_total[0]-before_steps)
                    assert row['calculatorSteps']==0 if kind=='warm' else row['calculatorSteps']>=len(bars)
                    assert row['cacheBytes']<=64*1024*1024 and row['cacheEntries']<=16
                    summary['budget'].append(row)
            latest,row=predict(client,None);assert latest['computedThrough']==bars[-1].time
            b.save(out,'latest.json',latest)
            from concurrent.futures import ThreadPoolExecutor
            q._CACHE=q.XxmCache()
            concurrent_started=time.perf_counter()
            with ThreadPoolExecutor(max_workers=2) as pool:
                left=pool.submit(b.prediction,client,'day',bars[-1].time)
                right=pool.submit(b.recognition,client,'day',bars[-1].time)
                prediction,recognition=left.result(),right.result()
            assert prediction.status_code==recognition.status_code==200
            assert time.perf_counter()-concurrent_started<=4
            assert prediction.json()['sourceInputId']==recognition.json()['source']['inputId']
            assert max(model_times,default=0)<=.2
            summary.update(passed=True,statuses={str(k):v for k,v in statuses.items()},
                maxSweepHttpSeconds=max_http,maxSweepForecastBytes=max_bytes,
                maxModelEnvelopeMs=1000*max(model_times,default=0),concurrentPairPassed=True,
                assumptions=['frozen 2020+ input','temporary SQLite storage','frozen capture clock','auth not under test'])
    finally:
        fq.future_calendar=original_calendar;fq.IndexDetailXxmForecastQueryService.build=original_build
        XxmCalculator.step=original_step
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--capture-source',action='store_true')
    choice.add_argument('--source',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    run=dict(scope='ISOLATED_DAILY_2020_WINDOW',formalApiAccepted=False,formalWrites=False,
             startedAt=datetime.now(CN_ZONE).isoformat())
    b.save(args.output,'run.json',run)
    try:
        result=capture(args.output) if args.capture_source else check(args.source,args.output)
        b.save(args.output,'result.json',result);run['passed']=True
    except Exception as exc:
        run.update(passed=False,failure=dict(type=type(exc).__name__,code=getattr(exc,'code',None)))
        print(json.dumps(run['failure']),flush=True)
        raise SystemExit(1) from None
    finally:
        run['finishedAt']=datetime.now(CN_ZONE).isoformat();b.save(args.output,'run.json',run)


if __name__=='__main__':main()
