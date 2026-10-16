from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.exceptions import WebAppError, install_exception_handlers
from src.biz.api.wealth.market.index_detail_xxm_forecast import build_router
from src.biz.queries.wealth.market.index_detail_xxm import query_service
from src.biz.queries.wealth.market.index_detail_xxm.query_service import XxmCache
from src.biz.queries.wealth.market.index_detail_xxm.forecast_query_service import IndexDetailXxmForecastQueryService
from src.biz.queries.wealth.market.index_detail_xxm.source import ENDPOINTS, CN_ZONE
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState
from scripts.research.index_market.tests.test_xxm_key_point_forecast import frozen, ROOT

PATH = "/api/v1/wealth/market/index-detail/xxm-key-point-forecast"


@pytest.fixture
def source_db(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def attach(dbapi, record):
        dbapi.execute("ATTACH DATABASE ':memory:' AS core_serving")
    past = json.loads((ROOT / "reports/xxm_source_audit_20261013_213852/sse_minute_calendar.json").read_text())
    future = json.loads((ROOT / "reports/xxm_forecast_precheck_20261014/future_sse_calendar.json").read_text())["rows"]
    days = {r["trade_date"]: r["is_open"] for r in past + future}
    with engine.begin() as c:
        c.execute(text("CREATE TABLE core_serving.index_factor_pro (ts_code TEXT,trade_date DATE,close FLOAT,macd_dif_bfq FLOAT,macd_dea_bfq FLOAT,macd_bfq FLOAT)"))
        c.execute(text("CREATE TABLE core_serving.trade_calendar (exchange TEXT,trade_date DATE,is_open BOOLEAN,pretrade_date DATE)"))
        c.execute(text("INSERT INTO core_serving.trade_calendar (exchange,trade_date,is_open) VALUES ('SSE',:date,:open)"), [{"date": k,"open":v} for k,v in days.items()])
        c.execute(text("INSERT INTO core_serving.index_factor_pro VALUES ('000001.SH',:date,:close,:dif,:dea,:hist)"),
                  [dict(date=b.time,close=b.close,dif=b.dif,dea=b.dea,hist=b.hist) for b in frozen("day")])
    monkeypatch.setattr(query_service, "_CACHE", XxmCache())
    yield engine
    engine.dispose()


def api(engine, root=None, denied=None):
    def session():
        with Session(engine) as s:
            yield s
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(build_router(db_dependency=session,auth_dependency=denied or (lambda: None),
                       lake_dependency=lambda:root,error_factory=WebAppError),prefix="/api/v1")
    return TestClient(app)


def test_real_daily_route_query_dto_and_all_display_fields(source_db):
    response = api(source_db).get(PATH, params={"tsCode":"000001.SH","period":"day","asOf":"2026-10-13"})
    assert response.status_code == 200, response.text
    v = response.json()
    assert v["dataStatus"] == "READY" and v["status"] == "CONDITIONAL_ENTRY"
    assert v["targetEndpoint"] == "2026-10-15" and v["barsAhead"] == 2
    assert v["mode"] == "REPLAY" and v["requestedAsOf"] == v["computedThrough"] == "2026-10-13"
    from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
    assert v["detectorSpecHash"] == MAIN_SPEC.spec_hash
    assert v["forecastVersion"] == "xxm-key-point-forecast-v0.2-a1"
    assert "scenarios" not in v
    assert v["activation"]["endpoint"] == "2026-10-14"
    assert v["activation"]["ranges"][0]["priceRange"]["lower"] < 3500
    assert len(v["relations"]) >= 2 and len(v["commonConditions"]) >= 2
    assert len(v["examples"]) == 3
    assert all(term in v["display"]["conditionsText"] for term in ("钝化触发", "未触发", "推算失效", "结构成立"))
    assert not any(term in v["display"]["conditionsText"] for term in ("前置收盘", "目标收盘", "差异举例", "临界点"))
    assert "确认价" not in v["display"]["conditionsText"]
    assert "3764.1546" in v["display"]["conditionsText"] and "历史回放" in v["display"]["asOfText"]
    assert v["refreshAfterMs"] == 60000
    assert len(response.content) <= 32768
    assert api(source_db).get(PATH,params={"tsCode":"000001.SH","period":"day","asOf":"2026-10-13"}).json() == v


@pytest.mark.parametrize("query,code", [
    ("period=day",400), ("tsCode=000001.SH",400), ("tsCode=bad&period=day",400),
    ("tsCode=399001.SZ&period=day",404), ("tsCode=000001.SH&period=m30",400),
    ("tsCode=000001.SH&period=day&period=m60",400), ("tsCode=000001.SH&period=day&limit=20",400),
    ("tsCode=000001.SH&period=day&asOf=2999-01-01",400),
    ("tsCode=000001.SH&period=day&asOf=2026-10-11",400),
    ("tsCode=000001.SH&period=m90&asOf=2026-10-13T11:30:00%2B08:00",400),
    ("tsCode=000001.SH&period=m60&asOf=2026-10-13T10:30:00Z",400),
    ("tsCode=000001.SH&period=m60",404),
])
def test_invalid_requests_and_closed_minutes_do_not_produce_forecasts(source_db,query,code):
    r = api(source_db).get(PATH+"?"+query)
    assert r.status_code == code and r.json()["code"].startswith("XXMF_")
    assert "scenarios" not in r.json()


@pytest.mark.parametrize("status",[401,403])
def test_quote_auth_is_enforced_before_source(source_db,status):
    def denied():
        raise WebAppError(status_code=status,code="AUTH_REQUIRED",message="denied")
    assert api(source_db,denied=denied).get(PATH+"?tsCode=000001.SH&period=day").status_code == status


def test_latest_delayed_and_past_source_revision_causality(source_db):
    service = IndexDetailXxmForecastQueryService(cache=XxmCache())
    with Session(source_db) as s:
        delayed = service.build(s,period="day",now=datetime(2026,10,14,20,tzinfo=CN_ZONE))
        assert delayed.status == "DELAYED" and delayed.targetEndpoint is None and delayed.relations == []
        old = service.build(s,period="day",as_of="2026-10-12",now=datetime(2026,10,14,16,tzinfo=CN_ZONE))
        # Isolated fixture only; future price cannot affect an earlier prefix.
        s.execute(text("UPDATE core_serving.index_factor_pro SET close=close+100 WHERE trade_date='2026-10-13'"))
        s.commit()
        after = service.build(s,period="day",as_of="2026-10-12",now=datetime(2026,10,14,16,tzinfo=CN_ZONE))
        assert after == old
        s.execute(text("DELETE FROM core_serving.trade_calendar WHERE trade_date='2026-10-15'"))
        s.commit()
        with pytest.raises(query_service.XxmQueryError,match="日历.*缺口"):
            service.build(s,period="day",as_of="2026-10-12",now=datetime(2026,10,14,16,tzinfo=CN_ZONE))


@pytest.mark.parametrize("freq",[60,90,120])
def test_real_minute_route_and_two_stream_reader_calibration(source_db,tmp_path,freq):
    import duckdb
    from src.foundation.clients.local_lake.major_index_mins_contract import GOLD_BAR_COLUMN_SPECS, GOLD_INDICATOR_COLUMN_SPECS, GOLD_PARAMS_KEY
    days = [b.time for b in frozen("day")]
    slots = ENDPOINTS[freq]
    state = ProjectionState(3800,3800,0)
    values = []
    for i in range(252):
        close = 3800 + 30 * math.sin(i / 15) + i * .02
        state, (dif,dea,hist) = state.advance(close)
        day = date.fromisoformat(days[i // len(slots)])
        values.append(dict(ts_code="000001.SH",freq=freq,trade_date=day,trade_time=datetime.combine(day,slots[i%len(slots)]),
                           open=close,high=close,low=close,close=close,exchange="SSE",observation_count=i+1,
                           macd_dif=dif,macd_dea=dea,macd=hist,params_key=GOLD_PARAMS_KEY,indicator_version=1))
    con = duckdb.connect(":memory:")
    try:
        for dataset,specs,relative in (("bars",GOLD_BAR_COLUMN_SPECS,"quote/major_index_mins"),("indicators",GOLD_INDICATOR_COLUMN_SPECS,"indicator/major_index_mins_technical")):
            con.execute(f"CREATE TABLE {dataset} ({','.join(f'{name} {dtype}' for name,dtype in specs)})")
            con.executemany(f"INSERT INTO {dataset} VALUES ({','.join('?' for _ in specs)})",[[v.get(name,1.) for name,_ in specs] for v in values])
            for day in sorted(set(v["trade_date"] for v in values)):
                target=tmp_path/f"gold/{relative}/freq={freq}/trade_date={day}/part-000.parquet"
                target.parent.mkdir(parents=True,exist_ok=True)
                con.execute(f"CREATE OR REPLACE TEMP TABLE chunk AS SELECT * FROM {dataset} WHERE trade_date=?", [day])
                con.execute("COPY chunk TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        con.close()
    as_of=values[-1]["trade_time"].replace(tzinfo=CN_ZONE).isoformat()
    r=api(source_db,tmp_path).get(PATH,params={"tsCode":"000001.SH","period":f"m{freq}","asOf":as_of})
    assert r.status_code == 200,r.text
    value=r.json()
    assert value["dataStatus"] == "READY" and value["computedThrough"] == as_of
    assert value["precisionPolicy"] == "full_float" and value["status"] != "PRECISION_PENDING"
    assert len(value["sourceInputId"]) == 64 and value["display"]["targetText"]


def test_forecast_shares_slots_with_existing_layer_and_enforces_payload_budget(source_db, monkeypatch):
    from dataclasses import replace
    from src.biz.queries.wealth.market.index_detail_xxm import forecast_query_service as fq
    slots = query_service._REQUEST_SLOTS
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    try:
        r = api(source_db).get(PATH, params={"tsCode":"000001.SH","period":"day","asOf":"2026-10-13"})
        assert r.status_code == 503 and r.json()["code"] == "XXMF_BUDGET_EXCEEDED"
    finally:
        slots.release(); slots.release()
    monkeypatch.setattr(fq, "FORECAST_SPEC", replace(fq.FORECAST_SPEC, max_response_bytes=1))
    r = api(source_db).get(PATH, params={"tsCode":"000001.SH","period":"day","asOf":"2026-10-13"})
    assert r.status_code == 503 and r.json()["code"] == "XXMF_BUDGET_EXCEEDED"
    assert "scenarios" not in r.json()


def test_calibration_failure_does_not_return_an_active_candidate(source_db):
    with source_db.begin() as c:
        c.execute(text("UPDATE core_serving.index_factor_pro SET macd_dif_bfq=macd_dif_bfq+1 WHERE trade_date='2026-10-13'"))
    r = api(source_db).get(PATH, params={"tsCode":"000001.SH","period":"day","asOf":"2026-10-13"})
    assert r.status_code == 200
    v = r.json()
    assert v["status"] == "PRECISION_PENDING" and v["reasonCode"] == "CALIBRATION_FAILED"
    assert v["relations"] == [] and v["targetEndpoint"] is None


def test_actual_confirmed_structure_does_not_require_new_projection_tail(source_db):
    from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
    calc = XxmCalculator(period="day", source_identity="find-actual")
    stamp = None
    for i, b in enumerate(frozen("day")):
        step = calc.step(b)
        if any(e["type"] == "STRUCTURE" and e["route"] == "dif_turn" for e in step.events):
            assert i < 250
            stamp = b.time
            break
    assert stamp
    r = api(source_db).get(PATH,params={"tsCode":"000001.SH","period":"day","asOf":stamp})
    assert r.status_code == 200
    v = r.json()
    assert v["status"] == "CONFIRMED" and v["confirmedAt"] == stamp
    assert v["relations"] == [] and v["calendarInputId"] is None


def test_contract_rejects_legacy_and_invalid_range_relation(source_db):
    from copy import deepcopy
    from pydantic import ValidationError
    from src.biz.schemas.wealth.market.index_detail_xxm_forecast import ForecastResponseDto
    value=api(source_db).get(PATH,params={"tsCode":"000001.SH","period":"day","asOf":"2026-10-13"}).json()
    mutations=[lambda v:v.update(scenarios=[]),lambda v:v.update(forecastVersion='xxm-key-point-forecast-v0.1'),
               lambda v:v['activation']['ranges'][0]['priceRange'].update(upper=0),
               lambda v:v['relations'][0].update(entryRangeIds=['missing']),
               lambda v:v['relations'][0]['targetConditions'][0].update(op='approx'),
               lambda v:v.update(status='ENTRY_ONLY'),lambda v:v.update(barsAhead=1)]
    for mutation in mutations:
        broken=deepcopy(value);mutation(broken)
        with pytest.raises(ValidationError):ForecastResponseDto(**broken)


def test_actual_color_flip_confirmation_has_priority_over_new_none_state(source_db):
    from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
    calc=XxmCalculator(period='day',source_identity='flip-confirmation')
    stamp=None
    for bar in frozen('day'):
        step=calc.step(bar)
        if any(e['type']=='STRUCTURE' and e['route']=='color_flip' for e in step.events):
            stamp=bar.time;assert calc.state=='NONE';break
    assert stamp
    value=api(source_db).get(PATH,params={'tsCode':'000001.SH','period':'day','asOf':stamp})
    assert value.status_code==200,value.text
    v=value.json();assert v['status']=='CONFIRMED' and v['confirmedAt']==stamp
    assert v['activation'] is None and not v['relations']


def test_waiting_forecast_dto_and_real_producer_context_are_strict():
    from copy import deepcopy
    from pydantic import ValidationError
    from src.biz.schemas.wealth.market.index_detail_xxm_forecast import ForecastResponseDto
    path=ROOT/'reports/xxm_same_segment_a1_implementation_20261016/api/api_forecast_9_m120.json'
    value=json.loads(path.read_text());assert ForecastResponseDto.model_validate(value).rearmContext.status=='WAITING'
    mutations=[lambda v:v.pop('rearmContext'),lambda v:v.update(ordinaryState='DULL'),
        lambda v:v.update(status='READY'),lambda v:v.update(status='CONFIRMED'),
        lambda v:v.update(dataStatus='DELAYED'),lambda v:v['rearmContext'].update(referenceWave={}),
        lambda v:v['rearmContext'].update(status='REACTIVATED'),lambda v:v['rearmContext'].update(endReason='zero'),
        lambda v:v['rearmContext'].update(observedThrough='2099-01-01T15:00:00+08:00'),
        lambda v:v['activation']['ranges'][0]['reference'].update(price=1),
        lambda v:v['relations'][0]['reference'].update(dif=1),
        lambda v:v.update(forecastVersion='xxm-key-point-forecast-v0.2')]
    for mutate in mutations:
        bad=deepcopy(value);mutate(bad)
        with pytest.raises(ValidationError):ForecastResponseDto.model_validate(bad)
    for status in ('NO_CANDIDATE','PRECISION_PENDING'):
        inactive=deepcopy(value)
        inactive.update(status=status,targetEndpoint=None,barsAhead=None,activation=None,assumption=None,
                        relations=[],commonConditions=[],examples=[],targetEntryRanges=[],targetEntryExclusions=[])
        assert ForecastResponseDto.model_validate(inactive).rearmContext.status=='WAITING'
    from src.biz.queries.wealth.market.index_detail_xxm.forecast_query_service import _active_confirmation
    from types import SimpleNamespace
    broken=SimpleNamespace(points=[dict(time='2026-07-10',ordinaryState='STRUCTURE',ordinaryDirection='BOTTOM',pendingBottomHistoryId='missing')],
                           events=[],bottom_histories={})
    with pytest.raises(query_service.XxmQueryError,match='关联不完整'):_active_confirmation(broken,1,lambda:None)


@pytest.mark.parametrize('period',['m60','m90','m120'])
def test_batch_checkpoints_equal_full_prefix_and_reset_on_revision(source_db,tmp_path,monkeypatch,period):
    from dataclasses import replace
    from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
    from src.biz.queries.wealth.market.index_detail_xxm.query_service import _deep_size
    values={'bars':frozen(period),'revision':1}
    class FrozenReader:
        def history_source_signature(self,request,*,dataset):return ((dataset,values['revision']),)
    monkeypatch.setattr(query_service,'minute_reader',lambda root:FrozenReader())
    monkeypatch.setattr(query_service,'read_minutes',lambda *args,**kwargs:values['bars'])
    cache=XxmCache();source=query_service.IndexDetailXxmQueryService(lake_root=tmp_path,cache=cache)
    current=datetime(2026,10,13,20,tzinfo=CN_ZONE)
    with Session(source_db) as session:
        with source.load_entry(session,period=period,now=current) as (entry,*rest):
            assert len(entry.checkpoints)==len(values['bars'])//1000<=20
            assert _deep_size(entry)<=cache.max_bytes
            before=json.dumps(entry.checkpoints,sort_keys=True)
            for count in (999,1000,1001,2000,2001,len(entry.processed)-1,len(entry.processed)):
                expected=XxmCalculator(period=period,source_identity=entry.calculator.source_identity)
                for bar in entry.processed[:count]:expected.step(bar)
                child=entry.calculator_at(count,lambda:None)
                assert child.snapshot()==expected.snapshot()
            child.wave.price+=100
            assert json.dumps(entry.checkpoints,sort_keys=True)==before
            with pytest.raises(ValueError):entry.calculator_at(len(entry.processed)+1,lambda:None)
            # Future state cannot masquerade as an earlier exact batch.
            valid=entry.checkpoints[1000];entry.checkpoints[1000]=entry.calculator.snapshot()
            with pytest.raises(ValueError,match='real prefix'):entry.calculator_at(1000,lambda:None)
            entry.checkpoints[1000]=valid
            old_checkpoint=json.dumps(entry.checkpoints[1000],sort_keys=True)
            values['bars']=(*entry.processed[:999],replace(entry.processed[999],close=entry.processed[999].close+100),*entry.processed[1000:])
            values['revision']=2
        with source.load_entry(session,period=period,now=current) as (revised,*rest):
            assert json.dumps(revised.checkpoints[1000],sort_keys=True)!=old_checkpoint
            expected=XxmCalculator(period=period,source_identity=revised.calculator.source_identity)
            for bar in revised.processed[:1001]:expected.step(bar)
            assert revised.calculator_at(1001,lambda:None).snapshot()==expected.snapshot()


BUSINESS_PERIODS = ("day", "m60", "m90", "m120")


@pytest.fixture
def business_source(source_db, tmp_path, monkeypatch, request):
    """Real SQLite source and detector; minute transport is an isolated prefix fixture."""
    from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection
    publication = getattr(request, "param", "complete")
    values, records = {}, []
    revisions = {day: 1 for day in ("2026-10-14", "2026-10-15", "2026-10-16")}
    for period in BUSINESS_PERIODS:
        bars = list(frozen(period))
        state = recover_projection(tuple(bars), period, lambda: None)
        if publication != "missing":
            for day in (date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)):
                clocks = (None,) if period == "day" else ENDPOINTS[int(period[1:])]
                for clock in clocks:
                    if publication == "partial" and (period == "day" or day != date(2026, 10, 14) or clock != clocks[0]):
                        continue
                    stamp = day.isoformat() if clock is None else datetime.combine(day, clock, CN_ZONE).isoformat()
                    bar, state = state.project(bars[-1].close + 3, stamp, period, guard=False)
                    bars.append(bar)
        values[period] = tuple(bars)
    # Only this test's in-memory SQLite fixture is written; no formal source is accessed.
    with source_db.begin() as connection:
        extra = [b for b in values["day"] if b.time > "2026-10-13"]
        if extra:
            connection.execute(text("INSERT INTO core_serving.index_factor_pro VALUES ('000001.SH',:date,:close,:dif,:dea,:hist)"),
                               [dict(date=b.time, close=b.close, dif=b.dif, dea=b.dea, hist=b.hist) for b in extra])
    class PrefixReader:
        def history_source_signature(self, request, *, dataset):
            records.append(("signature", request.freq, dataset, request.end_date))
            return ((dataset, request.end_date.isoformat(), tuple((day, version) for day, version in revisions.items() if day <= request.end_date.isoformat())),)
    def read(_reader, *, freq, end, deadline, start=None):
        deadline()
        records.append(("read", freq, None, end))
        return tuple(b for b in values[f"m{freq}"] if b.time[:10] <= end.isoformat())
    monkeypatch.setattr(query_service, "minute_reader", lambda _: PrefixReader())
    monkeypatch.setattr(query_service, "read_minutes", read)
    return dict(engine=source_db, root=tmp_path, values=values, records=records, revisions=revisions)


def business_service(source):
    return IndexDetailXxmForecastQueryService(lake_root=source["root"], cache=XxmCache())


def close_stamp(period, day):
    return day if period == "day" else day + "T15:00:00+08:00"


@pytest.mark.parametrize("period", BUSINESS_PERIODS)
@pytest.mark.parametrize("clock", ["10:45:00", "11:15:00", "15:00:00", "19:59:59"])
def test_business_date_before_20_ignores_intraday_completion_and_early_published_source(business_source, period, clock):
    source = business_source
    with Session(source["engine"]) as session:
        value = business_service(source).build(session, period=period, now=datetime.fromisoformat("2026-10-14T" + clock + "+08:00"))
    assert value.dataStatus == "READY" and value.status not in ("DELAYED", "EMPTY")
    assert value.computedThrough == close_stamp(period, "2026-10-13")
    assert value.mode == "LATEST" and value.requestedAsOf is None
    assert "历史回放" not in value.display.asOfText and "数据滞后" != value.display.statusLabel
    assert all(record[-1] == date(2026, 10, 13) for record in source["records"])


@pytest.mark.parametrize("period", BUSINESS_PERIODS)
def test_business_date_at_20_switches_the_real_snapshot_and_cache_without_future_leak(business_source, period):
    source = business_source; service = business_service(source)
    before = datetime(2026, 10, 14, 19, 59, 59, tzinfo=CN_ZONE)
    with Session(source["engine"]) as session:
        old = service.build(session, period=period, now=before)
        current = service.build(session, period=period, now=before + timedelta(seconds=1))
        restored = service.build(session, period=period, now=before)
    assert current.dataStatus == "READY" and current.status not in ("DELAYED", "EMPTY", "PRECISION_PENDING")
    assert current.computedThrough == close_stamp(period, "2026-10-14")
    assert current.sourceInputId != old.sourceInputId
    assert restored == old


@pytest.mark.parametrize("business_source", ["missing", "partial"], indirect=True)
@pytest.mark.parametrize("period", BUSINESS_PERIODS)
def test_business_date_after_20_missing_or_partial_current_day_is_not_a_ready_fallback(business_source, period):
    with Session(business_source["engine"]) as session:
        value = business_service(business_source).build(session, period=period, now=datetime(2026, 10, 14, 20, tzinfo=CN_ZONE))
    assert value.dataStatus == value.status == "DELAYED"
    assert value.targetEndpoint is None and not value.activation and not value.relations


@pytest.mark.parametrize("period", BUSINESS_PERIODS)
def test_future_revision_cannot_change_the_before_20_snapshot_or_its_forecast(business_source, period):
    from dataclasses import replace
    source = business_source; service = business_service(source)
    now = datetime(2026, 10, 14, 19, 59, 59, tzinfo=CN_ZONE)
    with Session(source["engine"]) as session:
        first = service.build(session, period=period, now=now)
        if period == "day":
            session.execute(text("UPDATE core_serving.index_factor_pro SET close=close+1000 WHERE trade_date>='2026-10-14'"))
            session.commit()
        else:
            source["values"][period] = tuple(replace(b, close=b.close+1000, dif=b.dif+1000) if b.time[:10] >= "2026-10-14" else b for b in source["values"][period])
        source["revisions"]["2026-10-14"] += 1
        after = service.build(session, period=period, now=now)
    assert after == first


@pytest.mark.parametrize("period", BUSINESS_PERIODS)
def test_replay_is_bounded_by_business_day_and_stable_across_cutover(business_source, period):
    source = business_source; service = business_service(source)
    before = datetime(2026, 10, 14, 19, 59, 59, tzinfo=CN_ZONE)
    past = close_stamp(period, "2026-10-12")
    with Session(source["engine"]) as session:
        first = service.build(session, period=period, as_of=past, now=before)
        after = service.build(session, period=period, as_of=past, now=before + timedelta(seconds=1))
        with pytest.raises(query_service.XxmQueryError) as error:
            service.build(session, period=period, as_of=close_stamp(period, "2026-10-14"), now=before)
    assert first == after and first.mode == "REPLAY"
    assert error.value.status == 400


@pytest.mark.parametrize("period", BUSINESS_PERIODS)
@pytest.mark.parametrize("now,expected", [
    ("2026-10-17T10:00:00+08:00", "2026-10-16"),
    ("2026-10-17T20:00:00+08:00", "2026-10-16"),
    ("2026-10-19T10:00:00+08:00", "2026-10-16"),
    ("2026-10-01T10:00:00+08:00", "2026-09-30"),
    ("2026-10-01T20:00:00+08:00", "2026-09-30"),
])
def test_four_periods_reuse_weekend_holiday_and_previous_open_day(business_source, period, now, expected):
    with Session(business_source["engine"]) as session:
        value = business_service(business_source).build(session, period=period, now=datetime.fromisoformat(now))
    assert value.computedThrough == close_stamp(period, expected)
    assert value.dataStatus == "READY"


@pytest.mark.parametrize("period", BUSINESS_PERIODS)
def test_overlapping_forecasts_share_one_validated_load(business_source, monkeypatch, period):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    source = business_source; cache = XxmCache()
    entered, release, waiting = Event(), Event(), Event()
    actual = query_service.read_daily if period == "day" else query_service.read_minutes
    reads = []
    def paused(*args, **kwargs):
        reads.append(1); entered.set()
        assert release.wait(3)
        return actual(*args, **kwargs)
    monkeypatch.setattr(query_service, "read_daily" if period == "day" else "read_minutes", paused)
    original_load = cache.loads.load
    def observed(key, loader, remaining):
        def budget():
            if current_thread().name.endswith("_1"): waiting.set()
            return remaining()
        return original_load(key, loader, budget)
    monkeypatch.setattr(cache.loads, "load", observed)
    def build():
        with Session(source["engine"]) as session:
            return IndexDetailXxmForecastQueryService(lake_root=source["root"],cache=cache).build(
                session,period=period,now=datetime(2026,10,14,11,15,tzinfo=CN_ZONE))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(build)
        assert entered.wait(3)
        second = pool.submit(build)
        assert waiting.wait(3)
        # One actual load owns a slot; the waiting caller owns none.
        assert query_service._REQUEST_SLOTS.acquire(blocking=False)
        query_service._REQUEST_SLOTS.release()
        release.set()
        a,b = first.result(),second.result()
    assert a == b and a.dataStatus == "READY" and reads == [1]
    assert not cache.loads._pending
    assert sum(r[0] == "signature" for r in source["records"]) == (0 if period == "day" else 2)


@pytest.mark.parametrize("period", BUSINESS_PERIODS)
def test_unchanged_source_reuses_validation_and_response_but_revision_invalidates(business_source, monkeypatch, period):
    from dataclasses import replace
    from src.biz.queries.wealth.market.index_detail_xxm import forecast_query_service as fq
    source = business_source; cache = XxmCache()
    service = IndexDetailXxmForecastQueryService(lake_root=source["root"],cache=cache)
    validations, forecasts = [], []
    original_continuity, original_forecast = query_service.assert_continuous, fq.forecast
    def continuity(*args,**kwargs):
        validations.append(1); return original_continuity(*args,**kwargs)
    def calculate(*args,**kwargs):
        forecasts.append(1); return original_forecast(*args,**kwargs)
    monkeypatch.setattr(query_service,"assert_continuous",continuity)
    monkeypatch.setattr(fq,"forecast",calculate)
    now=datetime(2026,10,14,11,15,tzinfo=CN_ZONE)
    with Session(source["engine"]) as session:
        first=service.build(session,period=period,now=now)
        original=first.model_copy(deep=True)
        first.display.conditionsText="caller mutation"
        after=service.build(session,period=period,now=now)
        assert after==original and validations==[1]
        assert len(forecasts)==1
        # Every independent minute request still checks both signatures.
        assert sum(r[0]=="signature" for r in source["records"])==(0 if period=="day" else 4)
        if period=="day":
            session.execute(text("UPDATE core_serving.index_factor_pro SET close=close+1 WHERE trade_date='2026-10-13'"))
            session.commit()
        else:
            source["values"][period]=tuple(replace(b,close=b.close+1) if b.time==close_stamp(period,"2026-10-13") else b for b in source["values"][period])
            source["revisions"]["2026-10-13"]=2
        revised=service.build(session,period=period,now=now)
        assert revised.sourceInputId!=original.sourceInputId and revised.forecastId!=original.forecastId
        assert len(validations)==2


@pytest.mark.parametrize("period", BUSINESS_PERIODS)
def test_published_entry_is_not_mutated_when_another_request_appends(business_source,period):
    source=business_source; cache=XxmCache()
    service=query_service.IndexDetailXxmQueryService(lake_root=source["root"],cache=cache)
    with Session(source["engine"]) as session:
        with service.load_entry(session,period=period,now=datetime(2026,10,14,19,59,59,tzinfo=CN_ZONE)) as (old,*_):
            from copy import deepcopy
            old_bottom=deepcopy(old.bottom_histories); old_checkpoints=deepcopy(old.checkpoints)
            state=old.calculator.snapshot(); count=len(old.processed); last=old.processed[-1]
            with service.load_entry(session,period=period,now=datetime(2026,10,14,20,tzinfo=CN_ZONE)) as (new,*_):
                assert len(new.processed)>count and new is not old
            assert len(old.processed)==count and old.processed[-1]==last and old.calculator.snapshot()==state
            assert old.bottom_histories==old_bottom and old.checkpoints==old_checkpoints


def test_response_cache_includes_future_calendar_and_obeys_shared_lru_limit(source_db,monkeypatch):
    cache=XxmCache(max_series=2)
    service=IndexDetailXxmForecastQueryService(cache=cache)
    now=datetime(2026,10,14,11,15,tzinfo=CN_ZONE)
    with Session(source_db) as session:
        first=service.build(session,period="day",now=now)
        session.execute(text("UPDATE core_serving.trade_calendar SET is_open=false WHERE trade_date='2026-10-15'"));session.commit()
        changed=service.build(session,period="day",now=now)
        assert changed.calendarInputId!=first.calendarInputId and changed.forecastId!=first.forecastId
        for as_of in ("2026-10-09","2026-10-12","2026-10-13"):
            service.build(session,period="day",now=now,as_of=as_of)
            assert len(cache.entries)<=2
            assert sum(size for _,size in cache.entries.values())<=cache.max_bytes
    tiny=XxmCache(max_bytes=1)
    tiny.put_forecast(("day",),first)
    assert tiny.get_forecast(("day",)) is None and not tiny.entries
