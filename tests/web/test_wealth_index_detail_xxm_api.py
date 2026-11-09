from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.services.wealth.market.index_detail_xxm.debug_projection import project_debug_signal
from src.app.exceptions import WebAppError, install_exception_handlers
from src.biz.api.wealth.market.index_detail_xxm import build_router
from src.biz.api.wealth.market.index_detail_minute_xxm import build_router as build_minute_router
from src.biz.queries.wealth.market.index_detail_xxm import query_service
from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService, XxmCache, XxmQueryError
from src.biz.queries.wealth.market.index_detail_xxm.source import (
    assert_continuous, XxmSourceError, MinuteSourceWindow, normalize_minute_end, plan_minute_window,
)
from goldenshare_technical_indicators.xxm.types import XxmBar
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader


VALUES = [(100, 10, 2), (101, 12, 2), (99, 9, -2), (100, 9, 2), (102, 10, 2), (103, 9.8, 2), (104, 10, 2), (105, 9.7, 2)]
ZONE = ZoneInfo("Asia/Shanghai")


def _write_dg_calendar(root, *, first, last, open_days):
    import duckdb

    # Silver trade_calendar/full stores SSE DATE keys and DATE pretrade_date.
    path = root / "silver/calendar/trade_calendar/full/part-000.parquet"
    path.parent.mkdir(parents=True)
    previous = None
    rows = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        opened = day in open_days
        rows.append(("SSE", day, opened, previous))
        if opened:
            previous = day
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE calendar(exchange VARCHAR, trade_date DATE, is_open BOOLEAN, pretrade_date DATE)")
        connection.executemany("INSERT INTO calendar VALUES (?, ?, ?, ?)", rows)
        connection.execute("COPY calendar TO ? (FORMAT PARQUET)", [str(path)])


@pytest.fixture
def dg_daily(tmp_path):
    import duckdb

    first = date(2009, 12, 31)
    days = [date(2010, 1, day) for day in (4, 5, 6, 7, 8)]
    _write_dg_calendar(tmp_path, first=first, last=date(2010, 1, 8), open_days={first, *days})
    # DG Silver index_factor_pro uses DATE, DOUBLE and a per-trading-day file.
    with duckdb.connect() as connection:
        connection.execute("""CREATE TABLE factors(ts_code VARCHAR, trade_date DATE,
            close DOUBLE, macd_dif_bfq DOUBLE, macd_dea_bfq DOUBLE, macd_bfq DOUBLE)""")
        for index, day in enumerate((first, *days)):
            connection.execute("INSERT INTO factors VALUES ('000001.SH', ?, ?, 0, 0, 0)", [day, 100 + index])
            if day >= date(2010, 1, 6):
                connection.execute("INSERT INTO factors VALUES ('399001.SZ', ?, ?, 0, 0, 0)", [day, 200 + index])
            path = tmp_path / f"silver/index/index_factor_pro/trade_date={day}/part-000.parquet"
            path.parent.mkdir(parents=True)
            connection.execute("COPY factors TO ? (FORMAT PARQUET)", [str(path)])
            connection.execute("DELETE FROM factors")
    return IndexDailyLakeReader(tmp_path)


def test_dg_day_bounds_prefix_and_cache_identity(dg_daily):
    from src.biz.queries.wealth.market.index_detail_xxm.forecast_query_service import IndexDetailXxmForecastQueryService

    cache = XxmCache()
    signals = IndexDetailXxmQueryService(daily_lake=dg_daily, cache=cache)
    forecast = IndexDetailXxmForecastQueryService(daily_lake=dg_daily, cache=cache)
    now = datetime(2010, 1, 7, 20, tzinfo=ZONE)
    selected = build_debug(signals, None, period="day", start_date=date(2010, 1, 5),
                           end_date=date(2010, 1, 6), limit=1, now=now)
    assert selected.source.startTime == "2010-01-04"
    assert selected.source.computedThrough == "2010-01-06"
    assert [(point.time, point.close) for point in selected.points] == [("2010-01-06", 103.0)]
    latest = json.loads(forecast.build(None, ts_code="000001.SH", period="day", now=now))
    historical = json.loads(forecast.build(None, ts_code="000001.SH", period="day", as_of="2010-01-05", now=now))
    assert (latest["mode"], latest["computedThrough"], latest["status"]) == ("LATEST", "2010-01-07", "NO_CANDIDATE")
    assert historical["computedThrough"] == "2010-01-05"
    late = build_debug(signals, None, ts_code="399001.SZ", period="day",
                       start_date=None, end_date=None, limit=300, now=now)
    assert late.source.startTime == "2010-01-06"
    assert [point.time for point in late.points] == ["2010-01-06", "2010-01-07"]
    assert {key[-1] for key in cache.entries} == {"000001.SH", "399001.SZ"}
    assert all(key[:3] == ("dg", f"dg:{dg_daily.root}", "day") and len(key) == 5 for key in cache.entries)
    actual = cache.entries[next(key for key in cache.entries if key[-1] == "000001.SH")][0]
    assert [bar.time for bar in actual.raw] == ["2010-01-04", "2010-01-05", "2010-01-06", "2010-01-07"]


def test_dg_day_existing_cutover_and_internal_gap(dg_daily):
    service = IndexDetailXxmQueryService(daily_lake=dg_daily, cache=XxmCache())
    before_switch = datetime(2010, 1, 7, 19, 59, tzinfo=ZONE)
    result = build_debug(service, None, period="day", start_date=None, end_date=None, limit=300, now=before_switch)
    assert result.source.computedThrough == "2010-01-06"
    (dg_daily.root / "silver/index/index_factor_pro/trade_date=2010-01-05/part-000.parquet").unlink()
    with pytest.raises(XxmQueryError) as caught:
        build_debug(service, None, period="day", start_date=None, end_date=None, limit=300,
                    now=before_switch.replace(hour=20))
    assert caught.value.code == "XXM_SOURCE_CONTRACT_INVALID"
    entry = next(iter(service.cache.entries.values()))[0]
    assert entry.validated_through == "2010-01-06"


def _literal_minute_window():
    return MinuteSourceWindow(500, 1500, datetime(2020,1,1,10,30,tzinfo=ZONE),
                              datetime(2020,1,1,15,tzinfo=ZONE), (date(2020,1,1),))


def _source_clock(monkeypatch, scenario_now):
    """Only supply the existing default-now argument; keep real SQL and checks."""
    original = IndexDetailXxmQueryService.load_entry

    def load_entry(self, session, *, ts_code, period, now=None,
                   window_rows=None, requested_end=None):
        return original(self, session, ts_code=ts_code, period=period,
                        now=scenario_now if now is None else now,
                        window_rows=window_rows, requested_end=requested_end)

    monkeypatch.setattr(IndexDetailXxmQueryService, "load_entry", load_entry)


@pytest.fixture
def source_db(monkeypatch, request):
    _source_clock(monkeypatch, datetime(2020, 1, 10, 20, tzinfo=ZONE))
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def attach(dbapi, _record):
        dbapi.execute("ATTACH DATABASE ':memory:' AS core_serving")

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE core_serving.index_factor_pro (ts_code TEXT,trade_date DATE,close FLOAT,macd_dif_bfq FLOAT,macd_dea_bfq FLOAT,macd_bfq FLOAT)"))
        conn.execute(text("CREATE TABLE core_serving.trade_calendar (exchange TEXT,trade_date DATE,is_open BOOLEAN,pretrade_date DATE)"))
        begin = date(2020, 1, 1)
        # All source_db requests use Jan1-Jan10, including the appended Jan9 row.
        end = date(2020, 1, 10)
        conn.execute(text("INSERT INTO core_serving.trade_calendar (exchange,trade_date,is_open) VALUES (:exchange,:date,:open)"),
                     [{"exchange": "SSE", "date": (begin + timedelta(days=i)).isoformat(), "open": True} for i in range((end - begin).days + 1)])
        conn.execute(text("INSERT INTO core_serving.index_factor_pro VALUES (:code,:date,:close,:dif,:dea,:hist)"),
                     [{"code": "000001.SH", "date": (begin + timedelta(days=i)).isoformat(), "close": c,
                       "dif": d, "dea": d - h / 2, "hist": h} for i, (c, d, h) in enumerate(VALUES)
                      if i != getattr(request, "param", {}).get("skip_index")])
    monkeypatch.setattr(query_service, "_CACHE", XxmCache())
    yield engine
    engine.dispose()


def build_debug(service, session, *, period, start_date, end_date, limit,
                now=None, ts_code="000001.SH"):
    from src.biz.schemas.wealth.market.index_detail_xxm_debug import XxmDebugResponseDto
    from src.biz.services.wealth.market.index_detail_xxm.debug_projection import project_debug_signal

    return XxmDebugResponseDto.model_validate_json(service.build(
        session, ts_code=ts_code, period=period, start_date=start_date,
        end_date=end_date, limit=limit, now=now, project=project_debug_signal))


def _load_research_signals(session, *, lake_root=None, **params):
    from src.biz.services.wealth.market.index_detail_xxm.debug_projection import project_debug_signal

    return IndexDetailXxmQueryService(lake_root=lake_root).build(session, project=project_debug_signal, **params)


def client(engine, auth=lambda: None):
    app = FastAPI()
    install_exception_handlers(app)

    def session():
        with Session(engine) as session:
            yield session

    app.include_router(build_router(db_dependency=session, auth_dependency=auth, error_factory=WebAppError,
        path="/debug/xxm-signals", load=_load_research_signals, response_model=None), prefix="/api/v1")
    return TestClient(app)


def test_real_router_query_and_window_reference_history_are_consistent(source_db):
    api = client(source_db)
    path = "/api/v1/wealth/market/index-detail/debug/xxm-signals"
    full = api.get(path, params={"tsCode": "000001.SH", "endDate": "2020-01-08", "limit": 8}).json()
    small_response = api.get(path, params={"tsCode": "000001.SH", "startDate": "2020-01-05", "endDate": "2020-01-08", "limit": 3})
    assert small_response.status_code == 200
    small = small_response.json()
    assert small["points"] == full["points"][-3:]
    assert small["debug"]["points"][0]["activeReference"]["startTime"] == "2020-01-01"
    assert small["source"]["startTime"] == "2020-01-01"
    assert small["dataStatus"]["status"] == "READY"
    assert len(small["specHash"]) == 64 and small["source"]["initialHistoryIncomplete"]
    past = api.get(path, params={"tsCode": "000001.SH", "endDate": "2020-01-06", "limit": 8}).json()
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
    ("tsCode=000680.SH",404), ("tsCode=bad",400), ("",400),
])
def test_invalid_and_unsupported_requests_never_produce_a_layer(source_db, suffix, status):
    result = client(source_db).get("/api/v1/wealth/market/index-detail/debug/xxm-signals?" + suffix)
    assert result.status_code == status
    assert result.json()["code"] == ("XXM_NOT_SUPPORTED" if status == 404 else "XXM_REQUEST_INVALID")


@pytest.mark.parametrize("status", [401, 403])
def test_injected_existing_auth_is_required_before_query(source_db, status):
    def denied():
        raise WebAppError(status_code=status, code="AUTH_REQUIRED", message="denied")
    assert client(source_db, denied).get("/api/v1/wealth/market/index-detail/debug/xxm-signals?tsCode=000001.SH").status_code == status


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
    r = api.get("/api/v1/wealth/market/index-detail/debug/xxm-signals?tsCode=000001.SH&endDate=2020-01-02").json()
    assert r["events"] == [] and r["dataStatus"]["status"] == "READY"
    r = api.get("/api/v1/wealth/market/index-detail/debug/xxm-signals?tsCode=000001.SH&endDate=1999-01-01").json()
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


@pytest.mark.parametrize("freq", [30, 60, 90, 120])
def test_minute_router_uses_real_two_stream_reader_and_completed_endpoints(source_db, tmp_path, freq):
    import duckdb
    from src.foundation.clients.local_lake.major_index_mins_contract import (
        GOLD_BAR_COLUMN_SPECS, GOLD_INDICATOR_COLUMN_SPECS, GOLD_PARAMS_KEY,
    )
    # These are isolated test Parquet files, never the formal Lake.
    # The endpoint literals follow the formal Gold production windows, not the
    # product source table being tested below.
    endpoints = tuple(datetime.strptime(slot, "%H:%M").time() for slot in BATCH3_SLOTS[freq])
    values = VALUES * 2 if freq == 30 else VALUES + [VALUES[-1]] if freq == 90 else VALUES
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
                       lake_dependency=lambda:tmp_path,error_factory=WebAppError, path="/debug/minute-xxm-signals", load=_load_research_signals, response_model=None),prefix="/api/v1")
    api = TestClient(app)
    path = "/api/v1/wealth/market/index-detail/debug/minute-xxm-signals"
    end = date(2020,1,1) + timedelta(days=len(values)//len(endpoints)-1)
    response = api.get(path,params={"tsCode":"000001.SH","freq":freq,"endDate":end.isoformat()})
    assert response.status_code == 200
    data = response.json()
    assert data["period"] == f"m{freq}" and data["source"]["indicatorVersion"] == 1
    assert data["meta"]["count"] == len(values) and data["dataStatus"]["status"] == "READY"
    assert [p["close"] for p in data["points"]] == [v[0] for v in values]
    assert any(e["type"] == "STRUCTURE" for e in data["events"])
    for bad in ("freq=15", "freq=60&freq=90", "freq=120&dif_turn_pct=1"):
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
    ordinary = project_xxm_response(internal)
    debug = project_debug_signal(internal)
    assert ordinary.model_dump() == {k:v for k,v in debug.model_dump().items() if k != 'debug'}
    assert [e.type for e in ordinary.events] == ['CANCEL','DULL']
    assert [e.displayOnChart for e in ordinary.events] == [False,True]
    assert len(debug.debug.events)==2
    record=debug.debug.structures[0]
    assert record.formedAt < ordinary.meta.responseStart and record.status=='DISAPPEARED'
    assert record.originWave.priceAt and record.originWave.difAt
    earlier=project_debug_signal(response(source,5))
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
        public = (project_debug_signal if debug else project_xxm_response)(internal)
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
    ordinary = project_xxm_response(internal)
    detailed = project_debug_signal(internal)
    assert ordinary.model_dump() == {k: v for k, v in detailed.model_dump().items() if k != 'debug'}
    for bad in (internal.model_dump(), ordinary, detailed, None, object()):
        with pytest.raises(ValueError, match='InternalXxmResponseDto'):
            (project_debug_signal if debug else project_xxm_response)(bad)


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
        public = project_debug_signal(internal) if debug else projection.project_xxm_response(internal)
        assert [event.type for event in public.events] == ['CANCEL', 'DULL']
        assert [event.displayOnChart for event in public.events] == [False, True]
        assert public.meta.responseStart == '2023-01-12'
    assert projection.project_xxm_response is original
    assert internal.model_dump() == before and collector.requests == {}


def test_public_and_debug_contracts_reject_legacy_bad_types_and_links():
    from copy import deepcopy
    from src.biz.schemas.wealth.market.index_detail_xxm import XxmResponseDto
    from src.biz.schemas.wealth.market.index_detail_xxm_debug import XxmDebugResponseDto
    from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_xxm_response
    from scripts.research.index_market.tests.test_xxm_r4_following_query import entry, response
    from scripts.research.index_market.tests.test_xxm_r4_following import TN
    value=project_debug_signal(response(entry(TN),8)).model_dump()
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
    r=client(source_db).get('/api/v1/wealth/market/index-detail/debug/xxm-signals?tsCode=000001.SH&debug='+raw)
    assert r.status_code==400


def test_real_http_normal_debug_same_facts_and_no_store(source_db,monkeypatch):
    from src.biz.schemas.wealth.market.index_detail_xxm import XxmResponseDto
    encoded=[];original=XxmResponseDto.model_dump_json
    def encode(value,*a,**k):
        body=original(value,*a,**k);encoded.append(body.encode());return body
    monkeypatch.setattr(XxmResponseDto,"model_dump_json",encode)
    c=client(source_db);path='/api/v1/wealth/market/index-detail/debug/xxm-signals'
    normal=c.get(path,params={'tsCode':'000001.SH','endDate':'2020-01-08'})
    debug=c.get(path,params={'tsCode':'000001.SH','endDate':'2020-01-08'})
    assert normal.status_code==debug.status_code==200
    assert normal.headers['cache-control']==debug.headers['cache-control']=='no-store'
    assert encoded==[normal.content,debug.content]
    assert normal.json()==debug.json()
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
        result=read_minutes(reader,ts_code='000001.SH',freq=60,window=_literal_minute_window(),deadline=lambda:3.)
        assert [bar.close for bar in result]==([100,101,102] if mismatch=='none' else [])
        assert all((bar.dif,bar.dea,bar.hist)==(0.,0.,0.) for bar in result)
    else:
        with pytest.raises(XxmSourceError): read_minutes(reader,ts_code='000001.SH',freq=60,window=_literal_minute_window(),deadline=lambda:3.)
    args=reader.read_complete_history_pair.call_args
    assert reader.read_complete_history_pair.call_count==1
    assert args.kwargs==dict(timeout_seconds=3., max_rows=1500,
        time_window=(datetime(2020,1,1,10,30),datetime(2020,1,1,15)),
        bar_value_columns=('close',),indicator_value_columns=('macd_dif','macd_dea','macd'))


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
    with pytest.raises(XxmSourceError): read_minutes(reader,ts_code='000001.SH',freq=60,window=_literal_minute_window(),deadline=lambda:3.)


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
    app.include_router(build_minute_router(db_dependency=session,auth_dependency=lambda:None,lake_dependency=lambda:tmp_path,error_factory=WebAppError, path="/debug/minute-xxm-signals", load=_load_research_signals, response_model=None),prefix='/api/v1')
    with TestClient(app) as api:
        path='/api/v1/wealth/market/index-detail/debug/minute-xxm-signals'
        response=api.get(path,params={'tsCode':'000001.SH','freq':freq,'endDate':'2020-01-01'})
        if change in ('valid','unused_bad','unused_missing','empty'):
            normal=api.get(path,params={'tsCode':'000001.SH','freq':freq,'endDate':'2020-01-01'})
            assert normal.status_code==200
            assert normal.json()==response.json()
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


# P4 batch 3: literal LLD 0.6.6 samples. These are temporary Gold/SQLite
# producers, never the formal Lake. Expected times do not come from ENDPOINTS.
BATCH3_NOW = datetime(2023, 1, 10, 20, tzinfo=ZONE)
BATCH3_SLOTS = {30: ('10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '15:00'),
                60: ('10:30', '11:30', '14:00', '15:00'),
                90: ('11:00', '14:00', '15:00'), 120: ('11:30', '15:00')}


@pytest.fixture
def batch3_db_factory():
    engines = []

    def create(*, begin=date(2023, 1, 3), end=date(2023, 1, 10)):
        engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        engines.append(engine)

        @event.listens_for(engine, 'connect')
        def attach(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS core_serving")

        with engine.begin() as connection:
            # Names/types follow TradeCalendar and IndexFactorPro. Nullable and
            # duplicate rows are allowed here only for explicitly invalid cases.
            connection.execute(text('CREATE TABLE core_serving.trade_calendar(exchange TEXT,trade_date DATE,is_open BOOLEAN,pretrade_date DATE)'))
            connection.execute(text('CREATE TABLE core_serving.index_factor_pro(ts_code TEXT,trade_date DATE,close FLOAT,macd_dif_bfq FLOAT,macd_dea_bfq FLOAT,macd_bfq FLOAT)'))
            days = [begin + timedelta(days=i) for i in range((end - begin).days + 1)]
            connection.execute(text("INSERT INTO core_serving.trade_calendar VALUES('SSE',:day,:opened,NULL)"),
                               [dict(day=day.isoformat(), opened=day.weekday() < 5) for day in days])
        return engine

    yield create
    for engine in engines:
        engine.dispose()


def _batch3_gold(root, freq, rows=None, *, ts_code='000001.SH'):
    import duckdb
    from src.foundation.clients.local_lake.major_index_mins_contract import (
        GOLD_BAR_COLUMN_SPECS, GOLD_INDICATOR_COLUMN_SPECS, GOLD_PARAMS_KEY,
    )
    if rows is None:
        rows = [(f'2023-01-{day:02d}T{slot}:00', 100., 0., 0., 0.)
                for day in (6, 9, 10) for slot in BATCH3_SLOTS[freq]]
    if not rows:
        return
    with duckdb.connect(':memory:') as connection:
        for dataset, specs, folder in (
            ('bars', GOLD_BAR_COLUMN_SPECS, 'quote/major_index_mins'),
            ('indicators', GOLD_INDICATOR_COLUMN_SPECS, 'indicator/major_index_mins_technical'),
        ):
            connection.execute(f'CREATE TABLE {dataset} (' + ','.join(f'{n} {t}' for n, t in specs) + ')')
            for stamp, close, dif, dea, hist in rows:
                value = {name: None for name, _ in specs}
                value.update(ts_code=ts_code, freq=freq, trade_date=date.fromisoformat(stamp[:10]),
                             trade_time=datetime.fromisoformat(stamp), open=close, high=close, low=close,
                             close=close, vol=1., amount=close, exchange='SSE', vwap=close,
                             macd_dif=dif, macd_dea=dea, macd=hist, observation_count=1,
                             params_key=GOLD_PARAMS_KEY, indicator_version=1)
                connection.execute(f'INSERT INTO {dataset} VALUES (' + ','.join('?' for _ in specs) + ')',
                                   [value[name] for name, _ in specs])
            for day in sorted({stamp[:10] for stamp, *_ in rows}):
                target = root / f'gold/{folder}/freq={freq}/trade_date={day}/part-000.parquet'
                target.parent.mkdir(parents=True, exist_ok=True)
                chunk = f'{dataset}_{day.replace("-", "")}'
                connection.execute(f'CREATE TEMP TABLE {chunk} AS SELECT * FROM {dataset} WHERE trade_date=?', [day])
                connection.execute(f'COPY {chunk} TO ? (FORMAT PARQUET)', [str(target)])


def test_p4_batch3_calendar_range_sql_and_errors(batch3_db_factory):
    from unittest.mock import patch
    from src.biz.queries.wealth.market.index_detail_xxm.source import calendar_dates
    engine = batch3_db_factory()
    with Session(engine) as session, patch.object(session, 'execute', wraps=session.execute) as execute:
        assert calendar_dates(session, start=date(2023, 1, 6), end=date(2023, 1, 10)) == (
            date(2023, 1, 6), date(2023, 1, 9), date(2023, 1, 10))
        assert execute.call_count == 1
        statement = execute.call_args.args[0]
        assert list(statement.selected_columns.keys()) == ['trade_date', 'is_open']
        assert list(statement.compile().params.values()) == ['SSE', date(2023, 1, 6), date(2023, 1, 10)]
        execute.reset_mock()
        assert calendar_dates(session, start=date(2023, 1, 10), end=date(2023, 1, 10)) == (date(2023, 1, 10),)
        execute.reset_mock()
        with pytest.raises(XxmSourceError):
            calendar_dates(session, start=date(2023, 1, 10), end=date(2023, 1, 6))
        assert execute.call_count == 0
        for start, end in ((date(2023, 1, 11), date(2023, 1, 11)), (date(2023, 1, 6), date(2023, 1, 11))):
            with pytest.raises(XxmSourceError):
                calendar_dates(session, start=start, end=end)


@pytest.mark.parametrize('freq,count', [(30, 24), (60, 12), (90, 9), (120, 6)])
def test_p4_bounded_real_minute_cold_order_range_and_hot_reuse(batch3_db_factory, tmp_path, monkeypatch, freq, count):
    from unittest.mock import patch
    _batch3_gold(tmp_path, freq)
    service = IndexDetailXxmQueryService(lake_root=tmp_path, cache=XxmCache())
    engine = batch3_db_factory()
    order = []
    original_calendar = query_service.plan_minute_window

    def calendar(*args, **kwargs):
        order.append('calendar')
        assert kwargs['output_rows']==500 and kwargs['requested_end']==datetime(2023,1,10,15,tzinfo=ZONE)
        return original_calendar(*args, **kwargs)

    original_signature = service.reader.history_source_signature
    def signature(request, *, dataset):
        order.append(dataset)
        assert request.ts_code == '000001.SH' and request.freq == freq
        assert request.start_date == date(2023,1,3) and request.end_date == date(2023,1,10)
        assert request.limit==1500
        return original_signature(request, dataset=dataset)

    original_pair = service.reader.read_complete_history_pair
    def pair(*args, **kwargs):
        order.append('pair')
        return original_pair(*args, **kwargs)

    monkeypatch.setattr(query_service, 'plan_minute_window', calendar)
    monkeypatch.setattr(service.reader, 'history_source_signature', signature)
    monkeypatch.setattr(service.reader, 'read_complete_history_pair', pair)
    with Session(engine) as session:
        with service.load_entry(session, period=f'm{freq}', now=BATCH3_NOW, ts_code="000001.SH") as loaded:
            first = loaded[0]
        assert order == ['calendar', 'bars', 'indicators', 'pair']
        assert len(first.raw) == len(first.processed) == count
        assert first.processed[-1].time == '2023-01-10T15:00:00+08:00'
        assert first.events == [] and all(point['ordinaryState'] == 'NONE' for point in first.points)
        saved = first.calculator.snapshot()
        order.clear()
        with patch.object(query_service.XxmCalculator, 'step', side_effect=AssertionError('hot request stepped')):
            with service.load_entry(session, period=f'm{freq}', now=BATCH3_NOW, ts_code="000001.SH") as loaded:
                assert loaded[0] is first
        assert order == ['calendar', 'bars', 'indicators']
        assert first.calculator.snapshot() == saved


@pytest.mark.parametrize('freq',[60,90,120])
def test_p4_bounded_calendar_metadata_change_is_not_revision(batch3_db_factory,tmp_path,monkeypatch,freq):
    from unittest.mock import patch
    _batch3_gold(tmp_path,freq)
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    key=('batch3-narrow',freq)
    with Session(batch3_db_factory()) as session:
        kwargs=dict(key=key,period=f'm{freq}',now=BATCH3_NOW,business_date=BATCH3_NOW.date(),remaining=lambda:4.,
                    requested_end=datetime(2023,1,10,15,tzinfo=ZONE),window_rows=500)
        old,_=service._load_series(session,**kwargs, ts_code="000001.SH")
        stored_key=next(iter(service.cache.entries))
        old=replace(old,open_dates=(date(2023,1,2),*old.open_dates))
        service.cache.put(stored_key,old,check=lambda:4.)
        facts=(old.calculator.snapshot(),list(old.fingerprints),list(old.points),old.open_dates)
        with patch.object(query_service.XxmCalculator,'step',side_effect=AssertionError('calendar change replayed source')):
            new,days=service._load_series(session,**kwargs, ts_code="000001.SH")
            again,_=service._load_series(session,**kwargs, ts_code="000001.SH")
        assert new is not old and again is new
        assert days==tuple(date(2023,1,d) for d in (3,4,5,6,9,10))
        assert new.calculator.snapshot()==facts[0] and new.fingerprints==facts[1] and new.points==facts[2]
        assert (old.calculator.snapshot(),old.fingerprints,old.points,old.open_dates)==facts


@pytest.mark.parametrize('freq',[60,90,120])
@pytest.mark.parametrize('case',['empty','single','partial_first','missing_tail','not_completed'])
def test_p4_bounded_raw_bounds_and_original_completion(batch3_db_factory,tmp_path,monkeypatch,freq,case):
    from unittest.mock import patch
    slots=BATCH3_SLOTS[freq]
    chosen=() if case=='empty' else slots[-1:] if case=='single' else slots[len(slots)//2:] if case=='partial_first' else slots[:-1] if case=='missing_tail' else slots
    rows=[(f'2023-01-10T{slot}:00',100.,0.,0.,0.) for slot in chosen]
    _batch3_gold(tmp_path,freq,rows)
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    now=BATCH3_NOW.replace(hour=10) if case=='not_completed' else BATCH3_NOW
    with Session(batch3_db_factory()) as session,patch.object(query_service,'plan_minute_window',wraps=query_service.plan_minute_window) as calendar:
        with service.load_entry(session,period=f'm{freq}',now=now, ts_code="000001.SH") as (entry,_,days,_): pass
    target_day=9 if case=='not_completed' else 10
    assert calendar.call_count==1 and calendar.call_args.kwargs['requested_end']==datetime(2023,1,target_day,15,tzinfo=ZONE)
    assert len(entry.raw)==len(entry.processed)==(0 if case=='not_completed' else len(rows))
    assert entry.validated_through==f'2023-01-{target_day:02d}T15:00:00+08:00'
    assert days==tuple(date(2023,1,d) for d in ((3,4,5,6,9) if target_day==9 else (3,4,5,6,9,10)))


@pytest.mark.parametrize('clock,business_day,end',[(BATCH3_NOW.replace(hour=19,minute=59),9,10),(BATCH3_NOW,10,10),(BATCH3_NOW.replace(day=15),13,15)])
def test_p4_batch3_real_context_cutover_and_weekend(batch3_db_factory,tmp_path,clock,business_day,end):
    from unittest.mock import patch
    _batch3_gold(tmp_path,60)
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(batch3_db_factory(end=date(2023,1,end))) as session,patch.object(query_service,'plan_minute_window',wraps=query_service.plan_minute_window) as calendar:
        with service.load_entry(session,period='m60',now=clock, ts_code="000001.SH") as (entry,context,days,remaining):
            assert context.trade_date==date(2023,1,business_day)
            assert calendar.call_args.kwargs['requested_end']==datetime(2023,1,business_day,15,tzinfo=ZONE)
            assert entry.processed[-1].time==('2023-01-09T15:00:00+08:00' if business_day==9 else '2023-01-10T15:00:00+08:00')


@pytest.mark.parametrize('freq',[60,90,120])
@pytest.mark.parametrize('kind',['missing_day','missing_middle'])
def test_p4_batch3_real_range_still_rejects_gaps(batch3_db_factory,tmp_path,freq,kind):
    rows=[(f'2023-01-{day:02d}T{slot}:00',100.,0.,0.,0.) for day in (6,9,10) for slot in BATCH3_SLOTS[freq]]
    rows=[row for row in rows if not row[0].startswith('2023-01-09')] if kind=='missing_day' else rows[:1]+rows[2:]
    _batch3_gold(tmp_path,freq,rows)
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(batch3_db_factory()) as session,pytest.raises(XxmQueryError) as failure:
        with service.load_entry(session,period=f'm{freq}',now=BATCH3_NOW, ts_code="000001.SH"):pass
    assert failure.value.code=='XXM_SOURCE_CONTRACT_INVALID' and not service.cache.entries


@pytest.mark.parametrize('stage,names',[('before',[]),('calendar',[]),('bars',['bars']),('indicators',['bars','indicators']),('raw',['bars','indicators'])])
def test_p4_bounded_deadline_stops_at_each_stage(tmp_path,monkeypatch,stage,names):
    from unittest.mock import Mock
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    calls=[];expired=[stage=='before']
    def remaining():
        if expired[0]:raise XxmQueryError('XXM_BUDGET_EXCEEDED','deadline',503)
        return 4.
    def signature(*a,dataset):
        calls.append(dataset)
        if stage==dataset:expired[0]=True
        return dataset
    def raw(reader, *, ts_code, freq, window, deadline):
        assert ts_code == '000001.SH' and freq == 60
        calls.append('raw')
        if stage=='raw':expired[0]=True
        return ()
    def calendar(*a,**k):
        calls.append('calendar')
        if stage=='calendar': expired[0]=True
        return MinuteSourceWindow(500,1500,datetime(2023,1,10,10,30,tzinfo=ZONE),datetime(2023,1,10,15,tzinfo=ZONE),(date(2023,1,10),))
    monkeypatch.setattr(service.reader,'history_source_signature',signature)
    monkeypatch.setattr(query_service,'read_minutes',raw)
    monkeypatch.setattr(query_service,'plan_minute_window',calendar)
    put=Mock(side_effect=AssertionError('partial publish'));monkeypatch.setattr(service.cache,'put',put)
    with pytest.raises(XxmQueryError) as failure:
        service._load_series(None,key=('deadline',),period='m60',now=BATCH3_NOW,business_date=BATCH3_NOW.date(),remaining=remaining, ts_code="000001.SH")
    assert failure.value.code=='XXM_BUDGET_EXCEEDED'
    assert [name for name in calls if name in ('bars','indicators')]==names
    assert ('raw' in calls)==(stage=='raw')
    assert ('calendar' in calls)==(stage!='before') and put.call_count==0


@pytest.mark.parametrize('kind',['source','async_cancel','future_cancel'])
def test_p4_batch3_signature_error_preserves_priority(tmp_path,monkeypatch,kind):
    from asyncio import CancelledError as AsyncCancelled
    from concurrent.futures import CancelledError as FutureCancelled
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    failure=XxmSourceError('source') if kind=='source' else AsyncCancelled() if kind=='async_cancel' else FutureCancelled()
    expired=[False];calls=[]
    def remaining():
        if expired[0]:raise TimeoutError('must not replace original')
        return 4.
    def signature(*a,dataset):
        calls.append(dataset);expired[0]=True;raise failure
    monkeypatch.setattr(service.reader,'history_source_signature',signature)
    monkeypatch.setattr(query_service,'plan_minute_window',lambda *a,**k:MinuteSourceWindow(
        500,1500,datetime(2023,1,10,10,30,tzinfo=ZONE),datetime(2023,1,10,15,tzinfo=ZONE),(date(2023,1,10),)))
    with pytest.raises(type(failure)) as error:
        service._load_series(None,key=('failure',),period='m60',now=BATCH3_NOW,business_date=BATCH3_NOW.date(),remaining=remaining, ts_code="000001.SH")
    assert error.value is failure and calls==['bars'] and not service.cache.entries


def test_p4_batch3_day_keeps_original_range_order_and_values(batch3_db_factory,monkeypatch):
    from unittest.mock import patch
    engine=batch3_db_factory()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO core_serving.index_factor_pro VALUES('000001.SH','2023-01-10',100,0,0,0)"))
    service=IndexDetailXxmQueryService(cache=XxmCache());order=[]
    old_calendar=query_service.calendar_dates;old_read=query_service.read_daily;old_get=service.cache.get
    def calendar(*a,**k):order.append('calendar');assert k==dict(start=date(1990,1,1),end=date(2023,1,10));return old_calendar(*a,**k)
    def read(session, *, ts_code, completed, check):
        order.append('read')
        assert ts_code == '000001.SH'
        return old_read(session, ts_code=ts_code, completed=completed, check=check)
    def get(*a,**k):order.append('cache');return old_get(*a,**k)
    monkeypatch.setattr(query_service,'calendar_dates',calendar);monkeypatch.setattr(query_service,'read_daily',read);monkeypatch.setattr(service.cache,'get',get)
    with Session(engine) as session:
        value=json.loads(service.build(session,period='day',start_date=None,end_date=None,limit=500,now=BATCH3_NOW, ts_code="000001.SH"))
    assert order==['calendar','cache','read'] and value['points'][0]['close']==100.
    assert value['dataStatus']['status']=='READY'


@pytest.mark.parametrize('freq',[60,90,120])
def test_p4_batch3_append_revision_and_calendar_failure_keep_old_facts(batch3_db_factory,tmp_path,monkeypatch,freq):
    from copy import deepcopy
    rows=[(f'2023-01-{day:02d}T{slot}:00',100.,0.,0.,0.) for day in (6,9,10) for slot in BATCH3_SLOTS[freq]]
    size=len(BATCH3_SLOTS[freq]);engine=batch3_db_factory()
    _batch3_gold(tmp_path,freq,rows[:size])
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache());key=('revision',freq)
    steps=[];original=query_service.XxmCalculator.step
    def step(calculator,bar):steps.append(bar.time);return original(calculator,bar)
    monkeypatch.setattr(query_service.XxmCalculator,'step',step)
    def load():
        with Session(engine) as session:
            return service._load_series(session,key=key,period=f'm{freq}',now=BATCH3_NOW,business_date=BATCH3_NOW.date(),remaining=lambda:4.,
                                       requested_end=datetime(2023,1,10,15,tzinfo=ZONE),window_rows=500, ts_code="000001.SH")[0]
    first=load();first_facts=deepcopy(first)
    _batch3_gold(tmp_path,freq,rows[:2*size]);steps.clear()
    second=load()
    assert steps==[r[0]+'+08:00' for r in rows[size:2*size]]
    assert first.calculator.snapshot()==first_facts.calculator.snapshot() and first.points==first_facts.points
    changed=[(rows[0][0],101.,0.,0.,0.),*rows[1:2*size]]
    _batch3_gold(tmp_path,freq,changed);steps.clear()
    revised=load()
    assert len(steps)==2*size and revised.fingerprints!=second.fingerprints
    assert second.points[0]['close']==100. and revised.points[0]['close']==101.
    with engine.begin() as connection:
        connection.execute(text("UPDATE core_serving.trade_calendar SET is_open=0 WHERE trade_date='2023-01-04'"))
    steps.clear()
    calendar_changed=load()
    assert calendar_changed.calculator.snapshot()==revised.calculator.snapshot() and steps==[]
    assert calendar_changed.fingerprints==revised.fingerprints
    revised=calendar_changed
    old_facts=deepcopy(revised)
    with engine.begin() as connection:
        connection.execute(text("UPDATE core_serving.trade_calendar SET is_open=0 WHERE trade_date='2023-01-09'"))
    with pytest.raises(XxmSourceError):load()
    assert next(iter(service.cache.entries.values()))[0] is revised and revised.points==old_facts.points
    assert revised.calculator.snapshot()==old_facts.calculator.snapshot()


@pytest.mark.parametrize('fail',[False,True])
def test_p4_batch3_overlapping_loads_share_actual_range_and_recover(batch3_db_factory,tmp_path,monkeypatch,fail):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from unittest.mock import patch
    _batch3_gold(tmp_path,60)
    engine=batch3_db_factory();service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    entered=Event();joined=Event();release=Event();calls=[];old_calendar=query_service.plan_minute_window
    def calendar(*a,**k):
        calls.append(k);entered.set();assert release.wait(2)
        if fail:raise XxmSourceError('shared source failure')
        return old_calendar(*a,**k)
    monkeypatch.setattr(query_service,'plan_minute_window',calendar)
    def leader():
        with Session(engine) as session:
            return service._load_series(session,key=('shared',),period='m60',now=BATCH3_NOW,business_date=BATCH3_NOW.date(),remaining=lambda:4.,
                                       requested_end=datetime(2023,1,10,15,tzinfo=ZONE),window_rows=500, ts_code="000001.SH")
    def waiter_remaining():joined.set();return 4.
    with patch.object(service.reader,'read_complete_history_pair',wraps=service.reader.read_complete_history_pair) as pair:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(service.cache.loads.load,('flight',),leader,lambda:4.)
            assert entered.wait(2)
            second=pool.submit(service.cache.loads.load,('flight',),lambda:pytest.fail('second source load'),waiter_remaining)
            try:assert joined.wait(2)
            finally:release.set()
            if fail:
                with pytest.raises(XxmSourceError) as a:first.result(timeout=2)
                with pytest.raises(XxmSourceError) as b:second.result(timeout=2)
                assert a.value is b.value and not service.cache.entries
            else:assert first.result(timeout=2) is second.result(timeout=2)
        assert pair.call_count==(0 if fail else 1) and len(calls)==1
        assert calls[0]['requested_end']==datetime(2023,1,10,15,tzinfo=ZONE)
    monkeypatch.setattr(query_service,'plan_minute_window',old_calendar)
    assert service.cache.loads.load(('flight',),leader,lambda:4.)[0].processed


def test_p4_batch3_signal_http_window_never_cuts_loaded_prefix(batch3_db_factory,tmp_path,monkeypatch):
    _batch3_gold(tmp_path,60);engine=batch3_db_factory();cache=XxmCache()
    class FixedDateTime(datetime):
        @classmethod
        def now(cls,tz=None):return BATCH3_NOW.astimezone(tz) if tz else BATCH3_NOW.replace(tzinfo=None)
    monkeypatch.setattr(query_service,'datetime',FixedDateTime);monkeypatch.setattr(query_service,'_CACHE',cache)
    def session():
        with Session(engine) as value:yield value
    app=FastAPI();install_exception_handlers(app)
    app.include_router(build_minute_router(db_dependency=session,auth_dependency=lambda:None,lake_dependency=lambda:tmp_path,error_factory=WebAppError, path="/debug/minute-xxm-signals", load=_load_research_signals, response_model=None),prefix='/api/v1')
    with TestClient(app) as api:
        path='/api/v1/wealth/market/index-detail/debug/minute-xxm-signals'
        empty=api.get(path,params=dict(tsCode='000001.SH',freq=60,endDate='2023-01-03'))
        assert empty.status_code==200 and empty.json()['dataStatus']['status']=='EMPTY' and empty.json()['points']==[]
        normal=api.get(path,params=dict(tsCode='000001.SH',freq=60,limit=2))
        debug=api.get(path,params=dict(tsCode='000001.SH',freq=60,limit=2))
        assert normal.status_code==debug.status_code==200
        assert normal.json()==debug.json()
        assert normal.json()['meta']['count']==2 and normal.json()['dataStatus']['status']=='READY'
    stored=max((value[0] for value in cache.entries.values()),key=lambda entry:len(entry.processed))
    assert len(stored.raw)==len(stored.processed)==12 and stored.raw[0].time=='2023-01-06T10:30:00+08:00'


# LLD 0.9: independent calendar dates/endpoint literals; never formal data.
@pytest.mark.parametrize('freq,n,read_rows,day_limit',[(60,1,1001,252),(60,500,1500,376),
    (90,500,1500,501),(120,500,1500,751),(60,2000,3000,751),
    (30,1,1001,127),(30,500,1500,189),(30,2000,3000,376)])
def test_p4_bounded_plan_uses_one_limited_sql_and_fixed_extra(batch3_db_factory,freq,n,read_rows,day_limit):
    from types import SimpleNamespace
    from unittest.mock import patch
    with Session(batch3_db_factory()) as session,patch.object(session,'execute',wraps=session.execute) as execute:
        plan=plan_minute_window(session,period=f'm{freq}',output_rows=n,
            requested_end=datetime(2023,1,10,15,tzinfo=ZONE),context=SimpleNamespace(trade_date=date(2023,1,10)),
            now=BATCH3_NOW,check=lambda:4.)
        assert (plan.output_rows,plan.read_rows)==(n,read_rows)
        assert plan.start_time==datetime(2023,1,3,*map(int,BATCH3_SLOTS[freq][0].split(':')),tzinfo=ZONE)
        assert plan.end_time==datetime(2023,1,10,15,tzinfo=ZONE)
        assert execute.call_count==1
        sql=str(execute.call_args.args[0]);params=execute.call_args.args[0].compile().params
        assert 'xxm_recent_open_dates' in sql and 'LIMIT' in sql and 'min(' in sql
        assert day_limit in params.values() and date(1990,1,1) not in params.values()


@pytest.mark.parametrize('n',[0,-1,2001,True,1.5])
def test_p4_bounded_plan_rejects_bad_count_without_query(n):
    from unittest.mock import Mock
    session=Mock()
    with pytest.raises(ValueError):
        plan_minute_window(session,period='m60',output_rows=n,requested_end=BATCH3_NOW,
                           context=None,now=BATCH3_NOW,check=lambda:4.)
    session.execute.assert_not_called()


@pytest.mark.parametrize('requested,expected',[(None,datetime(2023,1,10,15,tzinfo=ZONE)),
    (date(2023,1,10),datetime(2023,1,10,15,tzinfo=ZONE)),
    (date(2023,1,11),datetime(2023,1,10,15,tzinfo=ZONE)),
    (datetime(2023,1,6,11,30,tzinfo=ZONE),datetime(2023,1,6,11,30,tzinfo=ZONE))])
def test_p4_bounded_normalization_keeps_intraday_cutoff_without_sql(requested,expected):
    from types import SimpleNamespace
    context=SimpleNamespace(trade_date=date(2023,1,10))
    assert normalize_minute_end(period='m60',requested_end=requested,context=context,now=BATCH3_NOW)==expected
    assert normalize_minute_end(period='m60',requested_end=None,context=context,now=BATCH3_NOW.replace(hour=10)) is None


@pytest.mark.parametrize('end',[None,datetime(1989,12,29,15,tzinfo=ZONE)])
def test_p4_bounded_empty_plan_has_no_calendar_or_files(end):
    from unittest.mock import Mock
    session=Mock()
    plan=plan_minute_window(session,period='m60',output_rows=500,requested_end=end,context=None,
                           now=BATCH3_NOW,check=lambda:4.)
    assert plan==MinuteSourceWindow(500,1500,None,None,())
    session.execute.assert_not_called()


@pytest.mark.parametrize('kind',['absent','middle_gap','null','duplicate'])
def test_p4_bounded_calendar_errors_are_not_empty(batch3_db_factory,kind):
    engine=batch3_db_factory()
    with engine.begin() as c:
        if kind=='absent': c.execute(text("DELETE FROM core_serving.trade_calendar WHERE trade_date='2023-01-10'"))
        elif kind=='middle_gap': c.execute(text("DELETE FROM core_serving.trade_calendar WHERE trade_date='2023-01-04'"))
        elif kind=='null': c.execute(text("UPDATE core_serving.trade_calendar SET is_open=NULL WHERE trade_date='2023-01-06'"))
        else:c.execute(text("INSERT INTO core_serving.trade_calendar VALUES('SSE','2023-01-06',1,NULL)"))
    with Session(engine) as session,pytest.raises(XxmSourceError):
        plan_minute_window(session,period='m60',output_rows=500,requested_end=datetime(2023,1,10,15,tzinfo=ZONE),
                           context=None,now=BATCH3_NOW,check=lambda:4.)


@pytest.mark.parametrize('freq,n,read_rows,input_rows',[(60,1,1001,1044),(60,500,1500,1524),
    (60,2000,3000,3024),(90,500,1500,1524),(120,500,1500,1524),
    (30,500,1500,1528)])
def test_p4_bounded_real_gold_limits_files_sql_steps_and_output(batch3_db_factory,tmp_path,monkeypatch,freq,n,read_rows,input_rows):
    import os
    from src.foundation.clients.local_lake import major_index_mins_reader as reader_module
    begin=date(2020,1,2)
    days=[begin+timedelta(days=i) for i in range(2400) if (begin+timedelta(days=i)).weekday()<5]
    # Fixed input calendar and endpoint literals, not the planner's own output.
    rows=[(day.isoformat()+'T'+slot+':00',100.,0.,0.,0.) for day in days for slot in BATCH3_SLOTS[freq]][:input_rows]
    last=date.fromisoformat(rows[-1][0][:10]);now=datetime.combine(last,datetime.min.time(),ZONE).replace(hour=20)
    engine=batch3_db_factory(begin=begin,end=last)
    _batch3_gold(tmp_path,freq,rows)
    old=tmp_path/f'gold/quote/major_index_mins/freq={freq}/trade_date=1999-01-04/part-000.parquet'
    old.parent.mkdir(parents=True);old.write_text('out-of-range broken fixture must never be opened')
    real_stat=os.stat
    def stat(path,*a,**k):
        assert os.fspath(path)!=str(old),'out-of-window file metadata read'
        return real_stat(path,*a,**k)
    monkeypatch.setattr(reader_module.os,'stat',stat)
    queries=[];original_query=reader_module._query_rows
    def query(*a,**k):
        queries.append(k)
        return original_query(*a,**k)
    monkeypatch.setattr(reader_module,'_query_rows',query)
    steps=[];original_step=query_service.XxmCalculator.step
    def step(calculator,bar):steps.append(bar.time);return original_step(calculator,bar)
    monkeypatch.setattr(query_service.XxmCalculator,'step',step)
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(engine) as session:
        value=build_debug(service,session,period=f'm{freq}',start_date=None,end_date=last,limit=n,now=now)
    stored=next(iter(service.cache.entries.values()))[0]
    assert len(stored.raw)==len(stored.processed)==len(steps)==read_rows
    assert len(value.points)==n and value.meta.count==n
    assert value.source.startTime==rows[-read_rows][0]+'+08:00'
    assert value.points[0].time==rows[-n][0]+'+08:00' and value.source.computedThrough==rows[-1][0]+'+08:00'
    assert value.dataStatus.status=='READY' and len(queries)==2
    bounds=(datetime.fromisoformat(rows[-read_rows][0]),datetime.fromisoformat(rows[-1][0]))
    assert all(q['time_window']==bounds and q['request'].limit==read_rows for q in queries)
    assert all(bounds[0].date()<=p.trade_date<=bounds[1].date() for q in queries for p in q['partitions'])
    assert all(str(p.path)!=str(old) for q in queries for p in q['partitions'])
    old.write_text('outside file was revised; selected source signature must not change')
    with Session(engine) as session:
        warm=build_debug(service,session,period=f'm{freq}',start_date=None,end_date=last,limit=n,now=now)
        assert warm.model_dump()==value.model_dump() and len(queries)==2 and len(steps)==read_rows
        assert next(iter(service.cache.entries.values()))[0] is stored
        # The requested old day is earlier than the current 1500/3000 window.
        historical=build_debug(service,session,period=f'm{freq}',start_date=None,end_date=begin,limit=n,now=now)
    assert historical.dataStatus.status=='READY' and len(historical.points)==min(n,len(BATCH3_SLOTS[freq]))
    assert historical.source.computedThrough==begin.isoformat()+'T15:00:00+08:00'
    assert historical.source.computedThrough<value.source.startTime and len(queries)==4


@pytest.mark.parametrize('freq',[60,90,120])
def test_p4_bounded_history_intraday_and_early_empty(batch3_db_factory,tmp_path,freq):
    from unittest.mock import patch
    _batch3_gold(tmp_path,freq)
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    first_slot=BATCH3_SLOTS[freq][0]
    end=datetime.fromisoformat('2023-01-09T'+first_slot+':00+08:00')
    with Session(batch3_db_factory()) as session:
        with service.load_entry(session,period=f'm{freq}',requested_end=end,now=BATCH3_NOW, ts_code="000001.SH") as (entry,_,_,_):
            assert entry.validated_through==entry.processed[-1].time==end.isoformat()
            assert all(bar.time<=end.isoformat() for bar in entry.raw)
        with patch.object(service.reader,'history_source_signature',side_effect=AssertionError('early signature')),\
             patch.object(service.reader,'read_complete_history_pair',side_effect=AssertionError('early data')):
            result=json.loads(service.build(session,period=f'm{freq}',start_date=None,end_date=date(1989,12,29),limit=500,now=BATCH3_NOW, ts_code="000001.SH"))
        assert result['dataStatus']['status']=='EMPTY' and result['points']==[]


@pytest.mark.parametrize('initial_end',['2023-01-06T15:00:00+08:00','2023-01-10T11:30:00+08:00'])
def test_p4_bounded_changed_plan_rebuilds_even_with_same_actual_first(batch3_db_factory,tmp_path,monkeypatch,initial_end):
    from unittest.mock import patch
    _batch3_gold(tmp_path,60)
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(batch3_db_factory()) as session:
        with service.load_entry(session,period='m60',requested_end=datetime.fromisoformat(initial_end),now=BATCH3_NOW, ts_code="000001.SH") as (old,_,_,_):pass
        before=old.calculator.snapshot();steps=[];restores=[];original=query_service.XxmCalculator.step
        original_restore=query_service.XxmCalculator.restore
        def step(calculator,bar):steps.append(bar.time);return original(calculator,bar)
        def restore(calculator,snapshot):restores.append(calculator);return original_restore(calculator,snapshot)
        monkeypatch.setattr(query_service.XxmCalculator,'step',step)
        monkeypatch.setattr(query_service.XxmCalculator,'restore',restore)
        with patch.object(service.reader,'read_complete_history_pair',wraps=service.reader.read_complete_history_pair) as pair:
            with service.load_entry(session,period='m60',now=BATCH3_NOW, ts_code="000001.SH") as (new,_,_,_):pass
        assert pair.call_count==1 and len(steps)==12 and len(service.cache.entries)==2
        assert old.raw[0].time==new.raw[0].time and old.calculator.snapshot()==before
        assert all(calculator is not new.calculator for calculator in restores)


def test_p4_bounded_counts_and_historical_endpoints_have_separate_entries(batch3_db_factory,tmp_path):
    _batch3_gold(tmp_path,60);service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(batch3_db_factory()) as session:
        entries=[]
        for n,end in ((500,None),(2000,None),(500,None),(500,date(2023,1,6))):
            with service.load_entry(session,period='m60',window_rows=n,requested_end=end,now=BATCH3_NOW, ts_code="000001.SH") as (entry,_,_,_):entries.append(entry)
    assert entries[0] is entries[2] and entries[0] is not entries[1] and entries[0] is not entries[3]
    assert len(service.cache.entries)==3
    assert entries[3].validated_through=='2023-01-06T15:00:00+08:00'


def test_p4_bounded_visible_event_keeps_structure_from_extra_prefix(batch3_db_factory,tmp_path):
    # RC47/52 seven-bar literal sequence: structure at bar6, zero return at7.
    values=((100,-10,-2),(99,-11,-2),(105,-5,2),(98,-9,-2),(97,-9.2,-2),(98,-8.8,-2),(100,-9,0))
    stamps=('2023-01-09T10:30:00','2023-01-09T11:30:00','2023-01-09T14:00:00','2023-01-09T15:00:00',
            '2023-01-10T10:30:00','2023-01-10T11:30:00','2023-01-10T14:00:00')
    rows=[(stamp,float(c),float(d),float(d-h/2),float(h)) for stamp,(c,d,h) in zip(stamps,values,strict=True)]
    _batch3_gold(tmp_path,60,rows);service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(batch3_db_factory()) as session:
        result=build_debug(service,session,period='m60',start_date=None,end_date=date(2023,1,10),limit=1,now=BATCH3_NOW)
    assert len(result.points)==1 and result.points[0].ordinaryState=='DULL'
    assert [(event.type,detail.route) for event,detail in zip(result.events,result.debug.events,strict=True)]==[('DULL','dif_return')]
    record=result.debug.structures[0]
    assert record.formedAt=='2023-01-10T11:30:00+08:00' and record.status=='DISAPPEARED'
    assert result.debug.events[0].relatedStructureId==record.id


@pytest.mark.parametrize('size,count',[(400,400),(1000,500)])
def test_p4_bounded_short_real_source_returns_last_n_without_dropping_extra(batch3_db_factory,tmp_path,size,count):
    begin=date(2023,1,3)
    days=[begin+timedelta(days=i) for i in range(400) if (begin+timedelta(days=i)).weekday()<5]
    rows=[(day.isoformat()+'T'+slot+':00',100.,0.,0.,0.) for day in days for slot in BATCH3_SLOTS[60]][:size]
    _batch3_gold(tmp_path,60,rows)
    end=date.fromisoformat(rows[-1][0][:10]);now=datetime.combine(end,datetime.min.time(),ZONE).replace(hour=20)
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache())
    with Session(batch3_db_factory(end=end)) as session:
        result=build_debug(service,session,period='m60',start_date=None,end_date=end,limit=500,now=now)
    assert result.meta.count==len(result.points)==count and result.dataStatus.status=='READY'
    assert result.points[0].time==rows[-count][0]+'+08:00'
    assert len(next(iter(service.cache.entries.values()))[0].processed)==size


def test_p4_bounded_window_does_not_hide_corrupt_cached_old_structure(batch3_db_factory,tmp_path):
    from copy import deepcopy
    values=((100,-10,-2),(99,-11,-2),(105,-5,2),(98,-9,-2),(97,-9.2,-2),(98,-8.8,-2),(100,-9,0),(99,-9,0))
    stamps=[f'2023-01-{day:02d}T{slot}:00' for day in (9,10) for slot in BATCH3_SLOTS[60]]
    _batch3_gold(tmp_path,60,[(stamp,float(c),float(d),float(d-h/2),float(h)) for stamp,(c,d,h) in zip(stamps,values,strict=True)])
    service=IndexDetailXxmQueryService(lake_root=tmp_path,cache=XxmCache());kwargs=dict(
        period='m60',start_date=None,end_date=date(2023,1,10),limit=1,now=BATCH3_NOW)
    with Session(batch3_db_factory()) as session:
        result=build_debug(service,session,**kwargs)
        assert result.debug.structures==[]  # This old record is outside the output window.
        key,(valid,_)=next(iter(service.cache.entries.items()))
        before=deepcopy(valid.structure_records)
        poisoned=replace(valid,structure_records=deepcopy(valid.structure_records))
        next(iter(poisoned.structure_records.values()))['priceExtreme']=float('nan')
        service.cache.put(key,poisoned,check=lambda:4.)
        with pytest.raises(XxmQueryError) as error:build_debug(service,session,**kwargs)
        assert error.value.code=='XXM_SOURCE_CONTRACT_INVALID'
        assert valid.structure_records==before and service.cache.get(key) is poisoned


# Independent target list approved in the expansion plan. Production still
# reads the majorIndices configuration; tests must not manufacture this list
# through the admission function under test.
EXPANSION_CODES = ('000001.SH', '399001.SZ', '399006.SZ', '000688.SH',
                   '000300.SH', '000905.SH', '000852.SH', '000510.SH', '000016.SH')
EXPANSION_PERIODS = ('day', 'm30', 'm60', 'm90', 'm120')


def _expansion_client(engine, lake_root):
    app = FastAPI()
    install_exception_handlers(app)

    def session():
        with Session(engine) as value:
            yield value

    app.include_router(build_router(db_dependency=session, auth_dependency=lambda: None,
                                   error_factory=WebAppError, path="/debug/xxm-signals", load=_load_research_signals, response_model=None), prefix='/api/v1')
    app.include_router(build_minute_router(db_dependency=session, auth_dependency=lambda: None,
                                          lake_dependency=lambda: lake_root,
                                          error_factory=WebAppError, path="/debug/minute-xxm-signals", load=_load_research_signals, response_model=None), prefix='/api/v1')
    return TestClient(app)


@pytest.mark.parametrize('ts_code', EXPANSION_CODES)
@pytest.mark.parametrize('period', EXPANSION_PERIODS)
def test_expansion_real_signals_bind_nine_codes_and_five_periods(
        batch3_db_factory, tmp_path, monkeypatch, ts_code, period):
    """Real route/query/SQL or paired Gold, using only isolated contract inputs."""
    # All nine approved indices, including 000510.SH, exist in this window.
    _source_clock(monkeypatch, datetime(2025,10,16,21,tzinfo=ZONE))
    monkeypatch.setattr(query_service, '_CACHE', XxmCache())
    engine = batch3_db_factory(begin=date(2025,10,9), end=date(2025,10,16))
    if period == 'day':
        days = ('2025-10-09', '2025-10-10', '2025-10-13', '2025-10-14',
                '2025-10-15', '2025-10-16')
        with engine.begin() as connection:
            # Different first closes catch an accidental fixed 上证 SQL filter.
            connection.execute(text('INSERT INTO core_serving.index_factor_pro '
                'VALUES(:code,:day,:close,:dif,:dea,:hist)'),
                [dict(code=code, day=day, close=c + 20 * index, dif=d, dea=d-h/2, hist=h)
                 for index, code in enumerate(EXPANSION_CODES)
                 for day, (c,d,h) in zip(days, VALUES[:6], strict=True)])
        endpoint = 'xxm-signals'
        params = dict(tsCode=ts_code, period='day', endDate='2025-10-16')
    else:
        freq = int(period[1:])
        offset = 20 * EXPANSION_CODES.index(ts_code)
        stamps = [f'2025-10-{day:02d}T{slot}:00'
                  for day in (14,15,16) for slot in BATCH3_SLOTS[freq]]
        rows = [(stamp, float(c + offset), float(d), float(d-h/2), float(h))
                for stamp, (c,d,h) in zip(stamps, (VALUES * 3)[:len(stamps)], strict=True)]
        _batch3_gold(tmp_path, freq, rows, ts_code=ts_code)
        endpoint = 'minute-xxm-signals'
        params = dict(tsCode=ts_code, freq=freq, endDate='2025-10-16')
    with _expansion_client(engine, tmp_path) as api:
        response = api.get('/api/v1/wealth/market/index-detail/debug/' + endpoint, params=params)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['tsCode'] == ts_code and value['period'] == period
    assert value['dataStatus']['status'] == 'READY'
    assert value['points'] and value['points'][0]['close'] == 100 + 20 * EXPANSION_CODES.index(ts_code)
    assert value['meta']['count'] == (6 if period == 'day' else 3 * len(BATCH3_SLOTS[freq]))
    if period == 'm30':
        assert value['source']['startTime'] == '2025-10-14T10:00:00+08:00'
        assert {point['time'][11:16] for point in value['points']} == set(BATCH3_SLOTS[30])
    assert value['events'] and any(event['type'] == 'STRUCTURE' for event in value['events'])


@pytest.mark.parametrize('ts_code', ['899050.BJ', '000680.SH'])
@pytest.mark.parametrize('period', EXPANSION_PERIODS)
def test_expansion_rejects_excluded_codes_before_context_cache_or_source(
        source_db, tmp_path, monkeypatch, ts_code, period):
    from unittest.mock import Mock
    denied = Mock(side_effect=AssertionError('admission must precede context, cache and source'))
    monkeypatch.setattr(query_service.MarketPageContextQuery, 'resolve_context', denied)
    monkeypatch.setattr(query_service._CACHE, 'get', denied)
    monkeypatch.setattr(query_service._CACHE.loads, 'load', denied)
    monkeypatch.setattr(query_service, 'read_daily', denied)
    monkeypatch.setattr(query_service, 'read_minutes', denied)
    with _expansion_client(source_db, tmp_path) as api:
        minute = period != 'day'
        response = api.get('/api/v1/wealth/market/index-detail/debug/' +
            ('minute-xxm-signals' if minute else 'xxm-signals'),
            params={'tsCode':ts_code, **({'freq':period[1:]} if minute else {'period':'day'})})
    assert response.status_code == 404 and response.json()['code'] == 'XXM_NOT_SUPPORTED'
    service = IndexDetailXxmQueryService(cache=query_service._CACHE)
    with Session(source_db) as session:
        with pytest.raises(XxmQueryError) as error:
            with service.load_entry(session, ts_code=ts_code, period=period, now=BATCH3_NOW):
                pytest.fail('excluded code entered the query')
    assert error.value.status == 404 and error.value.code == 'XXM_NOT_SUPPORTED'
    denied.assert_not_called()


@pytest.mark.parametrize('problem', ['unavailable', 'wrong_payload'])
def test_expansion_configuration_failure_is_query_failure_without_source(
        source_db, monkeypatch, problem):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from src.biz.services.wealth.config import StrategyConfigError, StrategyConfigService

    def broken_config(self, *, module_key, market):
        assert (module_key, market) == ('majorIndices', 'CN_A')
        if problem == 'unavailable':
            raise StrategyConfigError('isolated missing configuration')
        return SimpleNamespace(payload=None, version='invalid-fixture')

    monkeypatch.setattr(StrategyConfigService, 'get_config', broken_config)
    source = Mock(side_effect=AssertionError('configuration failure must precede source'))
    monkeypatch.setattr(query_service.MarketPageContextQuery, 'resolve_context', source)
    response = client(source_db).get('/api/v1/wealth/market/index-detail/debug/xxm-signals',
                                     params={'tsCode':'000001.SH'})
    assert response.status_code == 500 and response.json()['code'] == 'XXM_QUERY_FAILED'
    source.assert_not_called()


def test_expansion_identical_daily_inputs_keep_separate_series_and_event_ids(source_db):
    with source_db.begin() as connection:
        connection.execute(text("INSERT INTO core_serving.index_factor_pro "
            "SELECT '399001.SZ',trade_date,close,macd_dif_bfq,macd_dea_bfq,macd_bfq "
            "FROM core_serving.index_factor_pro WHERE ts_code='000001.SH'"))
    service = IndexDetailXxmQueryService(cache=XxmCache())
    entries = []
    with Session(source_db) as session:
        for code in ('000001.SH', '399001.SZ'):
            with service.load_entry(session, ts_code=code, period='day',
                                    now=datetime(2020,1,10,20,tzinfo=ZONE)) as loaded:
                entries.append(loaded[0])
        for code, saved in zip(('000001.SH', '399001.SZ'), entries, strict=True):
            with service.load_entry(session, ts_code=code, period='day',
                                    now=datetime(2020,1,10,20,tzinfo=ZONE)) as loaded:
                assert loaded[0] is saved
    left, right = entries
    assert left is not right and left.calculator is not right.calculator
    assert left.raw == right.raw and left.fingerprints == right.fingerprints
    assert left.points is not right.points and left.events is not right.events
    assert left.events and right.events
    assert {event['id'] for event in left.events}.isdisjoint(event['id'] for event in right.events)
    assert (left.calculator.ts_code, right.calculator.ts_code) == ('000001.SH', '399001.SZ')
    assert {key[-1] for key in service.cache.entries} == {'000001.SH', '399001.SZ'}


def test_expansion_seventeen_valid_series_share_global_cache_limits_and_recompute(
        batch3_db_factory, monkeypatch):
    """Exercise the unchanged cache with real source-derived SeriesEntry values."""
    from copy import deepcopy

    days = ('2025-10-09','2025-10-10','2025-10-13','2025-10-14','2025-10-15','2025-10-16')
    engines = [batch3_db_factory(begin=date(2025,10,9), end=date(2025,10,16))
               for _ in range(2)]
    for engine in engines:
        with engine.begin() as connection:
            connection.execute(text('INSERT INTO core_serving.index_factor_pro '
                'VALUES(:code,:day,:close,:dif,:dea,:hist)'),
                [dict(code=code,day=day,close=c,dif=d,dea=d-h/2,hist=h)
                 for code in EXPANSION_CODES
                 for day,(c,d,h) in zip(days,VALUES[:6],strict=True)])
    cache = XxmCache()
    services = [IndexDetailXxmQueryService(cache=cache) for _ in engines]
    assert all(service.cache is cache for service in services)
    assert (cache.max_series,cache.max_bytes) == (16,64*1024*1024)
    now = datetime(2025,10,16,21,tzinfo=ZONE)

    def load(origin,code):
        with Session(engines[origin]) as session:
            with services[origin].load_entry(session,ts_code=code,period='day',now=now) as result:
                return result[0]

    # Both connections are valid current source contexts. All entries use the
    # same cache, rather than allocating a separate sixteen-item cache per code.
    requests = [(0,code) for code in EXPANSION_CODES] + [(1,code) for code in EXPANSION_CODES[:8]]
    saved = [load(origin,code) for origin,code in requests]
    keys = [(id(engines[origin]),'daily','day',entry.calculator.spec.spec_hash,code)
            for (origin,code),entry in zip(requests,saved,strict=True)]
    assert len(set(keys)) == 17 and len(cache.entries) == 16
    assert keys[0] not in cache.entries and tuple(cache.entries) == tuple(keys[1:])
    assert {key[-1] for key in cache.entries} == set(EXPANSION_CODES)
    assert 0 < sum(size for _,size in cache.entries.values()) <= 64*1024*1024
    assert all(isinstance(entry,query_service.SeriesEntry) for entry,_ in cache.entries.values())

    first_facts = deepcopy((saved[0].calculator.snapshot(),saved[0].points,saved[0].events,
                           saved[0].structure_records,saved[0].fingerprints))
    steps = [];original_step = query_service.XxmCalculator.step
    def step(calculator,bar):
        steps.append((calculator.ts_code,bar.time))
        return original_step(calculator,bar)
    monkeypatch.setattr(query_service.XxmCalculator,'step',step)
    assert load(*requests[-1]) is saved[-1] and steps == []
    rebuilt = load(*requests[0])
    assert rebuilt is not saved[0] and steps == [('000001.SH',day) for day in days]
    assert (rebuilt.calculator.snapshot(),rebuilt.points,rebuilt.events,
            rebuilt.structure_records,rebuilt.fingerprints) == first_facts
    assert len(cache.entries) == 16 and cache.get(keys[0]) is rebuilt and keys[1] not in cache.entries
    assert 0 < sum(size for _,size in cache.entries.values()) <= cache.max_bytes


@pytest.mark.parametrize('raw_code', ['000001.SH', ' 000001.sh '])
def test_expansion_signals_and_direct_build_use_the_normalized_code(source_db, raw_code):
    api_response = client(source_db).get('/api/v1/wealth/market/index-detail/debug/xxm-signals',
        params={'tsCode':raw_code, 'endDate':'2020-01-08'})
    assert api_response.status_code == 200 and api_response.json()['tsCode'] == '000001.SH'
    with Session(source_db) as session:
        value = json.loads(IndexDetailXxmQueryService(cache=XxmCache()).build(
            session, ts_code=raw_code, period='day', start_date=None,
            end_date=date(2020,1,8), limit=8, now=datetime(2020,1,10,20,tzinfo=ZONE)))
    assert value['tsCode'] == '000001.SH' and value['points']


@pytest.mark.parametrize('source_changed', [False, True])
def test_expansion_wrong_code_series_cache_rejected_before_rebuild(source_db, source_changed):
    """A valid other-code entry put at a wrong key is a cache binding error."""
    from copy import deepcopy
    with source_db.begin() as connection:
        connection.execute(text("INSERT INTO core_serving.index_factor_pro "
            "SELECT '399001.SZ',trade_date,close,macd_dif_bfq,macd_dea_bfq,macd_bfq "
            "FROM core_serving.index_factor_pro WHERE ts_code='000001.SH'"))
    service = IndexDetailXxmQueryService(cache=XxmCache())
    saved = {}
    with Session(source_db) as session:
        for code in ('000001.SH', '399001.SZ'):
            with service.load_entry(session, ts_code=code, period='day',
                                    now=datetime(2020,1,10,20,tzinfo=ZONE)) as loaded:
                saved[code] = loaded[0]
    wrong = saved['399001.SZ']
    facts = deepcopy(wrong.calculator.snapshot())
    target_key = next(key for key in service.cache.entries if key[-1] == '000001.SH')
    service.cache.put(target_key, wrong, check=lambda:4.)
    if source_changed:
        with source_db.begin() as connection:
            connection.execute(text("UPDATE core_serving.index_factor_pro SET close=close+5 "
                                    "WHERE ts_code='000001.SH' AND trade_date='2020-01-01'"))
    with Session(source_db) as session, pytest.raises(XxmQueryError) as error:
        with service.load_entry(session, ts_code='000001.SH', period='day',
                                now=datetime(2020,1,10,20,tzinfo=ZONE)):
            pytest.fail('wrong-code entry was accepted or replaced')
    assert error.value.code == 'XXM_SOURCE_CONTRACT_INVALID'
    assert service.cache.get(target_key) is wrong and wrong.calculator.snapshot() == facts


@pytest.mark.parametrize('period', EXPANSION_PERIODS)
@pytest.mark.parametrize('sign', [1, -1])
def test_expansion_five_period_nonshanghai_normal_debug_projection(period, sign):
    # Approved RC77/93 literal path: price ending is retained internally while
    # same-bar activation is the chart event; the public facts are identical.
    from scripts.research.index_market.tests.test_xxm_r4_following_query import entry, response
    from scripts.research.index_market.tests.test_xxm_r4_following import TF, values
    from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_xxm_response

    source = entry(values(TF + [(102,97,2),(104,96,2)],sign), period, ts_code='399001.SZ')
    internal = response(source,8,limit=1)
    normal = project_xxm_response(internal)
    debug = project_debug_signal(internal)
    assert normal.tsCode == debug.tsCode == '399001.SZ'
    assert normal.period == debug.period == period
    assert normal.model_dump() == {key:value for key,value in debug.model_dump().items() if key != 'debug'}
    assert [event.type for event in normal.events] == ['CANCEL','DULL']
    assert [event.displayOnChart for event in normal.events] == [False,True]
    assert debug.debug.structures[0].status == 'DISAPPEARED'
