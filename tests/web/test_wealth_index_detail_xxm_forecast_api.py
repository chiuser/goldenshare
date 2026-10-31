"""P3/PF28: literal next-bar examples and actual isolated query/HTTP boundaries.

M1 supplies the documented EMA state; only calibration/input are substituted
in the M1 tests. Separate SQLite tests exercise real source loading. No frozen
market files, historical replay, formal database or Lake are used.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine,event,text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.exceptions import WebAppError, install_exception_handlers
from src.biz.api.wealth.market.index_detail_xxm_forecast import build_router
from src.biz.queries.wealth.market.index_detail_xxm import forecast_query_service as query
from src.biz.queries.wealth.market.index_detail_xxm.query_service import XxmCache, XxmQueryError
from src.biz.queries.wealth.market.index_detail_xxm.source import CN_ZONE
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import InternalForecastResponseDto, ForecastResponseDto, ForecastDebugResponseDto
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState,ProjectionPrecisionError
from scripts.research.index_market.tests.test_xxm_r4_following_query import entry

PATH='/api/v1/wealth/market/index-detail/xxm-key-point-forecast'
M1=[(100,-60,-2),(110,0,2),(90,-50,-2),(100,0,2),(89,-15,-30),(88,-14,-28)]
NOW=datetime(2023,1,10,20,tzinfo=CN_ZONE)


@pytest.fixture
def source_db():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def attach(c,_): c.execute("ATTACH DATABASE ':memory:' AS core_serving")
    with engine.begin() as c:
        c.execute(text('CREATE TABLE core_serving.trade_calendar(exchange TEXT,trade_date DATE,is_open BOOLEAN,pretrade_date DATE)'))
        c.execute(text('CREATE TABLE core_serving.index_factor_pro(ts_code TEXT,trade_date DATE,close FLOAT,macd_dif_bfq FLOAT,macd_dea_bfq FLOAT,macd_bfq FLOAT)'))
        begin=date(2023,1,3)
        end=max(begin+timedelta(days=120),datetime.now(CN_ZONE).date())
        days=[begin+timedelta(days=i) for i in range((end-begin).days+1)]
        c.execute(text("INSERT INTO core_serving.trade_calendar(exchange,trade_date,is_open) VALUES('SSE',:day,:opened)"),
                  [dict(day=d.isoformat(),opened=d.weekday()<5) for d in days])
        c.execute(text("INSERT INTO core_serving.index_factor_pro VALUES('000001.SH',:day,100,0,0,0)"),
                  [dict(day=d.isoformat()) for d in days if d<=NOW.date() and d.weekday()<5])
    yield engine
    engine.dispose()


def api(engine,denied=None):
    app=FastAPI();install_exception_handlers(app)
    def session():
        with Session(engine) as s: yield s
    app.include_router(build_router(db_dependency=session,auth_dependency=denied or (lambda:None),
        lake_dependency=lambda:None,error_factory=WebAppError),prefix='/api/v1')
    return TestClient(app)


@pytest.fixture
def m1(monkeypatch,source_db):
    service=query.IndexDetailXxmForecastQueryService(cache=XxmCache())
    state=entry(M1)
    @contextmanager
    def load(*a,**kw):
        yield state,SimpleNamespace(trade_date=NOW.date(),generated_at=NOW),(NOW.date(),),lambda:4.
    service.source.load_entry=load
    monkeypatch.setattr(query,'recover_projection',lambda *a:ProjectionState(13,27,0))
    return service,state


def read(service,session,**kwargs):
    return json.loads(service.build(session,period='day',now=NOW,**kwargs))


def test_full_m1_normal_debug_cache_and_exact_single_target(m1,source_db,monkeypatch):
    service,_=m1
    encoded=[];encode_original=ForecastResponseDto.model_dump_json
    def encode(value,*a,**k):
        body=encode_original(value,*a,**k);encoded.append(body.encode());return body
    monkeypatch.setattr(ForecastResponseDto,'model_dump_json',encode)
    calls=[];original=query.forecast
    monkeypatch.setattr(query,'forecast',lambda *a,**k:(calls.append(1),original(*a,**k))[1])
    with Session(source_db) as s:
        normal=read(service,s);debug=read(service,s,debug=True)
        assert normal=={k:v for k,v in debug.items() if k!='debug'}
        assert normal['status']=='READY' and normal['targetEndpoint']=='2023-01-11' and normal['barsAhead']==1
        assert normal['ordinaryState']=='DULL' and normal['direction']=='BOTTOM'
        assert '结构' in normal['display']['conditionsText']
        assert calls==[1] and len(encoded)==2
        assert json.loads(encoded[0])==normal and json.loads(encoded[1])==debug
        assert debug['debug']['selectedReference']=='NEAR' and not debug['debug']['farEvaluated']
        assert 'sourceInputId' not in normal
        stored=next(v[0] for k,v in service.source.cache.entries.items() if k[0]=='forecast')
        assert isinstance(stored,InternalForecastResponseDto)
        debug['display']['conditionsText']='changed caller copy'
        assert read(service,s)['display']==normal['display']
        replay=read(service,s,as_of='2023-01-10')
        assert replay['mode']=='REPLAY' and replay['forecastId']!=normal['forecastId']


def test_generated_ids_and_fields_are_required_and_no_legacy_contract(m1,source_db):
    service,_=m1
    with Session(source_db) as s: value=read(service,s,debug=True)
    assert ForecastDebugResponseDto.model_validate(value)
    changes=[lambda v:v.update(confirmedAt=None),lambda v:v.update(forecastSpecHash='old'),
        lambda v:v.update(barsAhead=2),lambda v:v['debug']['conditions'][0].pop('id'),
        lambda v:v['debug'].update(farEvaluated=True),lambda v:v['debug']['conditions'][0].update(referenceRole='FAR'),
        lambda v:v['debug']['references']['nearest'].update(priceAt='2099-01-01'),
        lambda v:v['debug']['conditions'][0]['priceRanges'][0].update(displayLower=True),
        lambda v:v['debug']['conditions'][0]['priceRanges'][0].update(lower=float('nan')),
        lambda v:(v.update(status='PRECISION_PENDING',reasonCode='ROUNDING_BOUNDARY'),v['debug'].update(precisionRanges=[dict(priceRange=dict(lower=1,upper=1,lowerInclusive=True,upperInclusive=True),reason='ROUNDING_BOUNDARY')]))]
    for mutate in changes:
        bad=deepcopy(value);mutate(bad)
        with pytest.raises(ValueError): ForecastDebugResponseDto.model_validate(bad)
    with pytest.raises(ValueError): ForecastResponseDto.model_validate(value)


@pytest.mark.parametrize('raw',['','true','01','2','1&debug=0'])
def test_invalid_debug_early_failure(source_db,monkeypatch,raw):
    monkeypatch.setattr(query.IndexDetailXxmForecastQueryService,'build',lambda *a,**k:pytest.fail('invalid read'))
    assert api(source_db).get(PATH+'?tsCode=000001.SH&period=day&debug='+raw).status_code==400


@pytest.mark.parametrize('query_string,status',[
    ('period=day',400),('tsCode=bad&period=day',400),('tsCode=399001.SZ&period=day',404),
    ('tsCode=000001.SH&period=m30',400),('tsCode=000001.SH&period=day&period=day',400),
    ('tsCode=000001.sh&period=day',400),('tsCode=%20000001.SH&period=day',400),
    ('tsCode=000001.SH&period=m90&asOf=2023-01-10T11:30:00%2B08:00',400),
    ('tsCode=000001.SH&period=m60',404)])
def test_original_request_semantics(source_db,query_string,status):
    response=api(source_db).get(PATH+'?'+query_string)
    assert response.status_code==status
    assert response.json()['code'].startswith('XXMF_')


@pytest.mark.parametrize('status',[401,403])
def test_auth_before_source(source_db,status):
    def denied(): raise WebAppError(status_code=status,code='AUTH_REQUIRED',message='denied')
    assert api(source_db,denied).get(PATH+'?tsCode=000001.SH&period=day').status_code==status


def test_real_route_source_empty_static_and_delayed_no_fake_conditions(source_db):
    c=api(source_db)
    r=c.get(PATH+'?tsCode=000001.SH&period=day&asOf=2023-01-10&debug=1')
    assert r.status_code==200,r.text
    v=r.json()
    assert v['status']=='NO_CANDIDATE' and v['reasonCode']=='ZERO_WAVE'
    assert v['targetEndpoint'] is None and v['debug']['conditions']==[]
    assert r.headers['cache-control']=='no-store'
    with Session(source_db) as s:
        service=query.IndexDetailXxmForecastQueryService(cache=XxmCache())
        empty=read(service,s,as_of='2023-01-03')
        assert empty['status']=='NO_CANDIDATE'
        delayed=json.loads(service.build(s,period='day',now=datetime(2023,1,11,20,tzinfo=CN_ZONE)))
        assert delayed['status']=='DELAYED' and delayed['targetEndpoint'] is None
    with source_db.begin() as c: c.execute(text('DELETE FROM core_serving.index_factor_pro'))
    r=api(source_db).get(PATH+'?tsCode=000001.SH&period=day&debug=1')
    assert r.status_code==200 and r.json()['status']=='EMPTY'
    assert r.json()['ordinaryState'] is None and r.json()['debug']['sourceInputId'] is None


def test_calibration_failure_does_not_read_future_calendar_or_cache(m1,source_db,monkeypatch):
    service,_=m1
    def fail(*args): raise ProjectionPrecisionError('CALIBRATION_FAILED')
    monkeypatch.setattr(query,'recover_projection',fail)
    monkeypatch.setattr(query,'future_calendar',lambda *a:pytest.fail('must not read calendar'))
    with Session(source_db) as s: value=read(service,s,debug=True)
    assert value['status']=='PRECISION_PENDING' and value['targetEndpoint'] is None
    assert not service.source.cache.entries


def test_with_exit_failure_never_publishes_forecast(m1,source_db):
    service,_=m1;original=service.source.load_entry
    @contextmanager
    def failing(*a,**kw):
        with original(*a,**kw) as loaded: yield loaded
        raise XxmQueryError('XXM_BUDGET_EXCEEDED','exit check',503)
    service.source.load_entry=failing
    with Session(source_db) as s,pytest.raises(XxmQueryError,match='exit check'):read(service,s)
    assert not service.source.cache.entries


def test_final_encoding_and_copy_share_original_budget(m1,source_db,monkeypatch):
    service,_=m1;clock=[0.]
    monkeypatch.setattr(query.time,'perf_counter',lambda:clock[0])
    def slow_size(value):clock[0]=.401;return 100
    monkeypatch.setattr(query,'_deep_size',slow_size)
    with Session(source_db) as s,pytest.raises(XxmQueryError) as error:read(service,s)
    assert error.value.status==503 and not service.source.cache.entries


def test_cache_publish_failure_is_atomic_and_normal_change_is_allowed():
    cache=XxmCache();old=object();cache.entries[('source',)]=(old,100)
    original=cache.entries
    def fail():raise TimeoutError('cancel before publish')
    with pytest.raises(TimeoutError):cache.put_forecast(('new',),object(),200,check=fail)
    checks=[]
    def fail_before_assignment():
        checks.append(1)
        if len(checks)==2:raise TimeoutError('cancel after candidate preparation')
        return 1.
    with pytest.raises(TimeoutError):cache.put_forecast(('new',),object(),200,check=fail_before_assignment)
    assert len(checks)==2 and cache.entries is original and cache.entries[('source',)][0] is old
    assert cache.entries is original and cache.entries[('source',)][0] is old
    with pytest.raises(XxmQueryError):cache.put_forecast(('new',),object(),cache.max_bytes+1,check=lambda:1.)
    assert cache.entries is original
    cache.put_forecast(('new',),object(),200,check=lambda:1.)
    assert ('forecast','new') in cache.entries and cache.entries[('source',)][0] is old


@pytest.mark.parametrize('period,through,target',[
    ('day','2023-01-13','2023-01-16'),
    ('m60','2023-01-10T10:30:00+08:00','2023-01-10T11:30:00+08:00'),
    ('m90','2023-01-10T11:00:00+08:00','2023-01-10T14:00:00+08:00'),
    ('m120','2023-01-13T15:00:00+08:00','2023-01-16T11:30:00+08:00')])
def test_single_calendar_endpoint_and_used_prefix_identity(source_db,period,through,target):
    with Session(source_db) as s:
        endpoint,identity=query.future_calendar(s,period,through,lambda:1.)
        assert endpoint==target and type(endpoint) is str
        s.execute(text("UPDATE core_serving.trade_calendar SET is_open=0 WHERE trade_date='2023-04-01'"))
        assert query.future_calendar(s,period,through,lambda:1.)==(endpoint,identity)
        s.rollback()


def test_future_calendar_gap_and_non_boolean_refused():
    class FakeSession:
        def __init__(self,rows): self.rows=rows
        def execute(self,*a):return SimpleNamespace(all=lambda:self.rows)
    for rows in ([(date(2023,1,10),True),(date(2023,1,12),True)],[(date(2023,1,10),1)]):
        with pytest.raises(XxmQueryError): query.future_calendar(FakeSession(rows),'day','2023-01-10',lambda:1.)


def test_actual_source_calibration_solver_models_and_encoding_share_budget(source_db):
    # Independently constructed closes: a sharp first decline and slower second
    # decline below 50. Indicators use the textbook EMA recurrence, never a
    # product projection/detector helper. Only temporary SQLite is written.
    closes=[100.]*250+[100,90,80,70,60,50,55,65,75,85,95,105]+list(range(100,49,-2))+[49,48]
    days=[];day=date(2023,1,3)
    while len(days)<len(closes):
        if day.weekday()<5:days.append(day)
        day+=timedelta(days=1)
    e12=e26=100.;dea=0.;rows=[]
    for day,close in zip(days,closes):
        e12=e12*(11/13)+close*(2/13);e26=e26*(25/27)+close*(2/27)
        dif=e12-e26;dea=dea*.8+dif*.2
        rows.append(dict(day=day.isoformat(),close=close,dif=round(dif,3),dea=round(dea,3),hist=round(2*(dif-dea),3)))
    assert rows[0]['dif']==0 and rows[-1]['close']==48
    with source_db.begin() as c:
        c.execute(text('DELETE FROM core_serving.index_factor_pro'))
        c.execute(text("INSERT INTO core_serving.index_factor_pro VALUES('000001.SH',:day,:close,:dif,:dea,:hist)"),rows)
    now=datetime.combine(days[-1],datetime.min.time().replace(hour=20),CN_ZONE)
    with Session(source_db) as s,patch.object(query,'recover_projection',wraps=query.recover_projection) as calibration,patch.object(query,'forecast',wraps=query.forecast) as solve:
        service=query.IndexDetailXxmForecastQueryService(cache=XxmCache())
        start=time.perf_counter()
        body=service.build(s,period='day',now=now,debug=True)
        cold_ms=(time.perf_counter()-start)*1000
        value=json.loads(body)
        assert calibration.call_count==solve.call_count==1
        start=time.perf_counter()
        normal=json.loads(service.build(s,period='day',now=now))
        warm_ms=(time.perf_counter()-start)*1000
        assert calibration.call_count==2 and solve.call_count==1
        assert {k:v for k,v in value.items() if k!='debug'}==normal
        print(f'P3 isolated {len(rows)} bars: cold={cold_ms:.2f}ms warm={warm_ms:.2f}ms debug={len(body)}bytes')
        assert value['dataStatus']=='READY' and value['status']=='READY'
        assert value['computedThrough']==days[-1].isoformat() and value['barsAhead']==1
        assert value['debug']['conditions'] and value['debug']['selectedReference']=='NEAR'
        assert len(json.dumps(value).encode())<=32768


@pytest.mark.parametrize("fault",["numeric","result_id","condition_id"])
def test_bad_cached_full_model_is_refused_without_solving_again(m1,source_db,monkeypatch,fault):
    service,_=m1
    with Session(source_db) as s:
        read(service,s)
        cached=next(v[0] for k,v in service.source.cache.entries.items() if k[0]=='forecast')
        if fault=='numeric':cached.references.nearest.price=float('nan')
        elif fault=='result_id':cached.forecastId='f'*64
        else:cached.conditions[0].id='f'*64
        monkeypatch.setattr(query,'forecast',lambda *a,**k:pytest.fail('invalid cache was silently solved again'))
        with pytest.raises(XxmQueryError) as error:read(service,s,debug=True)
        assert error.value.code=='XXM_SOURCE_CONTRACT_INVALID'


def test_final_json_encoding_cannot_exceed_original_budget_or_publish(m1,source_db,monkeypatch):
    service,_=m1;clock=[0.]
    monkeypatch.setattr(query.time,'perf_counter',lambda:clock[0])
    original=ForecastResponseDto.model_dump_json
    def slow_encode(value,*a,**k):
        body=original(value,*a,**k);clock[0]=.401;return body
    monkeypatch.setattr(ForecastResponseDto,'model_dump_json',slow_encode)
    with Session(source_db) as s,pytest.raises(XxmQueryError) as error:read(service,s)
    assert error.value.status==503 and not service.source.cache.entries


@pytest.mark.parametrize('phase',['inside','exit','publish'])
def test_f06_unexpected_failure_returns_forecast_error_and_keeps_old_cache(m1,source_db,monkeypatch,phase):
    from src.biz.api.wealth.market import index_detail_xxm_forecast as route
    service,_=m1
    with Session(source_db) as session:read(service,session)
    old=dict(service.source.cache.entries)
    failure=RuntimeError('private injected cache detail')
    def fail(*a,**kw):raise failure
    if phase=='publish':monkeypatch.setattr(service.source.cache,'put_forecast',fail)
    elif phase=='inside':monkeypatch.setattr(query,'forecast',fail)
    else:
        original=service.source.load_entry
        @contextmanager
        def failing(*a,**kw):
            with original(*a,**kw) as value:yield value
            raise failure
        monkeypatch.setattr(service.source,'load_entry',failing)
    monkeypatch.setattr(route,'IndexDetailXxmForecastQueryService',lambda **kw:service)
    response=api(source_db).get(PATH,params=dict(tsCode='000001.SH',period='day',asOf='2023-01-10'))
    assert response.status_code==500 and response.json()['code']=='XXMF_QUERY_FAILED'
    assert response.json()['message']=='下一根预判查询失败，请重试。'
    assert 'private' not in response.text
    assert set(service.source.cache.entries)==set(old)
    assert all(service.source.cache.entries[k][0] is old[k][0] for k in old)


@pytest.mark.parametrize('kind',['timeout','async_cancel','future_cancel','known'])
def test_f07_final_publication_preserves_known_timeout_and_cancel_errors(m1,source_db,monkeypatch,kind):
    from asyncio import CancelledError as AsyncCancelled
    from concurrent.futures import CancelledError as FutureCancelled
    service,_=m1
    with Session(source_db) as session:read(service,session)
    old=dict(service.source.cache.entries)
    failure={'timeout':TimeoutError('timeout'), 'async_cancel':AsyncCancelled('cancel'),
             'future_cancel':FutureCancelled('cancel'),
             'known':XxmQueryError('XXM_REQUEST_INVALID','原请求错误',400)}[kind]
    def fail(*a,**kw):raise failure
    monkeypatch.setattr(service.source.cache,'put_forecast',fail)
    with Session(source_db) as session,pytest.raises(type(failure) if kind in ('async_cancel','future_cancel','known') else XxmQueryError) as error:
        read(service,session,as_of='2023-01-10')
    if kind in ('async_cancel','future_cancel','known'):assert error.value is failure
    else:assert error.value.code=='XXM_BUDGET_EXCEEDED' and error.value.status==503
    assert set(service.source.cache.entries)==set(old)
    assert all(service.source.cache.entries[k][0] is old[k][0] for k in old)


def test_f06_actual_cache_candidate_failure_releases_lock_and_keeps_members(m1,source_db,monkeypatch):
    from collections import OrderedDict
    from concurrent.futures import ThreadPoolExecutor
    service,_=m1
    with Session(source_db) as session:read(service,session)
    class BrokenCandidate(OrderedDict):
        def copy(self):raise RuntimeError('candidate allocation failed')
    service.source.cache.entries=BrokenCandidate(service.source.cache.entries)
    old=service.source.cache.entries
    with Session(source_db) as session,pytest.raises(XxmQueryError) as error:read(service,session,as_of='2023-01-10')
    assert error.value.code=='XXM_QUERY_FAILED' and isinstance(error.value.__cause__,RuntimeError)
    assert service.source.cache.entries is old
    def can_lock():
        acquired=service.source.cache.lock.acquire(timeout=.5)
        if acquired:service.source.cache.lock.release()
        return acquired
    with ThreadPoolExecutor(max_workers=1) as worker:assert worker.submit(can_lock).result(timeout=1)


@pytest.mark.parametrize('failure_kind',['query','source','async_cancel','future_cancel'])
def test_f07_real_load_exit_does_not_replace_original_error_with_a_later_timeout(source_db,monkeypatch,failure_kind):
    from asyncio import CancelledError as AsyncCancelled
    from concurrent.futures import CancelledError as FutureCancelled
    cache=XxmCache();service=query.IndexDetailXxmQueryService(cache=cache);clock=[0.]
    monkeypatch.setattr(query.time,'perf_counter',lambda:clock[0])
    failure={'query':RuntimeError('original failure'),'source':ValueError('original source gap'),
             'async_cancel':AsyncCancelled('cancel'),'future_cancel':FutureCancelled('cancel')}[failure_kind]
    expected=type(failure) if 'cancel' in failure_kind else XxmQueryError
    with Session(source_db) as session,pytest.raises(expected) as error:
        with service.load_entry(session,period='day',now=NOW):
            clock[0]=4.001
            raise failure
    if 'cancel' in failure_kind:assert error.value is failure
    else:
        assert error.value.code==('XXM_QUERY_FAILED' if failure_kind=='query' else 'XXM_SOURCE_CONTRACT_INVALID')
        assert error.value.__cause__ is failure
    assert not cache.loads._pending
    # A normal request after rejection still obtains the released resources.
    clock[0]=0
    with Session(source_db) as session:
        with service.load_entry(session,period='day',now=NOW) as value:
            assert value[0].processed


@pytest.mark.parametrize('kind',['async_cancel','future_cancel'])
def test_f07_cancellation_inside_cache_lock_is_atomic_and_unlocks(m1,source_db,kind):
    from asyncio import CancelledError as AsyncCancelled
    from concurrent.futures import CancelledError as FutureCancelled,ThreadPoolExecutor
    service,_=m1
    with Session(source_db) as session:read(service,session)
    cache=service.source.cache;old=cache.entries;checks=[]
    prepared=next(v[0] for k,v in old.items() if k[0]=='forecast').model_copy(deep=True)
    failure=AsyncCancelled('cancel while locked') if kind=='async_cancel' else FutureCancelled('cancel while locked')
    def check():
        checks.append(1)
        if len(checks)==2:raise failure
        return 1.
    with pytest.raises(type(failure)) as error:cache.put_forecast(('new identity',),prepared,100,check=check)
    assert error.value is failure and len(checks)==2 and cache.entries is old
    def can_lock():
        acquired=cache.lock.acquire(timeout=.5)
        if acquired:cache.lock.release()
        return acquired
    with ThreadPoolExecutor(max_workers=1) as worker:assert worker.submit(can_lock).result(timeout=1)
    cache.put_forecast(('new identity',),prepared,100,check=lambda:1.)
    assert ('forecast','new identity') in cache.entries
