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
from src.biz.queries.wealth.market.index_detail_xxm import source as source_data
from src.biz.queries.wealth.market.index_detail_xxm.query_service import XxmCache, XxmQueryError
from src.biz.queries.wealth.market.index_detail_xxm.source import CN_ZONE
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import InternalForecastResponseDto, ForecastResponseDto, ForecastDebugResponseDto
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState,ProjectionPrecisionError
from scripts.research.index_market.tests.test_xxm_r4_following_query import entry
from tests.web.test_wealth_index_detail_xxm_api import (  # shared temporary producers, no source replacement
    batch3_db_factory, _batch3_gold, BATCH3_NOW, BATCH3_SLOTS, _source_clock,
)

PATH='/api/v1/wealth/market/index-detail/xxm-key-point-forecast'
M1=[(100,-60,-2),(110,0,2),(90,-50,-2),(100,0,2),(89,-15,-30),(88,-14,-28)]
NOW=datetime(2023,1,10,20,tzinfo=CN_ZONE)


@pytest.fixture
def source_db(monkeypatch):
    _source_clock(monkeypatch, NOW)
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def attach(c,_): c.execute("ATTACH DATABASE ':memory:' AS core_serving")
    with engine.begin() as c:
        c.execute(text('CREATE TABLE core_serving.trade_calendar(exchange TEXT,trade_date DATE,is_open BOOLEAN,pretrade_date DATE)'))
        c.execute(text('CREATE TABLE core_serving.index_factor_pro(ts_code TEXT,trade_date DATE,close FLOAT,macd_dif_bfq FLOAT,macd_dea_bfq FLOAT,macd_bfq FLOAT)'))
        begin=date(2023,1,3)
        # Literal NOW/asOf requests and their next trading days stay in January.
        end=date(2023,1,31)
        days=[begin+timedelta(days=i) for i in range((end-begin).days+1)]
        c.execute(text("INSERT INTO core_serving.trade_calendar(exchange,trade_date,is_open) VALUES('SSE',:day,:opened)"),
                  [dict(day=d.isoformat(),opened=d.weekday()<5) for d in days])
        c.execute(text("INSERT INTO core_serving.index_factor_pro VALUES('000001.SH',:day,100,0,0,0)"),
                  [dict(day=d.isoformat()) for d in days if d<=NOW.date() and d.weekday()<5])
    yield engine
    engine.dispose()


def api(engine,denied=None,*,lake_root=None):
    app=FastAPI();install_exception_handlers(app)
    def session():
        with Session(engine) as s: yield s
    app.include_router(build_router(db_dependency=session,auth_dependency=denied or (lambda:None),
        lake_dependency=lambda:lake_root,error_factory=WebAppError),prefix='/api/v1')
    return TestClient(app)


@pytest.fixture
def m1(monkeypatch,source_db):
    service=query.IndexDetailXxmForecastQueryService(cache=XxmCache())
    state=entry(M1)
    @contextmanager
    def load(session,*,ts_code,period,now=None,window_rows=None,requested_end=None):
        assert ts_code==state.calculator.ts_code and period==state.calculator.period
        yield state,SimpleNamespace(trade_date=NOW.date(),generated_at=NOW),(NOW.date(),),lambda:4.
    service.source.load_entry=load
    monkeypatch.setattr(query,'recover_projection',lambda *a:ProjectionState(13,27,0))
    return service,state


def read(service,session,*,ts_code='000001.SH',**kwargs):
    return json.loads(service.build(session,ts_code=ts_code,period='day',now=NOW,**kwargs))


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
    ('period=day',400),('tsCode=bad&period=day',400),('tsCode=000680.SH&period=day',404),
    ('tsCode=000001.SH&period=m15',400),('tsCode=000001.SH&period=day&period=day',400),
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
        delayed=json.loads(service.build(s,ts_code='000001.SH',period='day',now=datetime(2023,1,11,20,tzinfo=CN_ZONE)))
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
    def failing(session,*,ts_code,period,now=None,window_rows=None,requested_end=None):
        with original(session,ts_code=ts_code,period=period,now=now,
                      window_rows=window_rows,requested_end=requested_end) as loaded: yield loaded
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
    ('m30','2023-01-10T11:30:00+08:00','2023-01-10T13:30:00+08:00'),
    ('m30','2023-01-13T15:00:00+08:00','2023-01-16T10:00:00+08:00'),
    ('m60','2023-01-10T10:30:00+08:00','2023-01-10T11:30:00+08:00'),
    ('m90','2023-01-10T11:00:00+08:00','2023-01-10T14:00:00+08:00'),
    ('m120','2023-01-13T15:00:00+08:00','2023-01-16T11:30:00+08:00')])
def test_single_calendar_endpoint_and_used_prefix_identity(source_db,period,through,target):
    with Session(source_db) as s:
        endpoint,identity=query.future_calendar(s,period,through,lambda:1.)
        assert endpoint==target and type(endpoint) is str
        changed=s.execute(text("UPDATE core_serving.trade_calendar SET is_open=0 WHERE trade_date='2023-01-31' AND is_open=1"))
        assert changed.rowcount==1  # A real later-calendar change, beyond every target above.
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
        # Only this calibration example needs its long prefix and next open day.
        next_day=days[-1]+timedelta(days=1)
        while next_day.weekday()>=5:
            next_day+=timedelta(days=1)
        begin=date(2023,2,1)
        calendar=[begin+timedelta(days=i) for i in range((next_day-begin).days+1)]
        c.execute(text("INSERT INTO core_serving.trade_calendar(exchange,trade_date,is_open) VALUES('SSE',:day,:opened)"),
                  [dict(day=d.isoformat(),opened=d.weekday()<5) for d in calendar])
    now=datetime.combine(days[-1],datetime.min.time().replace(hour=20),CN_ZONE)
    with Session(source_db) as s,patch.object(query,'recover_projection',wraps=query.recover_projection) as calibration,patch.object(query,'forecast',wraps=query.forecast) as solve:
        service=query.IndexDetailXxmForecastQueryService(cache=XxmCache())
        start=time.perf_counter()
        body=service.build(s,ts_code='000001.SH',period='day',now=now,debug=True)
        cold_ms=(time.perf_counter()-start)*1000
        value=json.loads(body)
        assert calibration.call_count==solve.call_count==1
        start=time.perf_counter()
        normal=json.loads(service.build(s,ts_code='000001.SH',period='day',now=now))
        warm_ms=(time.perf_counter()-start)*1000
        assert calibration.call_count==2 and solve.call_count==1
        assert {k:v for k,v in value.items() if k!='debug'}==normal
        print(f'P3 isolated {len(rows)} bars: cold={cold_ms:.2f}ms warm={warm_ms:.2f}ms debug={len(body)}bytes')
        assert value['dataStatus']=='READY' and value['status']=='READY'
        assert value['computedThrough']==days[-1].isoformat() and value['barsAhead']==1
        assert value['debug']['conditions'] and value['debug']['selectedReference']=='NEAR'
        assert len(json.dumps(value).encode())<=32768


@pytest.mark.parametrize("fault",["numeric","result_id","condition_id"])
@pytest.mark.parametrize('debug', [False, True])
def test_bad_cached_full_model_is_refused_without_solving_again(m1,source_db,monkeypatch,fault,debug):
    service,_=m1
    with Session(source_db) as s:
        read(service,s)
        cached=next(v[0] for k,v in service.source.cache.entries.items() if k[0]=='forecast')
        if fault=='numeric':cached.references.nearest.price=float('nan')
        elif fault=='result_id':cached.forecastId='f'*64
        else:cached.conditions[0].id='f'*64
        old_members = dict(service.source.cache.entries)
        monkeypatch.setattr(query,'forecast',lambda *a,**k:pytest.fail('invalid cache was silently solved again'))
        monkeypatch.setattr(query,'project_forecast_response',lambda *a,**k:pytest.fail('invalid cache reached projection'))
        monkeypatch.setattr(service.source.cache,'put_forecast',lambda *a,**k:pytest.fail('invalid cache was republished'))
        with pytest.raises(XxmQueryError) as error:read(service,s,debug=debug)
        assert error.value.code=='XXM_SOURCE_CONTRACT_INVALID'
        assert set(service.source.cache.entries) == set(old_members)
        assert all(service.source.cache.entries[k][0] is old_members[k][0] and service.source.cache.entries[k][1] == old_members[k][1] for k in old_members)


@pytest.mark.parametrize('debug', [False, True])
def test_p4_batch1_actual_forecast_cache_hit_validates_once(m1, source_db, monkeypatch, debug):
    service, _ = m1
    with Session(source_db) as session:
        first = read(service, session, debug=debug)
        before = [(k, v[0].model_dump(), v[1]) for k, v in service.source.cache.entries.items()]
        monkeypatch.setattr(query, 'forecast', lambda *a, **kw: pytest.fail('cache hit ran solver'))
        monkeypatch.setattr(service.source.cache, 'put_forecast', lambda *a, **kw: pytest.fail('cache hit was republished'))
        with patch.object(InternalForecastResponseDto, 'model_validate', wraps=InternalForecastResponseDto.model_validate) as validate:
            with patch.object(ForecastResponseDto, 'model_dump_json', autospec=True, side_effect=ForecastResponseDto.model_dump_json) as encode:
                second = read(service, session, debug=debug)
        assert validate.call_count == 1 and encode.call_count == 1
    assert second == first and second['targetEndpoint'] == '2023-01-11'
    assert [(k, v[0].model_dump(), v[1]) for k, v in service.source.cache.entries.items()] == before


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
        def failing(session,*,ts_code,period,now=None,window_rows=None,requested_end=None):
            with original(session,ts_code=ts_code,period=period,now=now,
                          window_rows=window_rows,requested_end=requested_end) as value:yield value
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
        with service.load_entry(session,ts_code='000001.SH',period='day',now=NOW):
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
        with service.load_entry(session,ts_code='000001.SH',period='day',now=NOW) as value:
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


@pytest.mark.parametrize('freq',[30,60,90,120])
def test_p4_bounded_early_open_asof_uses_range_calendar_and_empty(batch3_db_factory,tmp_path,monkeypatch,freq):
    from src.biz.queries.wealth.market.index_detail_xxm import source
    _batch3_gold(tmp_path,freq,[(f'2023-01-10T{slot}:00',100.,0.,0.,0.) for slot in BATCH3_SLOTS[freq]])
    engine=batch3_db_factory()
    service=query.IndexDetailXxmForecastQueryService(lake_root=tmp_path,cache=XxmCache())
    calls=[]
    original_open=source.is_open_date
    def opened(session,day):
        calls.append(day)
        return original_open(session,day)
    monkeypatch.setattr(source_data,'is_open_date',opened)
    for name in ('recover_projection','future_calendar','forecast'):
        monkeypatch.setattr(query,name,lambda *a,**k:pytest.fail('EMPTY must not forecast'))
    monkeypatch.setattr(service.source.cache,'get_forecast',lambda *a,**k:pytest.fail('EMPTY cache read'))
    monkeypatch.setattr(service.source.cache,'put_forecast',lambda *a,**k:pytest.fail('EMPTY cache publish'))
    with Session(engine) as session:
        result=json.loads(service.build(session,ts_code='000001.SH',period=f'm{freq}',as_of=f'2023-01-06T{BATCH3_SLOTS[freq][-1]}:00+08:00',debug=True,now=BATCH3_NOW))
    assert calls==[]  # The one range calendar already contains this day.
    assert result['status']=='EMPTY' and result['targetEndpoint'] is None
    assert result['debug']['sourceInputId'] is None and result['debug']['calendarInputId'] is None
    assert result['debug']['conditions']==[]


@pytest.mark.parametrize('day,opened',[(6,True),(7,False)])
def test_p4_batch3_single_day_real_sql_contract(batch3_db_factory,day,opened):
    from src.biz.queries.wealth.market.index_detail_xxm.source import is_open_date
    with Session(batch3_db_factory()) as session,patch.object(session,'execute',wraps=session.execute) as execute:
        assert is_open_date(session,date(2023,1,day)) is opened
        assert execute.call_count==1
        statement=execute.call_args.args[0]
        assert list(statement.selected_columns.keys())==['trade_date','is_open']
        assert list(statement.compile().params.values())==['SSE',date(2023,1,day)]


@pytest.mark.parametrize('kind',['absent','null','duplicate','wrong_day','wrong_bool','other_exchange'])
def test_p4_batch3_single_day_rejects_invalid_facts(batch3_db_factory,kind):
    from src.biz.queries.wealth.market.index_detail_xxm.source import is_open_date,XxmSourceError
    day=date(2023,1,6);engine=batch3_db_factory()
    if kind in ('wrong_day','wrong_bool'):
        rows=[(date(2023,1,5),True)] if kind=='wrong_day' else [(day,1)]
        session=SimpleNamespace(execute=lambda statement:SimpleNamespace(all=lambda:rows))
        with pytest.raises(XxmSourceError):is_open_date(session,day)
        return
    with engine.begin() as connection:
        if kind in ('absent','other_exchange'):
            connection.execute(text("DELETE FROM core_serving.trade_calendar WHERE trade_date='2023-01-06'"))
        if kind=='other_exchange':connection.execute(text("INSERT INTO core_serving.trade_calendar VALUES('SZSE','2023-01-06',1,NULL)"))
        if kind=='null':connection.execute(text("UPDATE core_serving.trade_calendar SET is_open=NULL WHERE trade_date='2023-01-06'"))
        if kind=='duplicate':connection.execute(text("INSERT INTO core_serving.trade_calendar VALUES('SSE','2023-01-06',1,NULL)"))
    with Session(engine) as session,pytest.raises(XxmSourceError):is_open_date(session,day)


def _batch3_fixed_clock(monkeypatch,now=BATCH3_NOW):
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as source_query
    class FixedDateTime(datetime):
        @classmethod
        def now(cls,tz=None):return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)
    monkeypatch.setattr(source_query,'datetime',FixedDateTime)
    cache=XxmCache();monkeypatch.setattr(source_query,'_CACHE',cache)
    return cache


@pytest.mark.parametrize('freq',[30,60,90,120])
@pytest.mark.parametrize('kind,status',[('closed',400),('absent',500),('null',500),('open',200)])
def test_p4_batch3_early_asof_http_contract(batch3_db_factory,tmp_path,monkeypatch,freq,kind,status):
    _batch3_gold(tmp_path,freq,[(f'2023-01-10T{slot}:00',100.,0.,0.,0.) for slot in BATCH3_SLOTS[freq]])
    engine=batch3_db_factory();cache=_batch3_fixed_clock(monkeypatch)
    if kind in ('absent','null'):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM core_serving.trade_calendar WHERE trade_date='2023-01-06'") if kind=='absent' else text("UPDATE core_serving.trade_calendar SET is_open=NULL WHERE trade_date='2023-01-06'"))
    day='2023-01-07' if kind=='closed' else '2023-01-06'
    with patch.object(source_data,'is_open_date',wraps=source_data.is_open_date) as lookup,api(engine,lake_root=tmp_path) as client:
        response=client.get(PATH,params=dict(tsCode='000001.SH',period=f'm{freq}',asOf=day+'T15:00:00+08:00',debug=1))
        assert response.status_code==status,response.text
        assert lookup.call_count==0
        if status==200:
            normal=client.get(PATH,params=dict(tsCode='000001.SH',period=f'm{freq}',asOf=day+'T15:00:00+08:00'))
            assert normal.status_code==200 and normal.json()=={k:v for k,v in response.json().items() if k!='debug'}
            assert lookup.call_count==0
    assert bool(cache.entries)==(kind not in ('absent','null'))
    assert not any(key[0]=='forecast' for key in cache.entries)
    if status==200:assert response.json()['status']=='EMPTY'
    else:assert response.json()['code']==('XXMF_REQUEST_INVALID' if status==400 else 'XXMF_SOURCE_CONTRACT_INVALID')


@pytest.mark.parametrize('freq',[30,60,90,120])
@pytest.mark.parametrize('case',['empty_early','empty_current','inside','closed_inside','before_1990','future','future_endpoint'])
def test_p4_batch3_qualification_bounds_and_empty(batch3_db_factory,tmp_path,monkeypatch,freq,case):
    engine=batch3_db_factory()
    if case not in ('empty_early','empty_current'):_batch3_gold(tmp_path,freq)
    if case=='before_1990':
        with engine.begin() as connection:connection.execute(text("INSERT INTO core_serving.trade_calendar VALUES('SSE','1989-12-29',1,NULL)"))
    service=query.IndexDetailXxmForecastQueryService(lake_root=tmp_path,cache=XxmCache())
    day='1989-12-29' if case=='before_1990' else '2023-01-11' if case=='future' else '2023-01-07' if case=='closed_inside' else '2023-01-10' if case in ('empty_current','future_endpoint') else '2023-01-06'
    slot=BATCH3_SLOTS[freq][0] if case=='future_endpoint' else '15:00'
    stamp=day+'T'+slot+':00+08:00'
    now=BATCH3_NOW.replace(hour=10) if case=='future_endpoint' else BATCH3_NOW
    with Session(engine) as session,patch.object(source_data,'is_open_date',wraps=source_data.is_open_date) as lookup:
        if case in ('closed_inside','before_1990','future','future_endpoint'):
            with pytest.raises(XxmQueryError) as error:service.build(session,ts_code='000001.SH',period=f'm{freq}',as_of=stamp,now=now)
            assert error.value.status==400
        else:
            result=json.loads(service.build(session,ts_code='000001.SH',period=f'm{freq}',as_of=stamp,debug=True,now=now))
            assert result['status']==('EMPTY' if case.startswith('empty') else 'NO_CANDIDATE')
        assert lookup.call_count==0


@pytest.mark.parametrize('freq',[30,60,90,120])
def test_p4_batch3_real_minute_ready_cache_identity_and_next_endpoint(batch3_db_factory,tmp_path,monkeypatch,freq):
    from dataclasses import replace
    from unittest.mock import Mock
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as source_query
    from src.foundation.clients.local_lake.major_index_mins_reader import MajorIndexMinsLakeReader
    # Literal LLD 0.6.6. Only calibration is isolated; source and solver are real.
    times={30:('01-10T11:00','01-10T11:30','01-10T13:30','01-10T14:00','01-10T14:30','01-10T15:00'),
           60:('01-09T14:00','01-09T15:00','01-10T10:30','01-10T11:30','01-10T14:00','01-10T15:00'),
           90:('01-09T11:00','01-09T14:00','01-09T15:00','01-10T11:00','01-10T14:00','01-10T15:00'),
           120:('01-06T11:30','01-06T15:00','01-09T11:30','01-09T15:00','01-10T11:30','01-10T15:00')}[freq]
    values=((100.,-60.,-59.,-2.),(110.,0.,-1.,2.),(90.,-50.,-49.,-2.),(100.,0.,-1.,2.),(89.,-15.,0.,-30.),(88.,-14.,0.,-28.))
    rows=[('2023-'+stamp+':00',*value) for stamp,value in zip(times,values,strict=True)]
    _batch3_gold(tmp_path,freq,rows)
    engine=batch3_db_factory(end=date(2023,1,11));cache=_batch3_fixed_clock(monkeypatch)
    lookup=Mock(side_effect=AssertionError('latest must not check an out-of-range day'))
    monkeypatch.setattr(source_data,'is_open_date',lookup)
    calibration=Mock(return_value=ProjectionState(13,27,0));monkeypatch.setattr(query,'recover_projection',calibration)
    signatures=[];pairs=[];original_signature=MajorIndexMinsLakeReader.history_source_signature;original_pair=MajorIndexMinsLakeReader.read_complete_history_pair
    def signature(reader,*a,**k):signatures.append(k['dataset']);return original_signature(reader,*a,**k)
    def pair(reader,*a,**k):pairs.append(1);return original_pair(reader,*a,**k)
    monkeypatch.setattr(MajorIndexMinsLakeReader,'history_source_signature',signature)
    monkeypatch.setattr(MajorIndexMinsLakeReader,'read_complete_history_pair',pair)
    with patch.object(source_query,'plan_minute_window',wraps=source_query.plan_minute_window) as calendar,patch.object(query,'future_calendar',wraps=query.future_calendar) as future,patch.object(query,'forecast',wraps=query.forecast) as solve,patch.object(cache,'get_forecast',wraps=cache.get_forecast) as get,patch.object(cache,'put_forecast',wraps=cache.put_forecast) as put,api(engine,lake_root=tmp_path) as client:
        params=dict(tsCode='000001.SH',period=f'm{freq}')
        cold=client.get(PATH,params=params)
        assert cold.status_code==200,cold.text
        normal=cold.json()
        stored=next(value[0] for key,value in cache.entries.items() if key[0]=='forecast')
        assert isinstance(stored,InternalForecastResponseDto)
        source_key=next(key for key in cache.entries if key[0]!='forecast');source_entry=cache.entries[source_key][0]
        assert len(source_entry.raw)==6 and source_entry.points[-1]['ordinaryState']=='DULL'
        # A legitimate old entry with a longer calendar must keep every id.
        old=replace(source_entry,open_dates=(date(2023,1,2),*source_entry.open_dates))
        cache.put(source_key,old,check=lambda:4.)
        with patch.object(source_query.XxmCalculator,'step',side_effect=AssertionError('calendar normalization replay')):
            warm=client.get(PATH,params={**params,'debug':1})
        assert warm.status_code==200,warm.text
        debug=warm.json();details=debug['debug']
        assert normal=={k:v for k,v in debug.items() if k!='debug'}
        assert normal['status']=='READY' and normal['ordinaryState']=='DULL' and normal['direction']=='BOTTOM'
        assert normal['targetEndpoint']==f'2023-01-11T{BATCH3_SLOTS[freq][0]}:00+08:00' and normal['barsAhead']==1
        assert details['selectedReference']=='NEAR' and details['farEvaluated'] is False and details['conditions']
        assert any(condition['outcome']=='STRUCTURE_FORMED' for condition in details['conditions'])
        assert normal['forecastId']==stored.forecastId
        assert details['sourceInputId']==stored.sourceInputId and details['calendarInputId']==stored.calendarInputId
        assert [c['id'] for c in details['conditions']]==[c.id for c in stored.conditions]
        assert signatures==['bars','indicators','bars','indicators'] and pairs==[1]
        assert calendar.call_count==2 and calibration.call_count==future.call_count==get.call_count==2
        assert solve.call_count==put.call_count==1
        assert all(call.kwargs['requested_end']==datetime(2023,1,10,15,tzinfo=CN_ZONE) for call in calendar.call_args_list)
        assert old.open_dates[0]==date(2023,1,2) and cache.entries[source_key][0] is not old
        assert cold.headers['cache-control']==warm.headers['cache-control']=='no-store'


@pytest.mark.parametrize('kind',['timeout','source','query','async_cancel','future_cancel'])
def test_p4_bounded_plan_failure_keeps_published_source_and_priority(batch3_db_factory,tmp_path,monkeypatch,kind):
    from asyncio import CancelledError as AsyncCancelled
    from concurrent.futures import CancelledError as FutureCancelled
    from src.biz.queries.wealth.market.index_detail_xxm.source import XxmSourceError
    _batch3_gold(tmp_path,60,[(f'2023-01-10T{slot}:00',100.,0.,0.,0.) for slot in BATCH3_SLOTS[60]])
    service=query.IndexDetailXxmForecastQueryService(lake_root=tmp_path,cache=XxmCache())
    clock=[0.];monkeypatch.setattr(query.time,'perf_counter',lambda:clock[0])
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as source_query
    original=source_query.plan_minute_window;calls=[]
    failure={'source':XxmSourceError('bad source'),'query':RuntimeError('database error'),
             'async_cancel':AsyncCancelled(),'future_cancel':FutureCancelled()}.get(kind)
    def planned(*a,**k):
        result=original(*a,**k);calls.append(1);clock[0]=4.1
        if failure is not None:raise failure
        return result
    with Session(batch3_db_factory()) as session,patch.object(service.source.cache,'put_forecast',side_effect=AssertionError('failed forecast published')):
        with service.source.load_entry(session,ts_code='000001.SH',period='m60',now=BATCH3_NOW):pass
        monkeypatch.setattr(source_query,'plan_minute_window',planned)
        with pytest.raises(type(failure) if kind.endswith('cancel') else XxmQueryError) as error:
            service.build(session,ts_code='000001.SH',period='m60',as_of='2023-01-06T15:00:00+08:00',now=BATCH3_NOW)
        assert calls==[1]
        if kind.endswith('cancel'):assert error.value is failure
        else:assert error.value.code=={'timeout':'XXM_BUDGET_EXCEEDED','source':'XXM_SOURCE_CONTRACT_INVALID','query':'XXM_QUERY_FAILED'}[kind]
        entries=[value[0] for key,value in service.source.cache.entries.items() if key[0]!='forecast']
        assert len(entries)==1 and len(entries[0].processed)==4
        assert not any(key[0]=='forecast' for key in service.source.cache.entries)
        snapshot=entries[0].calculator.snapshot()
        monkeypatch.setattr(source_query,'plan_minute_window',original);clock[0]=0.
        result=json.loads(service.build(session,ts_code='000001.SH',period='m60',as_of='2023-01-06T15:00:00+08:00',now=BATCH3_NOW))
        assert result['status']=='EMPTY' and entries[0].calculator.snapshot()==snapshot


def test_p4_batch3_day_and_latest_do_not_use_single_day(m1,source_db,monkeypatch):
    monkeypatch.setattr(source_data,'is_open_date',lambda *a:pytest.fail('day lookup'))
    service,_=m1
    with Session(source_db) as session:
        assert read(service,session)['status']=='READY'
        assert read(service,session,as_of='2023-01-10')['status']=='READY'


@pytest.mark.parametrize('period,stamp',[
    ('m30','2023-01-10T09:30:00+08:00'),('m30','2023-01-10T12:00:00+08:00'),
    ('m30','2023-01-10T10:15:00+08:00'),('m60','2023-01-10T10:30:00'),
    ('m90','2023-01-10T11:30:00+08:00'),('m120','2023-01-10T11:30:00+00:00')])
def test_p4_batch3_invalid_endpoint_rejected_before_source(batch3_db_factory,tmp_path,monkeypatch,period,stamp):
    monkeypatch.setattr(query.IndexDetailXxmForecastQueryService,'build',lambda *a,**k:pytest.fail('invalid endpoint loaded source'))
    with api(batch3_db_factory(),lake_root=tmp_path) as client:
        response=client.get(PATH,params=dict(tsCode='000001.SH',period=period,asOf=stamp))
    assert response.status_code==400 and response.json()['code']=='XXMF_REQUEST_INVALID'


@pytest.mark.parametrize('case,expected,calls',[('none','NO_CANDIDATE',0),
    ('candidate','PRECISION_PENDING',1),('only_following','PRECISION_PENDING',1)])
def test_p4_bounded_short_source_precheck_precedes_real_calibration(batch3_db_factory,tmp_path,case,expected,calls):
    # Literal M1 and RC74/75 prefixes. They are intentionally not 250-bar
    # calibrated series; test the actual short-source status, without EMA mocks.
    values = ((100.,0.,0.),)*6 if case=='none' else M1 if case=='candidate' else (
        (100.,200.,2.),(90.,0.,-2.),(101.,100.,2.),(102.,100.,2.),(103.,99.,2.),(90.,98.,-2.))
    stamps=('2023-01-09T14:00:00','2023-01-09T15:00:00','2023-01-10T10:30:00',
            '2023-01-10T11:30:00','2023-01-10T14:00:00','2023-01-10T15:00:00')
    rows=[(stamp,float(c),float(d),float(d-h/2),float(h)) for stamp,(c,d,h) in zip(stamps,values,strict=True)]
    _batch3_gold(tmp_path,60,rows)
    service=query.IndexDetailXxmForecastQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(batch3_db_factory()) as session,patch.object(query,'recover_projection',wraps=query.recover_projection) as calibration,\
         patch.object(query,'future_calendar',side_effect=AssertionError('no future calendar before calibration')),\
         patch.object(query,'precheck_next_bar',wraps=query.precheck_next_bar) as precheck:
        result=json.loads(service.build(session,ts_code='000001.SH',period='m60',debug=True,now=BATCH3_NOW))
    assert result['status']==expected and result['dataStatus']=='READY'
    assert calibration.call_count==calls and precheck.call_count==1
    if case=='only_following':
        saved=next(iter(service.source.cache.entries.values()))[0]
        assert saved.calculator.state=='NONE' and saved.calculator.followed_structures['TOP'] is not None
    assert not any(key[0]=='forecast' for key in service.source.cache.entries)


@pytest.mark.parametrize('case',['empty','delayed'])
def test_p4_bounded_nonready_source_does_not_calibrate(batch3_db_factory,tmp_path,case):
    if case=='delayed':_batch3_gold(tmp_path,60,[('2023-01-10T14:00:00',100.,0.,0.,0.)])
    service=query.IndexDetailXxmForecastQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(batch3_db_factory()) as session,patch.object(query,'recover_projection',side_effect=AssertionError('nonready calibration')):
        result=json.loads(service.build(session,ts_code='000001.SH',period='m60',now=BATCH3_NOW))
    assert result['status']==case.upper()


def test_p4_bounded_real_page_enddate_and_forecasts_share_source_keep_modes(batch3_db_factory,tmp_path,monkeypatch):
    from src.biz.api.wealth.market.index_detail_minute_xxm import build_router as signals_router
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as source_query
    from src.foundation.clients.local_lake.major_index_mins_reader import MajorIndexMinsLakeReader
    _batch3_gold(tmp_path,60);engine=batch3_db_factory();cache=_batch3_fixed_clock(monkeypatch)
    def session():
        with Session(engine) as value:yield value
    test_client=api(engine,lake_root=tmp_path)
    test_client.app.include_router(signals_router(db_dependency=session,auth_dependency=lambda:None,
        lake_dependency=lambda:tmp_path,error_factory=WebAppError),prefix='/api/v1')
    with patch.object(source_query,'plan_minute_window',wraps=source_query.plan_minute_window) as plans,\
         patch.object(MajorIndexMinsLakeReader,'read_complete_history_pair',autospec=True,
                      side_effect=MajorIndexMinsLakeReader.read_complete_history_pair) as pair, test_client as client:
        params=dict(tsCode='000001.SH',freq=60,startDate='2023-01-06',endDate='2023-01-10',limit=500)
        normal=client.get('/api/v1/wealth/market/index-detail/minute-xxm-signals',params=params)
        debug=client.get('/api/v1/wealth/market/index-detail/minute-xxm-signals',params={**params,'debug':1})
        latest=client.get(PATH,params=dict(tsCode='000001.SH',period='m60'))
        replay=client.get(PATH,params=dict(tsCode='000001.SH',period='m60',asOf='2023-01-10T15:00:00+08:00'))
    assert all(r.status_code==200 for r in (normal,debug,latest,replay))
    assert normal.json()=={k:v for k,v in debug.json().items() if k!='debug'}
    assert latest.json()['mode']=='LATEST' and latest.json()['requestedAsOf'] is None
    assert replay.json()['mode']=='REPLAY' and replay.json()['requestedAsOf']=='2023-01-10T15:00:00+08:00'
    assert replay.json()['forecastId']!=latest.json()['forecastId']
    assert pair.call_count==1 and plans.call_count==4
    assert len([k for k in cache.entries if k[0]!='forecast'])==1


@pytest.mark.parametrize('holiday',[False,True])
def test_p4_bounded_overlapping_signal_forecast_use_same_flight(batch3_db_factory,tmp_path,monkeypatch,holiday):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as source_query
    from src.foundation.clients.local_lake.major_index_mins_reader import MajorIndexMinsLakeReader
    _batch3_gold(tmp_path,60);engine=batch3_db_factory();cache=XxmCache()
    signals=source_query.IndexDetailXxmQueryService(lake_root=tmp_path,cache=cache)
    forecasts=query.IndexDetailXxmForecastQueryService(lake_root=tmp_path,cache=cache)
    entered,joined,release=Event(),Event(),Event();keys=[]
    original_plan=source_query.plan_minute_window;original_shared=cache.loads.load
    end=date(2023,1,7) if holiday else date(2023,1,10)
    def plan(*a,**k):
        entered.set();assert release.wait(3)
        return original_plan(*a,**k)
    def shared(key,loader,remaining):
        keys.append(key);follower=len(keys)==2
        def wait_budget():
            if follower:joined.set()
            return remaining()
        return original_shared(key,loader,wait_budget)
    monkeypatch.setattr(source_query,'plan_minute_window',plan);monkeypatch.setattr(cache.loads,'load',shared)
    def signal():
        with Session(engine) as session:return json.loads(signals.build(session,ts_code='000001.SH',period='m60',start_date=None,end_date=end,limit=500,now=BATCH3_NOW))
    def forecast():
        with Session(engine) as session:return json.loads(forecasts.build(session,ts_code='000001.SH',period='m60',
            as_of=end.isoformat()+'T15:00:00+08:00' if holiday else None,now=BATCH3_NOW))
    with patch.object(MajorIndexMinsLakeReader,'read_complete_history_pair',autospec=True,
                      side_effect=MajorIndexMinsLakeReader.read_complete_history_pair) as pair,ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(signal);assert entered.wait(2)
        second=pool.submit(forecast)
        try:assert joined.wait(2)
        finally:release.set()
        assert first.result(timeout=3)['dataStatus']['status']=='READY'
        if holiday:
            with pytest.raises(XxmQueryError) as failure:second.result(timeout=3)
            assert failure.value.status==400
        else:assert second.result(timeout=3)['status']=='NO_CANDIDATE'
    assert keys[0]==keys[1] and pair.call_count==1 and not cache.loads._pending


def test_p4_bounded_early_and_future_forecast_refused_before_source(batch3_db_factory,tmp_path):
    service=query.IndexDetailXxmForecastQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(batch3_db_factory()) as session,patch.object(service.source,'load_entry',side_effect=AssertionError('early load')):
        with pytest.raises(XxmQueryError) as error:
            service.build(session,ts_code='000001.SH',period='m60',as_of='1989-12-29T15:00:00+08:00',now=BATCH3_NOW)
        assert error.value.status==400
    with Session(batch3_db_factory()) as session,patch.object(service.source,'_load_series',side_effect=AssertionError('future source')):
        with pytest.raises(XxmQueryError) as error:
            service.build(session,ts_code='000001.SH',period='m60',as_of='2023-01-11T15:00:00+08:00',now=BATCH3_NOW)
        assert error.value.status==400 and not service.source.cache.entries


EXPANSION_CODES=('000001.SH','399001.SZ','399006.SZ','000688.SH','000300.SH',
                 '000905.SH','000852.SH','000510.SH','000016.SH')


def _daily_literal_rows(engine, codes, values):
    """Finite M1/zero fixtures on the six independently fixed trading dates."""
    days=('2023-01-03','2023-01-04','2023-01-05','2023-01-06','2023-01-09','2023-01-10')
    rows=[dict(code=code,day=day,close=close,dif=dif,dea=dif-hist/2,hist=hist)
          for code in codes for day,(close,dif,hist) in zip(days,values,strict=True)]
    with engine.begin() as connection:
        connection.execute(text('DELETE FROM core_serving.index_factor_pro'))
        if rows:
            connection.execute(text('INSERT INTO core_serving.index_factor_pro '
                'VALUES(:code,:day,:close,:dif,:dea,:hist)'),rows)


@pytest.mark.parametrize('ts_code',EXPANSION_CODES)
@pytest.mark.parametrize('period',['day','m30','m60','m90','m120'])
def test_expansion_forecast_http_binds_all_approved_codes_and_periods(source_db,tmp_path,ts_code,period):
    # Real isolated query/source/calculator/DTO, with deliberately empty Gold.
    # The SSE day fixture is flat; no nonempty prediction is claimed here.
    with api(source_db,lake_root=tmp_path) as client:
        response=client.get(PATH,params=dict(tsCode=ts_code,period=period))
    assert response.status_code==200,response.text
    value=response.json()
    assert (value['tsCode'],value['period'])==(ts_code,period)
    assert value['status']==('NO_CANDIDATE' if ts_code=='000001.SH' and period=='day' else 'EMPTY')


@pytest.mark.parametrize('ts_code',['000680.SH','899050.BJ','999999.SH'])
@pytest.mark.parametrize('period',['day','m30'])
def test_expansion_forecast_rejects_unapproved_codes_before_context_or_cache(source_db,tmp_path,monkeypatch,ts_code,period):
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as source_query
    monkeypatch.setattr(source_query.MarketPageContextQuery,'resolve_context',
                        lambda *a,**k:pytest.fail('unsupported code reached context'))
    monkeypatch.setattr(source_query.XxmCache,'get',lambda *a:pytest.fail('unsupported cache read'))
    with api(source_db,lake_root=tmp_path) as client:
        response=client.get(PATH,params=dict(tsCode=ts_code,period=period))
    assert response.status_code==404 and response.json()['code']=='XXMF_NOT_SUPPORTED'


def test_expansion_forecast_configuration_error_is_not_source_or_unsupported(source_db,monkeypatch):
    from src.biz.services.wealth.market.index_detail.index_detail_universe import (
        IndexDetailUniverseService,IndexDetailQueryError,
    )
    def broken_config(self):
        raise IndexDetailQueryError('configured payload unavailable')
    with monkeypatch.context() as scoped:
        scoped.setattr(IndexDetailUniverseService,'load_universe',broken_config)
        scoped.setattr(query.IndexDetailXxmQueryService,'_load_series',
                       lambda *a,**k:pytest.fail('invalid configuration read source'))
        response=api(source_db).get(PATH,params=dict(tsCode='399001.SZ',period='day'))
    assert response.status_code==500 and response.json()['code']=='XXMF_QUERY_FAILED'
    normal=api(source_db).get(PATH,params=dict(tsCode='399001.SZ',period='day'))
    assert normal.status_code==200 and normal.json()['tsCode']=='399001.SZ'


def test_expansion_forecast_direct_build_requires_code_and_uses_normalized_identity(source_db):
    _daily_literal_rows(source_db,('399001.SZ',),[(100,0,0)]*6)
    service=query.IndexDetailXxmForecastQueryService(cache=XxmCache())
    with pytest.raises(TypeError,match='ts_code'):
        service.build(None,period='day')
    with Session(source_db) as session:
        value=read(service,session,ts_code=' 399001.sz ')
    assert value['tsCode']=='399001.SZ' and value['status']=='NO_CANDIDATE'


@pytest.mark.parametrize('ts_code',['399001.SZ','000688.SH'])
@pytest.mark.parametrize('case,expected',[
    ('empty','EMPTY'),('delayed','DELAYED'),('zero','NO_CANDIDATE'),('candidate','PRECISION_PENDING'),
])
def test_expansion_forecast_nonready_and_short_source_states_keep_code(source_db,monkeypatch,ts_code,case,expected):
    values=M1 if case=='candidate' else [(100,0,0)]*6
    _daily_literal_rows(source_db,(ts_code,),values)
    with source_db.begin() as connection:
        if case=='empty':connection.execute(text('DELETE FROM core_serving.index_factor_pro'))
        elif case=='delayed':connection.execute(text("DELETE FROM core_serving.index_factor_pro WHERE trade_date='2023-01-10'"))
    service=query.IndexDetailXxmForecastQueryService(cache=XxmCache())
    with Session(source_db) as session,patch.object(query,'recover_projection',wraps=query.recover_projection) as calibration:
        value=read(service,session,ts_code=ts_code,debug=True)
    assert value['tsCode']==ts_code and value['period']=='day' and value['status']==expected
    assert calibration.call_count==(1 if case=='candidate' else 0)
    assert value['targetEndpoint'] is None and value['debug']['conditions']==[]


def test_expansion_forecast_equal_inputs_have_separate_code_caches_and_ids(source_db,monkeypatch):
    codes=('399001.SZ','000688.SH')
    _daily_literal_rows(source_db,codes,M1)
    # M1's published literal EMA state isolates calibration only, as in m1.
    monkeypatch.setattr(query,'recover_projection',lambda bars,period,check:ProjectionState(13,27,0))
    service=query.IndexDetailXxmForecastQueryService(cache=XxmCache())
    with Session(source_db) as session,patch.object(query,'forecast',wraps=query.forecast) as solve:
        values=[read(service,session,ts_code=code,debug=True) for code in codes]
        assert solve.call_count==2
        for code,value in zip(codes,values,strict=True):
            assert read(service,session,ts_code=code,debug=True)==value
        assert solve.call_count==2
    assert all(value['status']=='READY' and value['debug']['conditions'] for value in values)
    assert values[0]['debug']['sourceInputId']==values[1]['debug']['sourceInputId']
    assert values[0]['forecastId']!=values[1]['forecastId']
    assert {key[-1] for key in service.source.cache.entries if key[0]=='forecast'}==set(codes)


@pytest.mark.parametrize('field,wrong',[
    ('tsCode','000688.SH'),('period','m30'),('forecastVersion','wrong'),
    ('forecastSpecHash','f'*64),('detectorSpecHash','f'*64),
])
@pytest.mark.parametrize('debug',[False,True])
def test_expansion_forecast_cache_binding_rejected_before_full_validation(source_db,monkeypatch,field,wrong,debug):
    codes=('399001.SZ','000688.SH')
    _daily_literal_rows(source_db,codes,M1)
    monkeypatch.setattr(query,'recover_projection',lambda bars,period,check:ProjectionState(13,27,0))
    service=query.IndexDetailXxmForecastQueryService(cache=XxmCache())
    cache=service.source.cache
    with Session(source_db) as session:
        for code in codes:read(service,session,ts_code=code)
        key=next(key for key in cache.entries if key[0]=='forecast' and key[-1]==codes[0])
        if field=='tsCode':
            other=next(value[0] for k,value in cache.entries.items() if k[0]=='forecast' and k[-1]==codes[1])
            cache.entries[key]=(other,cache.entries[key][1])
        else:
            setattr(cache.entries[key][0],field,wrong)
        before=dict(cache.entries)
        monkeypatch.setattr(query,'forecast',lambda *a,**k:pytest.fail('wrong cache was solved again'))
        with patch.object(InternalForecastResponseDto,'model_validate',side_effect=AssertionError('cheap binding must run first')):
            with pytest.raises(XxmQueryError) as error:read(service,session,ts_code=codes[0],debug=debug)
    assert error.value.code=='XXM_SOURCE_CONTRACT_INVALID'
    assert set(cache.entries)==set(before)
    assert all(cache.entries[k][0] is before[k][0] for k in before)


@pytest.mark.parametrize('ts_code',['399001.SZ','000510.SH'])
def test_expansion_m30_real_calibration_and_nonempty_forecast(batch3_db_factory,tmp_path,ts_code):
    from decimal import Decimal,localcontext
    # Same independently justified two-decline closes as the existing real
    # calibration test. The producer EMA below uses Decimal, not projection.
    closes=[100.]*250+[100,90,80,70,60,50,55,65,75,85,95,105]+list(range(100,49,-2))+[49,48]
    assert len(closes)==290
    slots=('10:00','10:30','11:00','11:30','13:30','14:00','14:30','15:00')
    # Both codes are in formal scope here, including A500 after 2024-10-22.
    begin=date(2025,10,9)
    stamps=[];day=begin
    while len(stamps)<len(closes):
        if day.weekday()<5:
            stamps.extend(day.isoformat()+'T'+slot+':00' for slot in slots)
        day+=timedelta(days=1)
    stamps=stamps[:len(closes)]
    rows=[]
    with localcontext():
        e12=e26=Decimal(100);dea=Decimal(0)
        for stamp,close in zip(stamps,closes,strict=True):
            price=Decimal(str(close))
            e12=(e12*11+price*2)/13;e26=(e26*25+price*2)/27
            dif=e12-e26;dea=(dea*4+dif)/5
            rows.append((stamp,float(price),float(dif),float(dea),float(2*(dif-dea))))
    assert rows[0][2:]==(0.,0.,0.) and rows[-1][1]==48
    assert stamps[-1].endswith('T10:30:00')
    _batch3_gold(tmp_path,30,rows,ts_code=ts_code)
    through=datetime.fromisoformat(stamps[-1]).replace(tzinfo=CN_ZONE)
    engine=batch3_db_factory(begin=begin,end=through.date())
    service=query.IndexDetailXxmForecastQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(engine) as session,patch.object(query,'recover_projection',wraps=query.recover_projection) as calibration:
        value=json.loads(service.build(session,ts_code=ts_code,period='m30',debug=True,
            as_of=through.isoformat(),now=through.replace(hour=21,minute=0,second=0)))
    assert calibration.call_count==1
    assert value['tsCode']==ts_code and value['period']=='m30'
    assert value['status']=='READY' and value['dataStatus']=='READY'
    assert value['computedThrough']==through.isoformat()
    assert value['targetEndpoint']==through.date().isoformat()+'T11:00:00+08:00'
    assert value['debug']['precisionPolicy']=='full_float'
    assert value['debug']['conditions'] and value['debug']['selectedReference']=='NEAR'
