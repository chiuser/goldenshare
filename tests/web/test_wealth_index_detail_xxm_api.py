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
