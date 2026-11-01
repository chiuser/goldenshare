from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.exceptions import WebAppError, install_exception_handlers
from src.biz.api.wealth.market.index_detail_xxm import build_router
from src.biz.api.wealth.market.index_detail_minute_xxm import build_router as build_minute_router
from src.biz.queries.wealth.market.index_detail_xxm import query_service
from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService, XxmCache, XxmQueryError
from src.biz.queries.wealth.market.index_detail_xxm.source import assert_continuous, XxmSourceError
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


VALUES = [(100, 10, 2), (101, 12, 2), (99, 9, -2), (100, 9, 2), (102, 10, 2), (103, 9.8, 2), (104, 10, 2), (105, 9.7, 2)]
ZONE = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def source_db(monkeypatch, request):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def attach(dbapi, _record):
        dbapi.execute("ATTACH DATABASE ':memory:' AS core_serving")

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE core_serving.index_factor_pro (ts_code TEXT,trade_date DATE,close FLOAT,macd_dif_bfq FLOAT,macd_dea_bfq FLOAT,macd_bfq FLOAT)"))
        conn.execute(text("CREATE TABLE core_serving.trade_calendar (exchange TEXT,trade_date DATE,is_open BOOLEAN,pretrade_date DATE)"))
        begin = date(2020, 1, 1)
        now = datetime.now(ZONE).date()
        conn.execute(text("INSERT INTO core_serving.trade_calendar (exchange,trade_date,is_open) VALUES (:exchange,:date,:open)"),
                     [{"exchange": "SSE", "date": (begin + timedelta(days=i)).isoformat(), "open": True} for i in range((now - begin).days + 1)])
        conn.execute(text("INSERT INTO core_serving.index_factor_pro VALUES (:code,:date,:close,:dif,:dea,:hist)"),
                     [{"code": "000001.SH", "date": (begin + timedelta(days=i)).isoformat(), "close": c,
                       "dif": d, "dea": d - h / 2, "hist": h} for i, (c, d, h) in enumerate(VALUES)
                      if i != getattr(request, "param", {}).get("skip_index")])
    monkeypatch.setattr(query_service, "_CACHE", XxmCache())
    yield engine
    engine.dispose()


def build_debug(service, *args, **kwargs):
    from src.biz.schemas.wealth.market.index_detail_xxm import XxmDebugResponseDto
    return XxmDebugResponseDto.model_validate_json(service.build(*args, debug=True, **kwargs))


def client(engine, auth=lambda: None):
    app = FastAPI()
    install_exception_handlers(app)

    def session():
        with Session(engine) as session:
            yield session

    app.include_router(build_router(db_dependency=session, auth_dependency=auth, error_factory=WebAppError), prefix="/api/v1")
    return TestClient(app)


def test_real_router_query_and_window_reference_history_are_consistent(source_db):
    api = client(source_db)
    path = "/api/v1/wealth/market/index-detail/xxm-signals"
    full = api.get(path, params={"tsCode": "000001.SH", "endDate": "2020-01-08", "limit": 8}).json()
    small_response = api.get(path, params={"tsCode": "000001.SH", "startDate": "2020-01-05", "endDate": "2020-01-08", "limit": 3, "debug": 1})
    assert small_response.status_code == 200
    small = small_response.json()
    assert small["points"] == full["points"][-3:]
    assert small["debug"]["points"][0]["activeReference"]["startTime"] == "2020-01-01"
    assert small["source"]["startTime"] == "2020-01-01"
    assert small["dataStatus"]["status"] == "READY"
    assert len(small["specHash"]) == 64 and small["source"]["initialHistoryIncomplete"]
    past = api.get(path, params={"tsCode": "000001.SH", "endDate": "2020-01-06", "limit": 8, "debug": 1}).json()
    assert len(past["debug"]["structures"]) == 1
    assert past["debug"]["structures"][0]["status"] == "ASSESSING"
    assert past["debug"]["structures"][0]["trackingEndedAt"] is None
    assert past["debug"]["structures"][0]["disappearanceReason"] is None
    assert past["source"]["computedThrough"] == "2020-01-06"


@pytest.mark.parametrize("suffix,status", [
    ("tsCode=000001.SH&limit=0",400), ("tsCode=000001.SH&limit=2001",400),
    ("tsCode=000001.SH&limit=2&limit=3",400), ("tsCode=000001.SH&dif_turn_pct=1",400),
    ("tsCode=000001.SH&startDate=2020-01-08&endDate=2020-01-01",400),
    ("tsCode=000001.SH&period=m60",400), ("tsCode=000001.SH&endDate=2020-02-30",400),
    ("tsCode=399001.SZ",404), ("tsCode=bad",400), ("",400),
])
def test_invalid_and_unsupported_requests_never_produce_a_layer(source_db, suffix, status):
    result = client(source_db).get("/api/v1/wealth/market/index-detail/xxm-signals?" + suffix)
    assert result.status_code == status
    assert result.json()["code"] == ("XXM_NOT_SUPPORTED" if status == 404 else "XXM_REQUEST_INVALID")


@pytest.mark.parametrize("status", [401, 403])
def test_injected_existing_auth_is_required_before_query(source_db, status):
    def denied():
        raise WebAppError(status_code=status, code="AUTH_REQUIRED", message="denied")
    assert client(source_db, denied).get("/api/v1/wealth/market/index-detail/xxm-signals?tsCode=000001.SH").status_code == status


def test_append_revision_and_incomplete_day_do_not_mutate_past(source_db):
    cache = XxmCache()
    service = IndexDetailXxmQueryService(cache=cache)
    kwargs = dict(period="day", start_date=None, end_date=date(2020,1,6), limit=8)
    with Session(source_db) as session:
        first = build_debug(service, session, now=datetime(2020,1,8,10,tzinfo=ZONE), **kwargs)
        assert first.source.computedThrough == "2020-01-06"
        all_before_close = build_debug(service, session, now=datetime(2020,1,8,10,tzinfo=ZONE), **{**kwargs,"end_date":date(2020,1,8)})
        assert all_before_close.source.computedThrough == "2020-01-07"
        # Explicit isolated SQLite fixture mutation; no formal DB/lake access.
        session.execute(text("INSERT INTO core_serving.index_factor_pro VALUES ('000001.SH','2020-01-09',106,9.6,8.6,2)"))
        session.commit()
        after = build_debug(service, session, now=datetime(2020,1,10,16,tzinfo=ZONE), **kwargs)
        assert after.model_dump() == first.model_dump()
        previous_input = after.debug.sourceInputId
        session.execute(text("UPDATE core_serving.index_factor_pro SET close=99.5 WHERE trade_date='2020-01-01'"))
        session.commit()
        revised = build_debug(service, session, now=datetime(2020,1,10,16,tzinfo=ZONE), **kwargs)
        assert revised.debug.sourceInputId != previous_input
        assert revised.points[0].close == 99.5


@pytest.mark.parametrize("source_db", [{"skip_index": 3}], indirect=True)
def test_missing_calendar_day_fails_closed(source_db):
    service = IndexDetailXxmQueryService(cache=XxmCache())
    with Session(source_db) as session:
        with pytest.raises(XxmQueryError, match="缺口") as error:
            build_debug(service, session, period="day", start_date=None, end_date=date(2020,1,8), limit=8,
                          now=datetime(2020,1,10,16,tzinfo=ZONE))
        assert error.value.code == "XXM_SOURCE_CONTRACT_INVALID"


def test_zero_events_is_ready_and_empty_source_is_empty(source_db):
    # Restrict endDate before any history can activate, not an implementation-derived expectation.
    api = client(source_db)
    r = api.get("/api/v1/wealth/market/index-detail/xxm-signals?tsCode=000001.SH&endDate=2020-01-02").json()
    assert r["events"] == [] and r["dataStatus"]["status"] == "READY"
    r = api.get("/api/v1/wealth/market/index-detail/xxm-signals?tsCode=000001.SH&endDate=1999-01-01").json()
    assert r["points"] == [] and r["dataStatus"]["status"] == "EMPTY" and r["source"]["computedThrough"] is None


def test_budgets_and_calendar_gap_on_both_streams_are_not_silently_skipped(source_db, monkeypatch):
    monkeypatch.setattr(query_service, "BUDGET", replace(query_service.BUDGET, max_response_bytes=10))
    with Session(source_db) as session:
        with pytest.raises(XxmQueryError) as error:
            build_debug(IndexDetailXxmQueryService(cache=XxmCache()), session, period="day", start_date=None,
                end_date=date(2020,1,8),limit=8,now=datetime(2020,1,10,16,tzinfo=ZONE))
        assert error.value.code == "XXM_BUDGET_EXCEEDED"
    values = (XxmBar("2020-01-01T15:00:00+08:00",100,1,0,2), XxmBar("2020-01-03T11:30:00+08:00",100,1,0,2))
    with pytest.raises(XxmSourceError):
        assert_continuous(values, period="m120", open_dates=(date(2020,1,1),date(2020,1,2),date(2020,1,3)))


@pytest.mark.parametrize("freq", [60, 90, 120])
def test_minute_router_uses_real_two_stream_reader_and_completed_endpoints(source_db, tmp_path, freq):
    import duckdb
    from src.foundation.clients.local_lake.major_index_mins_contract import (
        GOLD_BAR_COLUMN_SPECS, GOLD_INDICATOR_COLUMN_SPECS, GOLD_PARAMS_KEY,
    )
    from src.biz.queries.wealth.market.index_detail_xxm.source import ENDPOINTS

    # These are isolated test Parquet files, never the formal Lake.
    endpoints = ENDPOINTS[freq]
    values = VALUES + [VALUES[-1]] if freq == 90 else VALUES
    con = duckdb.connect(":memory:")
    try:
        for dataset, specs, relative in (("bars", GOLD_BAR_COLUMN_SPECS, "quote/major_index_mins"),
                                          ("indicators", GOLD_INDICATOR_COLUMN_SPECS, "indicator/major_index_mins_technical")):
            con.execute(f"CREATE TABLE {dataset} ({','.join(f'{name} {dtype}' for name,dtype in specs)})")
            for i, (c, d, h) in enumerate(values):
                day = date(2020,1,1) + timedelta(days=i // len(endpoints))
                row = {name: 1.0 for name, _ in specs}
                row.update(ts_code="000001.SH", freq=freq, trade_date=day,
                           trade_time=datetime.combine(day, endpoints[i % len(endpoints)]),
                           open=c, high=c, low=c, close=c, exchange="SSE", observation_count=i+1,
                           macd_dif=d, macd_dea=d-h/2, macd=h, params_key=GOLD_PARAMS_KEY, indicator_version=1)
                con.execute(f"INSERT INTO {dataset} VALUES ({','.join('?' for _ in specs)})", [row[name] for name,_ in specs])
            for offset in range(0, len(values), len(endpoints)):
                day = date(2020,1,1) + timedelta(days=offset // len(endpoints))
                target = tmp_path / f"gold/{relative}/freq={freq}/trade_date={day}/part-000.parquet"
                target.parent.mkdir(parents=True, exist_ok=True)
                chunk = f"{dataset}_{offset}"
                con.execute(f"CREATE TEMP TABLE {chunk} AS SELECT * FROM {dataset} WHERE trade_date=?", [day])
                con.execute(f"COPY {chunk} TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        con.close()
    def session():
        with Session(source_db) as session:
            yield session
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(build_minute_router(db_dependency=session,auth_dependency=lambda:None,
                       lake_dependency=lambda:tmp_path,error_factory=WebAppError),prefix="/api/v1")
    api = TestClient(app)
    path = "/api/v1/wealth/market/index-detail/minute-xxm-signals"
    end = date(2020,1,1) + timedelta(days=len(values)//len(endpoints)-1)
    response = api.get(path,params={"tsCode":"000001.SH","freq":freq,"endDate":end.isoformat()})
    assert response.status_code == 200
    data = response.json()
    assert data["period"] == f"m{freq}" and data["source"]["indicatorVersion"] == 1
    assert data["meta"]["count"] == len(values) and data["dataStatus"]["status"] == "READY"
    assert [p["close"] for p in data["points"]] == [v[0] for v in values]
    assert any(e["type"] == "STRUCTURE" for e in data["events"])
    for bad in ("freq=30", "freq=60&freq=90", "freq=120&dif_turn_pct=1"):
        assert api.get(path+"?tsCode=000001.SH&"+bad).status_code == 400
    # Even a full current-day file must not enter the page before the 20:00 switch.
    with Session(source_db) as session:
        service = IndexDetailXxmQueryService(lake_root=tmp_path, cache=XxmCache())
        full_at_20 = build_debug(service, session, period=f"m{freq}", start_date=None, end_date=end, limit=500,
                                   now=datetime.combine(end, datetime.min.time().replace(hour=20), ZONE))
        assert len(full_at_20.points) == len(values)
        before = datetime.combine(end,endpoints[-1],ZONE) - timedelta(minutes=1)
        partial = build_debug(service, session,
            period=f"m{freq}",start_date=None,end_date=end,limit=500,now=before)
    assert len(partial.points) == len(values)-len(endpoints)
    assert partial.dataStatus.status == "READY"
    assert all(e.time <= partial.source.computedThrough for e in partial.events)



@pytest.mark.parametrize("period", ["day", "m60", "m90", "m120"])
@pytest.mark.parametrize("sign", [1, -1])
def test_current_public_window_full_events_and_no_future_structure(period, sign):
    # RC77/93 literal producer: all inputs and their independent expected events
    # are documented in LLD14.15; this exercises the real internal producer.
    from scripts.research.index_market.tests.test_xxm_r4_following_query import entry, response
    from scripts.research.index_market.tests.test_xxm_r4_following import TF, values
    from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_xxm_response
    source = entry(values(TF + [(102,97,2),(104,96,2)],sign),period)
    internal = response(source,8,limit=1)
    ordinary = project_xxm_response(internal,debug=False)
    debug = project_xxm_response(internal,debug=True)
    assert ordinary.model_dump() == {k:v for k,v in debug.model_dump().items() if k != 'debug'}
    assert [e.type for e in ordinary.events] == ['CANCEL','DULL']
    assert [e.displayOnChart for e in ordinary.events] == [False,True]
    assert len(debug.debug.events)==2
    record=debug.debug.structures[0]
    assert record.formedAt < ordinary.meta.responseStart and record.status=='DISAPPEARED'
    assert record.originWave.priceAt and record.originWave.difAt
    earlier=project_xxm_response(response(source,5),debug=True)
    assert earlier.debug.structures[0].status=='ASSESSING'
    assert earlier.debug.structures[0].firstOppositeAt is None


@pytest.mark.parametrize('debug,expected_validations', [(False, 0), (True, 1)])
def test_p4_batch1_signal_projection_validates_only_public_result(debug, expected_validations):
    from unittest.mock import patch
    from src.biz.schemas.wealth.market.index_detail_xxm import InternalXxmResponseDto
    from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_xxm_response
    from scripts.research.index_market.tests.test_xxm_r4_following_query import entry, response
    from scripts.research.index_market.tests.test_xxm_r4_following import TN

    internal = response(entry(TN), 8)
    before = internal.model_dump()
    with patch.object(InternalXxmResponseDto, 'model_validate', wraps=InternalXxmResponseDto.model_validate) as validate:
        public = project_xxm_response(internal, debug=debug)
    # The public debug validator still verifies reconstructed associations.
    assert validate.call_count == expected_validations
    assert public.points[-1].time == '2023-01-12'
    assert internal.model_dump() == before


@pytest.mark.parametrize('debug', [False, True])
def test_p4_batch1_signal_projection_requires_internal_model_and_strict_debug(debug):
    from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_xxm_response
    from scripts.research.index_market.tests.test_xxm_r4_following_query import entry, response
    from scripts.research.index_market.tests.test_xxm_r4_following import TN

    internal = response(entry(TN), 8)
    ordinary = project_xxm_response(internal, debug=False)
    detailed = project_xxm_response(internal, debug=True)
    assert ordinary.model_dump() == {k: v for k, v in detailed.model_dump().items() if k != 'debug'}
    for bad in (internal.model_dump(), ordinary, detailed, None, object()):
        with pytest.raises(ValueError, match='InternalXxmResponseDto'):
            project_xxm_response(bad, debug=debug)
    for bad_debug in (0, 1, None, 'true'):
        with pytest.raises(ValueError, match='Debug must be a boolean'):
            project_xxm_response(internal, debug=bad_debug)
        # Debug is checked before the input model, including when both are bad.
        with pytest.raises(ValueError, match='Debug must be a boolean'):
            project_xxm_response({}, debug=bad_debug)


@pytest.mark.parametrize('debug', [False, True])
def test_p4_batch1_signal_projection_keeps_dynamic_audit_wrapper(debug):
    from scripts.research.index_market import xxm_page_request_audit as audit
    from scripts.research.index_market.tests.test_xxm_p4_audit_tools import group
    from scripts.research.index_market.tests.test_xxm_r4_following_query import entry, response
    from scripts.research.index_market.tests.test_xxm_r4_following import TF
    from src.biz.services.wealth.market.index_detail_xxm import response_projection as projection

    internal = response(entry(TF + [(102, 97, 2), (104, 96, 2)]), 8, limit=1)
    before = internal.model_dump()
    original = projection.project_xxm_response
    collector = audit.AuditCollector(group())
    assert audit._REQUEST_ID.get() is None
    with audit._observe(collector):
        assert projection.project_xxm_response is not original
        public = projection.project_xxm_response(internal, debug=debug)
        assert [event.type for event in public.events] == ['CANCEL', 'DULL']
        assert [event.displayOnChart for event in public.events] == [False, True]
        assert public.meta.responseStart == '2023-01-12'
    assert projection.project_xxm_response is original
    assert internal.model_dump() == before and collector.requests == {}


def test_public_and_debug_contracts_reject_legacy_bad_types_and_links():
    from copy import deepcopy
    from src.biz.schemas.wealth.market.index_detail_xxm import XxmResponseDto, XxmDebugResponseDto
    from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_xxm_response
    from scripts.research.index_market.tests.test_xxm_r4_following_query import entry, response
    from scripts.research.index_market.tests.test_xxm_r4_following import TN
    value=project_xxm_response(response(entry(TN),8),debug=True).model_dump()
    assert XxmDebugResponseDto.model_validate(value)
    normal={k:v for k,v in value.items() if k!='debug'}
    assert XxmResponseDto.model_validate(normal)
    changes=[lambda v:v.update(topHistories=[]),lambda v:v.update(specHash='wrong'),
        lambda v:v['points'][0].update(close=True),lambda v:v['points'][0].update(dif='99'),
        lambda v:v['events'][0].pop('displayOnChart'), lambda v:v['events'][0].update(displayOnChart=1),
        lambda v:v['debug']['points'][0].update(activeStructureId='dangling'),
        lambda v:v['debug']['structures'][0].update(firstOppositeAt='2099-01-01'),
        lambda v:v['debug']['events'][0].update(relatedStructureId='missing'),
        lambda v:v['debug']['structures'][0]['originWave'].update(priceAt='2099-01-01')]
    for change in changes:
        bad=deepcopy(value);change(bad)
        with pytest.raises(ValueError): XxmDebugResponseDto.model_validate(bad)
    with pytest.raises(ValueError): XxmResponseDto.model_validate(value)


@pytest.mark.parametrize('raw',['','true','01','2','1&debug=0'])
def test_invalid_debug_does_not_enter_source(source_db,raw,monkeypatch):
    monkeypatch.setattr(IndexDetailXxmQueryService,'build',lambda *a,**k:pytest.fail('bad request read source'))
    r=client(source_db).get('/api/v1/wealth/market/index-detail/xxm-signals?tsCode=000001.SH&debug='+raw)
    assert r.status_code==400


def test_real_http_normal_debug_same_facts_and_no_store(source_db,monkeypatch):
    from src.biz.schemas.wealth.market.index_detail_xxm import XxmResponseDto
    encoded=[];original=XxmResponseDto.model_dump_json
    def encode(value,*a,**k):
        body=original(value,*a,**k);encoded.append(body.encode());return body
    monkeypatch.setattr(XxmResponseDto,"model_dump_json",encode)
    c=client(source_db);path='/api/v1/wealth/market/index-detail/xxm-signals'
    normal=c.get(path,params={'tsCode':'000001.SH','endDate':'2020-01-08'})
    debug=c.get(path,params={'tsCode':'000001.SH','endDate':'2020-01-08','debug':'1'})
    assert normal.status_code==debug.status_code==200
    assert normal.headers['cache-control']==debug.headers['cache-control']=='no-store'
    assert encoded==[normal.content,debug.content]
    assert normal.json()=={k:v for k,v in debug.json().items() if k!='debug'}
    assert 'inputId' not in normal.json()['source']


@pytest.mark.parametrize('mismatch',['none','length','time','code','freq','date','left_empty','right_empty','both_empty'])
def test_p4_batch2_two_streams_match_in_one_pass(mismatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from src.biz.queries.wealth.market.index_detail_xxm.source import read_minutes
    price=[dict(ts_code='000001.SH',freq=60,trade_date=date(2020,1,1),trade_time=datetime(2020,1,1,h,m),close=100+i)
        for i,(h,m) in enumerate(((10,30),(11,30),(14,0)))]
    indicators=[{k:v for k,v in row.items() if k!='close'}|dict(macd_dif=0.,macd_dea=0.,macd=0.) for row in price]
    if mismatch=='length': indicators.pop()
    elif mismatch=='time': indicators[1]['trade_time']=datetime(2020,1,1,11,29)
    elif mismatch=='code': indicators[1]['ts_code']='399001.SZ'
    elif mismatch=='freq': indicators[1]['freq']=90
    elif mismatch=='date': indicators[1]['trade_date']=date(2020,1,2)
    elif mismatch in ('left_empty','both_empty'): price=[]
    if mismatch in ('right_empty','both_empty'): indicators=[]
    reader=Mock()
    reader.read_complete_history_pair.return_value=(SimpleNamespace(rows=tuple(price)),SimpleNamespace(rows=tuple(indicators)))
    if mismatch in ('none','both_empty'):
        result=read_minutes(reader,freq=60,end=date(2020,1,1),deadline=lambda:3.)
        assert [bar.close for bar in result]==([100,101,102] if mismatch=='none' else [])
        assert all((bar.dif,bar.dea,bar.hist)==(0.,0.,0.) for bar in result)
    else:
        with pytest.raises(XxmSourceError): read_minutes(reader,freq=60,end=date(2020,1,1),deadline=lambda:3.)
    args=reader.read_complete_history_pair.call_args
    assert reader.read_complete_history_pair.call_count==1
    assert args.kwargs==dict(timeout_seconds=3.,bar_value_columns=('close',),indicator_value_columns=('macd_dif','macd_dea','macd'))


@pytest.mark.parametrize('field',['close','macd_dif','macd_dea','macd'])
@pytest.mark.parametrize('bad',[None,float('nan'),float('inf')])
def test_p4_batch2_bar_validation_still_rejects_required_values(field,bad):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from src.biz.queries.wealth.market.index_detail_xxm.source import read_minutes
    price=dict(ts_code='000001.SH',freq=60,trade_date=date(2020,1,1),trade_time=datetime(2020,1,1,10,30),close=100.)
    indicator={k:v for k,v in price.items() if k!='close'}|dict(macd_dif=0.,macd_dea=0.,macd=0.)
    (price if field=='close' else indicator)[field]=bad
    reader=Mock();reader.read_complete_history_pair.return_value=(SimpleNamespace(rows=(price,)),SimpleNamespace(rows=(indicator,)))
    with pytest.raises(XxmSourceError): read_minutes(reader,freq=60,end=date(2020,1,1),deadline=lambda:3.)


@pytest.mark.parametrize('period,endpoints',[
    ('day',None),('m60',('10:30:00','11:30:00','14:00:00','15:00:00')),
    ('m90',('11:00:00','14:00:00','15:00:00')),('m120',('11:30:00','15:00:00'))])
@pytest.mark.parametrize('kind',['valid','duplicate','reverse','missing_day','missing_middle'])
def test_p4_batch2_calendar_still_rejects_gaps_duplicates_and_order(period,endpoints,kind):
    # Literal endpoint table, independent of source.ENDPOINTS; weekend isn't a missing day.
    days=(date(2026,8,7),date(2026,8,10),date(2026,8,11))
    times=[d.isoformat() for d in days] if period=='day' else [f'{d}T{t}+08:00' for d in days for t in endpoints]
    if kind=='duplicate': times.insert(1,times[0])
    elif kind=='reverse': times.reverse()
    elif kind=='missing_day': times=[t for t in times if not t.startswith('2026-08-10')]
    elif kind=='missing_middle': times.pop(1)
    values=tuple(XxmBar(t,100.,0.,0.,0.) for t in times)
    if kind=='valid': assert_continuous(values,period=period,open_dates=days)
    else:
        with pytest.raises(XxmSourceError): assert_continuous(values,period=period,open_dates=days)


def _batch2_real_xxm_gold(root,freq,change):
    import duckdb
    from src.foundation.clients.local_lake.major_index_mins_contract import GOLD_BAR_COLUMN_SPECS,GOLD_INDICATOR_COLUMN_SPECS,GOLD_PARAMS_KEY
    # Producers' fixed Gold schemas; independent literal end times and business values.
    endpoints={60:('10:30:00','11:30:00','14:00:00','15:00:00'),90:('11:00:00','14:00:00','15:00:00'),120:('11:30:00','15:00:00')}[freq]
    with duckdb.connect(':memory:') as con:
        for dataset,specs,folder in (('bars',GOLD_BAR_COLUMN_SPECS,'quote/major_index_mins'),('indicators',GOLD_INDICATOR_COLUMN_SPECS,'indicator/major_index_mins_technical')):
            con.execute(f'CREATE TABLE {dataset} ('+','.join(f'{n} {t}' for n,t in specs)+')')
            for i,clock in enumerate(endpoints):
                row={n:1. for n,_ in specs}
                row.update(ts_code='000001.SH',freq=freq,trade_date=date(2020,1,1),trade_time='2020-01-01 '+clock,
                    close=100+i,exchange='SSE',macd_dif=.1,macd_dea=.2,macd=-.2,observation_count=1,params_key=GOLD_PARAMS_KEY,indicator_version=1)
                con.execute(f'INSERT INTO {dataset} VALUES ('+','.join('?' for _ in specs)+')',[row[n] for n,_ in specs])
            if change=='unused_bad':
                con.execute(f'UPDATE {dataset} SET '+("open='NaN'::DOUBLE" if dataset=='bars' else 'observation_count=0'))
            if dataset=='indicators':
                if change=='misaligned': con.execute("UPDATE indicators SET trade_time=trade_time+INTERVAL '1 minute' WHERE trade_time=(SELECT min(trade_time) FROM indicators)")
                elif change=='bad_version': con.execute('UPDATE indicators SET indicator_version=0')
                elif change=='bad_macd': con.execute("UPDATE indicators SET macd_dif='NaN'::DOUBLE")
                elif change=='duplicate': con.execute('INSERT INTO indicators SELECT * FROM indicators LIMIT 1')
            projection='* EXCLUDE (open)' if change=='unused_missing' and dataset=='bars' else '* EXCLUDE (ma_5)' if change=='unused_missing' else '*'
            path=root/f'gold/{folder}/freq={freq}/trade_date=2020-01-01/part-000.parquet';path.parent.mkdir(parents=True,exist_ok=True)
            con.execute(f'COPY (SELECT {projection} FROM {dataset}) TO ? (FORMAT PARQUET)',[str(path)])
    return endpoints


@pytest.mark.parametrize('freq',[60,90,120])
@pytest.mark.parametrize('change',['valid','unused_bad','unused_missing','misaligned','bad_version','bad_macd','duplicate','empty'])
def test_p4_batch2_real_xxm_partial_reader_and_http(source_db,tmp_path,freq,change):
    if change!='empty': endpoints=_batch2_real_xxm_gold(tmp_path,freq,change)
    def session():
        with Session(source_db) as s: yield s
    app=FastAPI();install_exception_handlers(app)
    app.include_router(build_minute_router(db_dependency=session,auth_dependency=lambda:None,lake_dependency=lambda:tmp_path,error_factory=WebAppError),prefix='/api/v1')
    with TestClient(app) as api:
        path='/api/v1/wealth/market/index-detail/minute-xxm-signals'
        response=api.get(path,params={'tsCode':'000001.SH','freq':freq,'endDate':'2020-01-01','debug':'1'})
        if change in ('valid','unused_bad','unused_missing','empty'):
            normal=api.get(path,params={'tsCode':'000001.SH','freq':freq,'endDate':'2020-01-01'})
            assert normal.status_code==200
            assert normal.json()=={k:v for k,v in response.json().items() if k!='debug'}
            assert normal.headers['cache-control']==response.headers['cache-control']=='no-store'
    if change in ('misaligned','bad_version','bad_macd','duplicate'):
        assert response.status_code==500 and response.json()['code']=='XXM_SOURCE_CONTRACT_INVALID'
        assert not query_service._CACHE.entries
    else:
        assert response.status_code==200
        data=response.json()
        assert data['meta']['count']==(0 if change=='empty' else len(endpoints))
        assert [p['close'] for p in data['points']]==([] if change=='empty' else list(range(100,100+len(endpoints))))
        assert '_source_filename' not in response.text and '_partition_date' not in response.text
