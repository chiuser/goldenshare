"""B-group acceptance of the unique product kernel; never write formal data.

Frozen/API fixtures are isolated evidence, not protected-service performance.
Budget explicitly opts into normal read-only DB and the formal Lake.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

from .acceptance import load_source, sha
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast, inactive_result
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import build_display_context, make_display
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection, ProjectionPrecisionError
from src.biz.queries.wealth.market.index_detail_xxm import query_service as q, forecast_query_service as fq
from src.biz.queries.wealth.market.index_detail_xxm.source import CN_ZONE, ENDPOINTS

ROOT = Path(__file__).resolve().parents[4]
B1 = ROOT / 'reports/xxm_bottom_history_precheck_20261016'
PERIODS = ('day', 'm60', 'm90', 'm120')


def save(out, name, value):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def new(period):
    return XxmCalculator(period=period, source_identity='h1-acceptance:'+period)


def replay(period, bars):
    calculator = new(period)
    steps = [calculator.step(bar) for bar in bars]
    return calculator, steps


def calendar_rows(source):
    rows = json.loads((source / 'sse_minute_calendar.json').read_text())
    future = ROOT / 'reports/xxm_forecast_precheck_20261014/future_sse_calendar.json'
    by_date = {r['trade_date']: r['is_open'] for r in rows}
    for row in json.loads(future.read_text())['rows']:
        if row['trade_date'] in by_date:
            assert by_date[row['trade_date']] == row['is_open']
        by_date[row['trade_date']] = row['is_open']
    return by_date


def future_slots(calendar, period, through):
    result = []
    for day, opened in sorted(calendar.items()):
        if not opened or day < through[:10]: continue
        for slot in ([None] if period == 'day' else ENDPOINTS[int(period[1:])]):
            stamp = day if slot is None else datetime.combine(date.fromisoformat(day), slot, CN_ZONE).isoformat()
            if stamp > through: result.append(stamp)
            if len(result) == 20: return tuple(result)
    raise ValueError('Frozen calendar does not cover forecast')


def forecast_result(period, bars, calculator, confirmation, calendar, check):
    through = bars[-1].time
    before = calculator.snapshot()
    if calculator.state == 'STRUCTURE' or confirmation and confirmation['time'] == through:
        result = inactive_result('CONFIRMED')
    else:
        try:
            result = forecast(calculator, recover_projection(tuple(bars), period, check), future_slots(calendar, period, through), check)
        except ProjectionPrecisionError as exc:
            result = inactive_result('PRECISION_PENDING', exc.reason)
    confirmed = result['status'] == 'CONFIRMED'
    result.update(confirmedAt=confirmation['time'] if confirmed and confirmation else None,
                  confirmedDirection=confirmation['direction'] if confirmed and confirmation else None)
    result['direction'] = result['confirmedDirection'] if confirmed else 'TOP' if bars[-1].hist > 0 else 'BOTTOM' if bars[-1].hist < 0 else None
    result['applicabilityText'] = ('仅适用于本周期已计算的收盘条件；实际收盘后更新。' if result['activation']
                                 else '按当前真实状态与明确的中间走势假设计算。')
    result['invalidationText'] = ('原钝化消失、零柱或前序走势变化时重新计算；未达结构条件不等于钝化已消失。'
                                if result['status'] in ('READY','CONDITIONAL_ENTRY','ENTRY_ONLY') else '新完成行情到达后重新判断。')
    clocks = ('15:00',) if period == 'day' else tuple(t.strftime('%H:%M') for t in ENDPOINTS[int(period[1:])])
    context = build_display_context(bars, period, through, result, clocks, check)
    result['display'] = make_display(result, period, through, 'REPLAY', context, check)
    check()
    child = clone(calculator)
    assert child.snapshot() == before and calculator.snapshot() == before
    if child.pending_bottom_history: child.pending_bottom_history['originalReference']['dif'] = -999
    assert calculator.snapshot() == before
    return result


def frozen_mode(source, out, sources):
    calendar = calendar_rows(source)
    summary = {'periods': {}, 'softwarePositiveObservations': 5, 'softwareFormulaProven': False}
    # Existing original algorithm acceptance preserves ordinary and TOP semantic
    # baselines. Compare associations by timestamps, rather than discard them.
    original_root = ROOT / 'reports/xxm_implementation_20261013'
    for period, bars in sources.items():
        started = time.perf_counter(); calculator, steps = replay(period, bars)
        events = [e for step in steps for e in step.events]
        bottom = {h['id']: h for step in steps for h in step.bottom_histories}
        additions = [e for e in events if e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL']
        expected = json.loads((B1 / f'replay_{period}.json').read_text())
        assert additions == expected['events'] and list(bottom.values()) == expected['bottomHistories'], period
        top = {h['id']: h for step in steps for h in step.histories}
        old = json.loads((original_root / f'baseline_{period}.json').read_text())
        old_top = {h['id']: h for h in old['topHistories']}
        retained = [e for e in events if not (e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL')]
        def event_semantics(event, histories):
            return {**{k:v for k,v in event.items() if k not in ('id','relatedTopHistoryId','relatedBottomHistoryId')},
                    'topAnchor': histories[event['relatedTopHistoryId']]['confirmedAt'] if event['relatedTopHistoryId'] else None}
        assert [event_semantics(e, top) for e in retained] == [event_semantics(e, old_top) for e in old['events']]
        assert [{k:v for k,v in h.items() if k!='id'} for h in top.values()] == [{k:v for k,v in h.items() if k!='id'} for h in old_top.values()]
        old_top_by_anchor = {h['confirmedAt']:h['id'] for h in old_top.values()}
        top_ids = {h['id']:old_top_by_anchor[h['confirmedAt']] for h in top.values()}
        old_points = []
        for step in steps:
            point = {k:v for k,v in step.point.items() if k!='pendingBottomHistoryId'}
            if point['pendingTopHistoryId'] is not None:
                point['pendingTopHistoryId'] = top_ids[point['pendingTopHistoryId']]
            old_points.append(point)
        assert hashlib.sha256(json.dumps(old_points,sort_keys=True).encode()).hexdigest() == old['pointSequenceSha256'], (period,'ordinary point ledger changed')
        cuts = {1,25,1000,len(bars)//2,len(bars)-1,len(bars)}
        times = [b.time for b in bars]
        for h in bottom.values():
            if '2024-07-01' <= h['confirmedAt'][:10] <= '2024-09-04':
                cuts.update(times.index(stamp)+1 for stamp in (h['confirmedAt'],h['leftOriginAt'],h['endedAt']) if stamp)
        cuts = sorted(n for n in cuts if 0<n<=len(bars))
        for n in cuts:
            prefix, part = replay(period, bars[:n]); assert part == steps[:n]
            observed = {h['id']:h for step in part for h in step.bottom_histories}
            projected = {key: q.IndexDetailXxmQueryService._project_bottom_history(h, through=times[n-1], times=times)
                         for key,h in bottom.items() if h['confirmedAt'] <= times[n-1]}
            assert observed == projected
            restored = new(period); restored.restore(prefix.snapshot())
            assert [restored.step(b) for b in bars[n:n+250]] == steps[n:n+250]
        frozen_forecasts = json.loads((B1 / f'forecast_{period}.json').read_text())
        wanted = {item['rows'] for item in frozen_forecasts}
        checkpoints, snapshots, confirmation = {}, {}, {}
        calc = new(period); last = None
        for n, b in enumerate(bars, 1):
            step = calc.step(b)
            last = next((e for e in reversed(step.events) if e['type']=='STRUCTURE'), last)
            if n%1000 == 0: checkpoints[n] = calc.snapshot()
            if n in wanted: snapshots[n] = calc.snapshot(); confirmation[n] = last
        model_results = []
        for item in frozen_forecasts:
            n = item['rows']; start = time.perf_counter()
            def check():
                if time.perf_counter()-start > .2: raise TimeoutError('200ms frozen model')
            child = new(period); offset=n//1000*1000
            if offset: child.restore(checkpoints[offset])
            for b in bars[offset:n]: child.step(b)
            assert child.snapshot() == snapshots[n]
            result = forecast_result(period, bars[:n], child, confirmation[n], calendar, check)
            assert result == item['result'], (period, item['through'])
            model_results.append(dict(through=item['through'], milliseconds=(time.perf_counter()-start)*1000, result=result))
        save(out, f'replay_{period}.json', dict(events=events,bottomHistories=list(bottom.values())))
        save(out, f'forecast_{period}.json', model_results)
        summary['periods'][period] = dict(rows=len(bars), ordinaryAndTopUnchanged=True, newBottomEvents=len(additions),
            bottomRecords=len(bottom), prefixRestoreCuts=len(cuts), forecasts=len(model_results),
            maxModelMs=max(r['milliseconds'] for r in model_results),
            calibrationProtected=sum(r['result']['reasonCode']=='CALIBRATION_FAILED' for r in model_results),
            seconds=time.perf_counter()-started)
        save(out,'frozen_summary.json',summary); print(period, json.dumps(summary['periods'][period]),flush=True)
    assert sum(r['newBottomEvents'] for r in summary['periods'].values()) == 95
    assert sum(r['prefixRestoreCuts'] for r in summary['periods'].values()) == 75
    assert sum(r['forecasts'] for r in summary['periods'].values()) == 356
    return summary


def app_for(session_dependency, lake, auth):
    from fastapi import FastAPI
    from src.app.exceptions import WebAppError, install_exception_handlers
    from src.biz.api.wealth.market.index_detail_xxm import build_router
    from src.biz.api.wealth.market.index_detail_minute_xxm import build_router as minutes
    from src.biz.api.wealth.market.index_detail_xxm_forecast import build_router as forecasts
    app = FastAPI(); install_exception_handlers(app)
    common = dict(db_dependency=session_dependency,auth_dependency=auth,error_factory=WebAppError)
    app.include_router(build_router(**common),prefix='/api/v1')
    app.include_router(minutes(**common,lake_dependency=lambda:lake),prefix='/api/v1')
    app.include_router(forecasts(**common,lake_dependency=lambda:lake),prefix='/api/v1')
    return app


def recognition(client, period, through=None):
    path = '/api/v1/wealth/market/index-detail/' + ('xxm-signals' if period=='day' else 'minute-xxm-signals')
    params = dict(tsCode='000001.SH',limit=2000)
    if period!='day': params['freq']=int(period[1:])
    if through: params['endDate']=through[:10]
    return client.get(path,params=params)


def prediction(client, period, through=None):
    params = dict(tsCode='000001.SH',period=period)
    if through: params['asOf']=through
    return client.get('/api/v1/wealth/market/index-detail/xxm-key-point-forecast',params=params)


def api_mode(source, out, sources):
    # Immutable frozen field fixture. The real source conversion/continuity,
    # queries, calculators, route parsers and DTOs still execute. No formal I/O.
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from src.app.exceptions import WebAppError
    class FrozenReader:
        def history_source_signature(self, request, **kwargs):
            return (request.freq,sha(source/'manifest.json'),kwargs['dataset'])
        def read_complete_history_pair(self, request, **kwargs):
            bars, indicators = [], []
            for b in sources[f'm{request.freq}']:
                stamp = datetime.fromisoformat(b.time).replace(tzinfo=None)
                if stamp.date() > request.end_date: continue
                key = dict(ts_code='000001.SH',freq=request.freq,trade_date=stamp.date(),trade_time=stamp)
                bars.append(dict(**key,close=b.close))
                indicators.append(dict(**key,macd_dif=b.dif,macd_dea=b.dea,macd=b.hist))
            return SimpleNamespace(rows=bars),SimpleNamespace(rows=indicators)
    engine = create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def attach(connection, _): connection.execute("ATTACH DATABASE ':memory:' AS core_serving")
    with engine.begin() as c:
        c.execute(text('CREATE TABLE core_serving.index_factor_pro (ts_code TEXT,trade_date DATE,close FLOAT,macd_dif_bfq FLOAT,macd_dea_bfq FLOAT,macd_bfq FLOAT)'))
        c.execute(text('CREATE TABLE core_serving.trade_calendar (exchange TEXT,trade_date DATE,is_open BOOLEAN,pretrade_date DATE)'))
        c.execute(text("INSERT INTO core_serving.trade_calendar (exchange,trade_date,is_open) VALUES ('SSE',:day,:opened)"),
                  [dict(day=k,opened=v) for k,v in calendar_rows(source).items()])
        c.execute(text("INSERT INTO core_serving.index_factor_pro VALUES ('000001.SH',:day,:close,:dif,:dea,:hist)"),
                  [dict(day=b.time,close=b.close,dif=b.dif,dea=b.dea,hist=b.hist) for b in sources['day']])
    def session():
        with Session(engine) as s: yield s
    original = q.minute_reader
    q.minute_reader = lambda root: FrozenReader()
    q._CACHE = q.XxmCache()
    results = []
    try:
        client = TestClient(app_for(session, out, lambda:None))
        cases = [('day','2024-07-23'),('day','2024-08-05'),('day','2024-08-22'),
                 ('m120','2024-08-05T15:00:00+08:00'),('m120','2024-08-14T15:00:00+08:00')]
        cases += [(p,sources[p][-1].time) for p in PERIODS]
        for i,(period,through) in enumerate(cases):
            response=recognition(client,period,through)
            assert response.status_code==200,(period,response.text)
            value=response.json(); assert value['algorithmVersion']==MAIN_SPEC.algorithm_version and value['specHash']==MAIN_SPEC.spec_hash
            assert 'bottomHistories' in value and all('pendingBottomHistoryId' in p for p in value['points'])
            assert all('relatedBottomHistoryId' in e for e in value['events'])
            if i<5:
                assert any(e['time']==through and e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL' for e in value['events'])
            save(out,f'api_{i}_{period}.json',value)
            predicted=prediction(client,period,through); assert predicted.status_code==200,predicted.text
            value=predicted.json(); assert value['detectorSpecHash']==MAIN_SPEC.spec_hash
            assert value['forecastVersion']=='xxm-key-point-forecast-v0.2'
            save(out,f'api_forecast_{i}_{period}.json',value)
            results.append(dict(period=period,through=through,recognitionStatus=200,forecastStatus=200))
        for status in (401,403):
            def denied(): raise WebAppError(status_code=status,code='AUTH_REQUIRED',message='denied')
            blocked=TestClient(app_for(session,out,denied))
            assert all(recognition(blocked,p).status_code==status and prediction(blocked,p).status_code==status for p in PERIODS)
    finally:
        q.minute_reader=original; engine.dispose()
    return dict(fixtureOnly=True,formalProtectedService=False,frozenFieldFixture=True,results=results,negativeAuth=[401,403])


@contextmanager
def readonly_session():
    from sqlalchemy import text
    from src.app.dependencies import get_db_session
    generator=get_db_session()
    try:
        session=next(generator); session.execute(text('SET TRANSACTION READ ONLY')); yield session
    finally: generator.close()


def budget_mode(source, out, sources):
    from fastapi.testclient import TestClient
    from src.app.auth.dependencies import require_quote_access
    from src.foundation.clients.local_lake.major_index_mins_contract import FORMAL_LAKE_ROOT
    from src.foundation.config.settings import get_settings
    from src.app.web.settings import get_web_settings
    from sqlalchemy.engine import make_url
    # Metadata is deliberately projected; never serialize a connection URL.
    url=make_url(get_settings().database_url)
    metadata=dict(readonly=True,formalLakeRoot=str(FORMAL_LAKE_ROOT),configuredDatabase=dict(host=url.host,port=url.port,database=url.database),
                  quoteAuthRequired=get_web_settings().quote_api_auth_required,
                  applicationCold='new series/forecast cache; OS and DB buffers retained', sourceOverlap={},requests=[])
    def session():
        with readonly_session() as s: yield s
    client=TestClient(app_for(session,FORMAL_LAKE_ROOT,require_quote_access))
    original_calendar, original_build=fq.future_calendar,fq.IndexDetailXxmForecastQueryService.build
    model_start=[None]; model_duration=[0.]
    def calendar(*a,**kw):
        value=original_calendar(*a,**kw); model_start[0]=time.perf_counter(); return value
    def build(self,*a,**kw):
        model_start[0]=None
        try: return original_build(self,*a,**kw)
        finally: model_duration[0]=time.perf_counter()-model_start[0] if model_start[0] else 0.
    fq.future_calendar=calendar; fq.IndexDetailXxmForecastQueryService.build=build
    try:
        # Compare every frozen overlap value; later appended bars are allowed.
        for period in PERIODS:
            q._CACHE=q.XxmCache()
            with readonly_session() as s:
                service=q.IndexDetailXxmQueryService(lake_root=FORMAL_LAKE_ROOT)
                with service.load_entry(s,period=period) as (entry,context,dates,check):
                    actual={b.time:b for b in entry.processed}
                    differences=[b.time for b in sources[period] if actual.get(b.time)!=b]
                    metadata['sourceOverlap'][period]=dict(rows=len(entry.processed),through=entry.processed[-1].time,
                        inputId=entry.fingerprints[-1],frozenOverlapRows=len(sources[period]),differences=differences)
                    save(out,'budget_records.json',metadata)
                    assert not differences,(period,'frozen source overlap revised')
        for period in PERIODS:
            through=sources[period][-1].time
            for kind in ('cold','warm'):
                if kind=='warm': q._CACHE=q.XxmCache()
                for iteration in range(1,21):
                    if kind=='cold': q._CACHE=q.XxmCache()
                    # Forecast goes first: its cold read, full detector and model
                    # must fit the existing deadline. Recognition then validates
                    # the maximum-2000 strict DTO on the same source/cache.
                    start=time.perf_counter(); response=prediction(client,period,through); elapsed=time.perf_counter()-start
                    row=dict(period=period,kind=kind,iteration=iteration,httpStatus=response.status_code,
                             httpSeconds=elapsed,modelEnvelopeSeconds=model_duration[0])
                    metadata['requests'].append(row)
                    save(out,'budget_records.json',metadata)
                    assert response.status_code==200,(period,kind,iteration,response.status_code)
                    payload=response.json(); assert payload['detectorSpecHash']==MAIN_SPEC.spec_hash
                    assert elapsed<=4 and model_duration[0]<=.2,(period,kind,iteration,'budget')
                    start=time.perf_counter(); response=recognition(client,period,through); rtime=time.perf_counter()-start
                    row.update(recognitionHttpStatus=response.status_code,recognitionHttpSeconds=rtime,recognitionBytes=len(response.content),
                               forecastBytes=len(json.dumps(payload,ensure_ascii=False).encode()),
                               cacheBytes=sum(size for _,size in q._CACHE.entries.values()),cacheEntries=len(q._CACHE.entries))
                    save(out,'budget_records.json',metadata)
                    assert response.status_code==200 and rtime<=4 and len(response.content)<=1048576
                    assert row['forecastBytes']<=32768 and row['cacheBytes']<=64*1024*1024 and row['cacheEntries']<=16
                    if iteration in (1,10,20): print(json.dumps(row),flush=True)
        metadata['latest']=[]
        for period in PERIODS:
            start=time.perf_counter(); response=prediction(client,period); elapsed=time.perf_counter()-start
            value=response.json()
            row=dict(period=period,httpStatus=response.status_code,httpSeconds=elapsed,
                     dataStatus=value.get('dataStatus'),computedThrough=value.get('computedThrough'))
            metadata['latest'].append(row); save(out,'budget_records.json',metadata)
            assert response.status_code==200 and elapsed<=4 and value['dataStatus']=='READY'
            save(out,f'latest_{period}.json',value)
    finally:
        fq.future_calendar=original_calendar; fq.IndexDetailXxmForecastQueryService.build=original_build
    metadata['passed']=True; save(out,'budget_records.json',metadata)
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',required=True,choices=('frozen','api','budget'))
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--formal-source',action='store_true')
    args=parser.parse_args()
    if args.formal_source != (args.mode=='budget'): parser.error('--formal-source is required only for budget mode')
    sources={period:load_source(args.source,period) for period in PERIODS}
    args.output.mkdir(parents=True,exist_ok=False)
    metadata=dict(mode=args.mode,source=str(args.source),sourceManifestSha256=sha(args.source/'manifest.json'),
                  algorithmVersion=MAIN_SPEC.algorithm_version,specHash=MAIN_SPEC.spec_hash,
                  startedAt=datetime.now(CN_ZONE).isoformat(),formalWrites=False)
    save(args.output,'run.json',metadata)
    try:
        handler={'frozen':frozen_mode,'api':api_mode,'budget':budget_mode}[args.mode]
        result=handler(args.source,args.output,sources)
        save(args.output,'result.json',result)
        metadata['passed']=True
    except Exception as exc:
        metadata.update(passed=False,failure=dict(type=type(exc).__name__,code=getattr(exc,'code',None)))
        # Do not print DB errors/connection details. Assertions use safe labels.
        if args.mode == 'budget':
            print(json.dumps(metadata['failure']), flush=True)
            raise SystemExit(1) from None
        raise
    finally:
        metadata['finishedAt']=datetime.now(CN_ZONE).isoformat();save(args.output,'run.json',metadata)


if __name__=='__main__': main()
