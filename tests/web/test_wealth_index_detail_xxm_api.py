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
    small_response = api.get(path, params={"tsCode": "000001.SH", "startDate": "2020-01-05", "endDate": "2020-01-08", "limit": 3})
    assert small_response.status_code == 200
    small = small_response.json()
    assert small["points"] == full["points"][-3:]
    assert small["points"][0]["activeReference"]["startTime"] == "2020-01-01"
    assert small["source"]["startTime"] == "2020-01-01"
    assert small["dataStatus"]["status"] == "READY"
    assert len(small["specHash"]) == 64 and small["source"]["initialHistoryIncomplete"]
    past = api.get(path, params={"tsCode": "000001.SH", "endDate": "2020-01-06", "limit": 8}).json()
    assert len(past["topHistories"]) == 1
    assert past["topHistories"][0]["status"] == "PENDING"
    assert past["topHistories"][0]["endedAt"] is None
    assert past["topHistories"][0]["endReason"] is None
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
        first = service.build(session, now=datetime(2020,1,8,10,tzinfo=ZONE), **kwargs)
        assert first.source.computedThrough == "2020-01-06"
        all_before_close = service.build(session, now=datetime(2020,1,8,10,tzinfo=ZONE), **{**kwargs,"end_date":date(2020,1,8)})
        assert all_before_close.source.computedThrough == "2020-01-07"
        # Explicit isolated SQLite fixture mutation; no formal DB/lake access.
        session.execute(text("INSERT INTO core_serving.index_factor_pro VALUES ('000001.SH','2020-01-09',106,9.6,8.6,2)"))
        session.commit()
        after = service.build(session, now=datetime(2020,1,10,16,tzinfo=ZONE), **kwargs)
        assert after.model_dump() == first.model_dump()
        previous_input = after.source.inputId
        session.execute(text("UPDATE core_serving.index_factor_pro SET close=99.5 WHERE trade_date='2020-01-01'"))
        session.commit()
        revised = service.build(session, now=datetime(2020,1,10,16,tzinfo=ZONE), **kwargs)
        assert revised.source.inputId != previous_input
        assert revised.points[0].close == 99.5


@pytest.mark.parametrize("source_db", [{"skip_index": 3}], indirect=True)
def test_missing_calendar_day_fails_closed(source_db):
    service = IndexDetailXxmQueryService(cache=XxmCache())
    with Session(source_db) as session:
        with pytest.raises(XxmQueryError, match="缺口") as error:
            service.build(session, period="day", start_date=None, end_date=date(2020,1,8), limit=8,
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
            IndexDetailXxmQueryService(cache=XxmCache()).build(session, period="day", start_date=None,
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
        full_at_20 = service.build(session, period=f"m{freq}", start_date=None, end_date=end, limit=500,
                                   now=datetime.combine(end, datetime.min.time().replace(hour=20), ZONE))
        assert len(full_at_20.points) == len(values)
        before = datetime.combine(end,endpoints[-1],ZONE) - timedelta(minutes=1)
        partial = service.build(session,
            period=f"m{freq}",start_date=None,end_date=end,limit=500,now=before)
    assert len(partial.points) == len(values)-len(endpoints)
    assert partial.dataStatus.status == "READY"
    assert all(e.time <= partial.source.computedThrough for e in partial.events)


def bottom_entry(period='day', stop=None):
    from scripts.research.index_market.xxm.acceptance import load_source
    from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
    from src.biz.queries.wealth.market.index_detail_xxm.query_service import SeriesEntry
    source = Path(__file__).resolve().parents[2] / 'reports/xxm_source_audit_20261013_213852'
    raw = tuple(load_source(source, period))
    values = raw if stop is None else tuple(b for b in raw if b.time <= stop)
    calc = XxmCalculator(period=period, source_identity='B-api-test')
    points, events, histories, bottom, rearms, checkpoints = [], [], {}, {}, {}, {}
    for n, bar in enumerate(values, 1):
        step = calc.step(bar); points.append(step.point); events.extend(step.events)
        histories.update({h['id']: h for h in step.histories})
        bottom.update({h['id']: h for h in step.bottom_histories})
        rearms.update({r['id']: r for r in step.rearm_records})
        if n % 1000 == 0: checkpoints[n] = calc.snapshot()
    return SeriesEntry(raw=raw, signature=(), calculator=calc, processed=values, points=points,
                       events=events, histories=histories, bottom_histories=bottom, rearm_records=rearms,
                       fingerprints=['a'*64]*len(values), checkpoints=checkpoints)


@pytest.mark.parametrize('period', ['day', 'm60', 'm90', 'm120'])
def test_bottom_asof_restore_past_window_and_single_bar_external_structure(period):
    service = IndexDetailXxmQueryService
    entry = bottom_entry(period)
    for day in ('2024-07-09', '2024-07-11', '2024-07-22', '2024-07-23'):
        through = day if period == 'day' else day+'T15:00:00+08:00'
        actual = service._response(entry, period=period, expected=through, start_date=None, limit=2000, check=lambda: None)
        prefix = bottom_entry(period, through)
        independent = service._response(prefix, period=period, expected=through, start_date=None, limit=2000, check=lambda: None)
        assert actual.model_dump() == independent.model_dump()
        child = entry.calculator_at(len(prefix.processed), lambda: None)
        assert child.snapshot() == prefix.calculator.snapshot()
        before = entry.calculator.snapshot()
        if child.pending_bottom_history:
            child.pending_bottom_history['originalReference']['dif'] = -999
        assert entry.calculator.snapshot() == before
    event = next(e for e in entry.events if e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL')
    response = service._response(entry, period=period, expected=event['time'], start_date=None, limit=1, check=lambda: None)
    h = next(h for h in response.bottomHistories if h.id == event['relatedBottomHistoryId'])
    assert h.confirmedAt < response.meta.responseStart and h.structureEventId not in {e.id for e in response.events}
    assert h.status == 'ENDED' and h.endReason == 'historical_price_break'
    empty = service._response(entry, period=period, expected=event['time'], start_date=date(2099,1,1), limit=1, check=lambda: None)
    assert empty.dataStatus.status == 'READY' and empty.points == [] and empty.bottomHistories == []


def test_bottom_strict_dto_rejects_partial_contracts_and_accepts_old_point_pending():
    from copy import deepcopy
    from pydantic import ValidationError
    from src.biz.schemas.wealth.market.index_detail_xxm import XxmResponseDto
    from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
    entry = bottom_entry()
    response = IndexDetailXxmQueryService._response(entry, period='day', expected='2024-07-23',
                                                   start_date=date(2024,7,22), limit=2, check=lambda: None)
    payload = response.model_dump()
    assert payload['points'][0]['pendingBottomHistoryId'] and payload['bottomHistories'][0]['status'] == 'ENDED'
    assert XxmResponseDto.model_validate(payload).algorithmVersion == MAIN_SPEC.algorithm_version
    changes = [lambda r:r.pop('bottomHistories'), lambda r:r['points'][0].pop('pendingBottomHistoryId'),
               lambda r:r['events'][0].pop('relatedBottomHistoryId'), lambda r:r.update(algorithmVersion='xxm-direction-v0.1'),
               lambda r:r.update(specHash='a'*64), lambda r:r.update(bottomHistories=[]),
               lambda r:r['bottomHistories'][0].update(extra=True),
               lambda r:r['bottomHistories'][0].update(ageBars=True),
               lambda r:r['bottomHistories'][0].update(leftOriginAt='2024-07-24'),
               lambda r:r['bottomHistories'][0].update(priceLow=float('inf')),
               lambda r:r['bottomHistories'][0].update(endedAt='2024-07-24'),
               lambda r:r['events'][0].update(relatedTopHistoryId='other'),
               lambda r:r['events'][0].update(direction='TOP'),
               lambda r:r['events'][0].update(type='DULL',relatedBottomHistoryId=None),
               lambda r:r['events'][0].update(eventReference={**r['events'][0]['eventReference'],'dif':-999}),
               lambda r:r['points'][1].update(pendingBottomHistoryId=r['bottomHistories'][0]['id']),
               lambda r:r['dataStatus'].update(status='EMPTY')]
    for mutate in changes:
        changed = deepcopy(payload); mutate(changed)
        with pytest.raises(ValidationError): XxmResponseDto.model_validate(changed)


def test_bottom_increment_copy_revision_and_eviction(source_db, monkeypatch):
    from copy import deepcopy
    from scripts.research.index_market.xxm.acceptance import load_source
    source = Path(__file__).resolve().parents[2] / 'reports/xxm_source_audit_20261013_213852'
    full = tuple(load_source(source, 'day'))
    actual = [tuple(b for b in full if b.time <= '2024-07-22')]
    monkeypatch.setattr(query_service, 'read_daily', lambda *a, **kw: actual[0])
    monkeypatch.setattr(query_service, 'calendar_dates', lambda *a, **kw: tuple(date.fromisoformat(b.time) for b in full))
    cache = XxmCache(); service = IndexDetailXxmQueryService(cache=cache)
    now = datetime(2026,10,14,21,tzinfo=ZONE)
    with Session(source_db) as session:
        first, _ = service._load_series(session, key=('B',), period='day', now=now,
                      business_date=date(2026,10,13), remaining=lambda: 4)
        before = deepcopy(first.bottom_histories); old_snapshot = first.calculator.snapshot()
        actual[0] = tuple(b for b in full if b.time <= '2024-07-23')
        next_entry, _ = service._load_series(session, key=('B',), period='day', now=now,
                      business_date=date(2026,10,13), remaining=lambda: 4)
        assert first.bottom_histories == before and first.calculator.snapshot() == old_snapshot
        assert first.bottom_histories is not next_entry.bottom_histories
        assert any(h['endReason']=='historical_price_break' and h['endedAt']=='2024-07-23' for h in next_entry.bottom_histories.values())
        actual[0] = (replace(actual[0][0], close=actual[0][0].close+.1), *actual[0][1:])
        revised, _ = service._load_series(session, key=('B',), period='day', now=now,
                      business_date=date(2026,10,13), remaining=lambda: 4)
        assert revised.points[0]['close'] != next_entry.points[0]['close']
        assert revised.bottom_histories is not next_entry.bottom_histories
    tiny = XxmCache(max_bytes=1); tiny.put(('B',), next_entry)
    assert tiny.get(('B',)) is None


@pytest.mark.parametrize('period',['m60','m90','m120'])
def test_rearm_asof_single_bar_and_strict_bidirectional_contract(period):
    from copy import deepcopy
    from pydantic import ValidationError
    from src.biz.schemas.wealth.market.index_detail_xxm import XxmResponseDto
    service=IndexDetailXxmQueryService;entry=bottom_entry(period)
    record=next(iter(entry.rearm_records.values()));stamp=record['disappearedAt']
    response=service._response(entry,period=period,expected=stamp,start_date=None,limit=1,check=lambda:None)
    value=response.model_dump();r=value['rearmRecords'][0]
    assert r['status']=='WAITING' and r['endedAt'] is None and r['observedThrough']==stamp
    assert r['reference'] and 'referenceWave' not in r
    assert value['bottomHistories'][0]['structureEventId']==r['structureEventId']
    assert r['structureEventId'] not in {e['id'] for e in value['events']}
    prefix=bottom_entry(period,stamp)
    assert response==service._response(prefix,period=period,expected=stamp,start_date=None,limit=1,check=lambda:None)
    assert entry.calculator_at(len(prefix.processed),lambda:None).snapshot()==prefix.calculator.snapshot()
    mutations=[lambda v:v.pop('rearmRecords'),lambda v:v['points'][0].pop('pendingRearmId'),
        lambda v:v['events'][0].pop('relatedRearmId'),lambda v:v.update(rearmRecords=[]),
        lambda v:v['rearmRecords'][0].update(referenceWave={}),
        lambda v:v['rearmRecords'][0].update(direction='TOP'),
        lambda v:v['rearmRecords'][0].update(observedThrough='2099-01-01T15:00:00+08:00'),
        lambda v:v['rearmRecords'][0]['reference'].update(price=float('inf')),
        lambda v:v['rearmRecords'][0].update(endReason='zero'),
        lambda v:v['rearmRecords'][0].update(bottomHistoryId='wrong'),
        lambda v:v['points'][0].update(pendingRearmId='wrong'),
        lambda v:v['events'][0].update(relatedRearmId=None),
        lambda v:v['events'].append({**v['events'][0],'id':'duplicate-transition'}),
        lambda v:v['bottomHistories'][0].update(endReason='historical_price_break',leftOriginAt=stamp),
        lambda v:v['events'][0].update(type='CANCEL',relatedBottomHistoryId=None),
        lambda v:v['dataStatus'].update(status='EMPTY')]
    for mutate in mutations:
        bad=deepcopy(value);mutate(bad)
        with pytest.raises(ValidationError):XxmResponseDto.model_validate(bad)
    if record['endedAt']:
        whole=service._response(entry,period=period,expected=record['endedAt'],start_date=date.fromisoformat(stamp[:10]),limit=2000,check=lambda:None)
        assert any(p.pendingRearmId==record['id'] for p in whole.points)
        assert next(r for r in whole.rearmRecords if r.id==record['id']).status==record['status']
        assert XxmResponseDto.model_validate(whole.model_dump())==whole


@pytest.mark.parametrize('period',['m60','m90','m120'])
def test_rearm_ledger_increment_isolation_revision_and_cache_rebuild(source_db,tmp_path,monkeypatch,period):
    from copy import deepcopy
    entry=bottom_entry(period);record=next(iter(entry.rearm_records.values()))
    values={'bars':tuple(b for b in entry.raw if b.time<record['disappearedAt']),'revision':1}
    class Reader:
        def history_source_signature(self,request,*,dataset):return (dataset,values['revision'])
    monkeypatch.setattr(query_service,'minute_reader',lambda root:Reader())
    monkeypatch.setattr(query_service,'read_minutes',lambda *a,**kw:values['bars'])
    monkeypatch.setattr(query_service,'calendar_dates',lambda *a,**kw:tuple(sorted({date.fromisoformat(b.time[:10]) for b in entry.raw})))
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    now=datetime(2026,10,16,16,tzinfo=ZONE)
    with Session(source_db) as session:
        first,_=service._load_series(session,key=('rearm',period),period=period,now=now,business_date=date(2026,10,15),remaining=lambda:4)
        before=deepcopy(first.rearm_records);snapshot=first.calculator.snapshot()
        values.update(bars=tuple(b for b in entry.raw if b.time<=record['disappearedAt']),revision=2)
        second,_=service._load_series(session,key=('rearm',period),period=period,now=now,business_date=date(2026,10,15),remaining=lambda:4)
        assert first.rearm_records==before and first.calculator.snapshot()==snapshot
        assert first.rearm_records is not second.rearm_records and second.calculator.pending_rearm
        old=deepcopy(second.rearm_records)
        values.update(bars=(replace(values['bars'][0],close=values['bars'][0].close+.1),*values['bars'][1:]),revision=3)
        rebuilt,_=service._load_series(session,key=('rearm',period),period=period,now=now,business_date=date(2026,10,15),remaining=lambda:4)
        assert second.rearm_records==old and rebuilt.rearm_records is not second.rearm_records
        assert rebuilt.points[0]['close']!=second.points[0]['close']
