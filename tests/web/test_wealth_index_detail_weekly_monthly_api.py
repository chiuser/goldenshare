from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy.orm import sessionmaker

from goldenshare_technical_indicators.errors import SourceReadError
from goldenshare_technical_indicators.executor import DuckDBExecutor
from src.app.dependencies import index_period_technical_indicators as execution
from src.app.dependencies.db import get_db_session
from src.app.exceptions import install_exception_handlers
from src.app.runtime.technical_indicators.composition import create_runtime
from src.biz.api.wealth.market import index_detail, index_detail_debug
from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
from src.foundation.config.settings import Settings, get_settings
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from tests.wealth_watchlist_postgres_support import isolated_postgres


PATH = "/api/v1/wealth/market/index-detail"
CODE = "000001.SH"
OTHER = "899050.BJ"
GAP = "000300.SH"
WEEKS = (("09-21", "09-24", 100), ("09-28", "09-30", 104), ("10-08", "10-09", 108))
MONTHS = (("09-01", "09-30", 104), ("10-08", "10-09", 108))


def day(value):
    return date.fromisoformat("2026-" + value)


def calendar_rows():
    start, end = day("09-01"), day("10-12")
    closed = {day("09-25"), *(day("10-01") + timedelta(days=i) for i in range(7))}
    previous = None
    for offset in range((end - start).days + 1):
        current = start + timedelta(days=offset)
        opened = current.weekday() < 5 and current not in closed
        yield dict(exchange="SSE", trade_date=current, is_open=opened, pretrade_date=previous)
        if opened:
            previous = current


def period_rows(values, *, dg):
    # Dates and column types follow the audited Silver footer and the Serving models.
    # Use independently chosen prices/volume and the documented conversion factors.
    for code in (CODE, GAP, OTHER):
        for start, cutoff, close in values:
            if values is WEEKS and code == GAP and cutoff == "09-30":
                continue
            yield dict(
                ts_code=code, period_start_date=day(start), trade_date=day(cutoff),
                open=Decimal(close - 1), high=Decimal(close + 2), low=Decimal(close - 2), close=Decimal(close),
                pre_close=Decimal("100"), change_amount=Decimal(close - 100),
                pct_chg=Decimal(close - 100) / (1 if dg else 100),
                vol=Decimal("12.25" if dg else "1225.00"), amount=Decimal("36.125" if dg else "36125.00"),
            )


def write_table(path, table):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, row_group_size=2)


@pytest.fixture(params=("local", "prod"))
def period_client(request, tmp_path, monkeypatch):
    dg = request.param == "local"
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
    settings = Settings(_env_file=None, APP_ENV=request.param, GOLDENSHARE_LAKE_ROOT=str(tmp_path),
                        TECHNICAL_INDICATOR_BATCH_ROWS=2)
    calendars = list(calendar_rows())
    identities = [dict(ts_code=code, name=name, market=market, publisher=market, category="综合")
                  for code, name, market in ((CODE, "上证指数", "SSE"), (GAP, "沪深300", "SSE"), (OTHER, "北证50", "BSE"))]
    db_dir = tmp_path / "pg"
    db_dir.mkdir()
    with isolated_postgres(db_dir) as engine:
        sessions = sessionmaker(engine)
        monkeypatch.setattr(execution, "get_session_factory", lambda: sessions)
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA core_serving")
            for model in (TradeCalendar, IndexBasic, IndexFactorPro, IndexDailyServing,
                          IndexWeeklyServing, IndexMonthlyServing):
                model.__table__.create(connection)
            connection.execute(TradeCalendar.__table__.insert(), calendars)
            connection.execute(IndexBasic.__table__.insert(), identities)
            connection.execute(IndexDailyServing.__table__.insert(), [{"ts_code": CODE, "trade_date": day("10-09")}])
            if not dg:
                connection.execute(IndexWeeklyServing.__table__.insert(), list(period_rows(WEEKS, dg=False)))
                connection.execute(IndexMonthlyServing.__table__.insert(), list(period_rows(MONTHS, dg=False)))
        if dg:
            write_table(tmp_path / "silver/index_basic/full/part-000.parquet", pa.Table.from_pylist(identities))
            write_table(tmp_path / "silver/calendar/trade_calendar/full/part-000.parquet", pa.Table.from_pylist(calendars))
            price_schema = pa.schema([
                ("ts_code", pa.string()), ("period_start_date", pa.date32()), ("trade_date", pa.date32()),
                *((name, pa.decimal128(18, 4)) for name in ("open", "high", "low", "close", "pre_close", "change_amount")),
                ("pct_chg", pa.decimal128(12, 4)), ("vol", pa.decimal128(20, 6)), ("amount", pa.decimal128(20, 7)),
            ])
            for name, values in (("index_weekly", WEEKS), ("index_monthly", MONTHS)):
                write_table(tmp_path / f"silver/{name}/full/part-000.parquet",
                            pa.Table.from_pylist(list(period_rows(values, dg=True)), schema=price_schema))
        calls, materializations = [], []
        method = "calculate_with_source" if dg else "calculate"
        original = getattr(execution.TechnicalIndicatorService, method)

        def calculate(self, request):
            result = original(self, request)
            calls.append(request)
            return result

        monkeypatch.setattr(execution.TechnicalIndicatorService, method, calculate)
        execute = DuckDBExecutor.execute

        def observe_materialization(executor, step):
            if step.name == "materialize_index_period":
                materializations.append(step.bindings)
            return execute(executor, step)

        monkeypatch.setattr(DuckDBExecutor, "execute", observe_materialization)

        @asynccontextmanager
        async def lifespan(app):
            runtime = create_runtime(settings, session_factory=sessions)
            if dg:
                def reject_second_read(*args, **kwargs):
                    pytest.fail("DG page bounds and auxiliary fields must come from the retained prices")

                monkeypatch.setattr(runtime.source, "index_period_page", reject_second_read)
                monkeypatch.setattr(runtime.source, "index_period_boundary", reject_second_read)
            app.state.technical_indicator_runtime = runtime
            try:
                yield
            finally:
                await runtime.aclose()

        def session():
            with sessions() as active:
                yield active

        app = FastAPI(lifespan=lifespan)
        app.dependency_overrides[get_db_session] = session
        install_exception_handlers(app)
        options = dict(run_period_kline=execution.run_index_period_kline, period_enabled=execution.supports_index_period_kline)
        app.include_router(index_detail.build_router(**options), prefix="/api/v1")
        app.include_router(index_detail_debug.build_router(**options), prefix="/api/v1")
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, app=app, calls=calls, engine=engine, dg=dg,
                                  materializations=materializations)
        assert engine.pool.checkedout() == 0


def kline(client, *, period="week", end="10-09", debug=False, **params):
    query = {"tsCode": CODE, "period": period, **params}
    if end is not None:
        query["endDate"] = str(day(end))
    return client.get(PATH + ("/debug/kline" if debug else "/kline"), params=query)


def test_weekly_pages_and_monthly_use_actual_dates_and_daily_units(period_client):
    client = period_client.client
    first = kline(client, limit=2)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["period"] == "week"
    assert body["meta"] == {"count": 2, "limit": 2, "startDate": None,
                            "endDate": "2026-10-09", "nextEndDate": "2026-09-24"}
    assert [bar["tradeDate"] for bar in body["bars"]] == ["2026-09-30", "2026-10-09"]
    bar = body["bars"][-1]
    assert [bar[name] for name in ("open", "high", "low", "close")] == [107, 110, 106, 108]
    assert [bar[name] for name in ("vol", "amount", "preClose", "change", "changePct", "amplitude")] == [
        12.25, 36.125, 100, 8, 8, 4,
    ]
    assert bar["factors"]["ma"]["ma250"] is None
    assert bar["factors"]["boll"] == {"upper": None, "middle": None, "lower": None}
    assert bar["factors"]["macd"]["dif"] > 0
    assert set(bar["factors"]["kdj"]) == {"k", "d", "j"}
    assert body["dataStatus"]["status"] == "READY"
    assert body["debugInfo"] is None
    assert len(period_client.calls) == 1
    if period_client.dg:
        [(period, path, ts_code)] = period_client.materializations
        assert (period, ts_code) == ("week", CODE)
        assert path.endswith("silver/index_weekly/full/part-000.parquet")
        assert period_client.calls[0].latest_rows == 2

    older = kline(client, end="09-24", limit=1).json()
    assert older["bars"][0]["tradeDate"] == "2026-09-24"
    assert older["meta"]["nextEndDate"] is None
    assert older["bars"][0]["factors"]["macd"] == {"dif": 0.0, "dea": 0.0, "macd": 0.0}
    month = kline(client, period="month", end=None).json()
    assert month["period"] == "month" and month["meta"]["limit"] == 300
    assert [bar["tradeDate"] for bar in month["bars"]] == ["2026-09-30", "2026-10-09"]
    assert month["meta"]["nextEndDate"] is None
    bounded = kline(client, startDate="2026-09-30").json()
    assert [bar["tradeDate"] for bar in bounded["bars"]] == ["2026-09-30", "2026-10-09"]
    assert bounded["meta"]["nextEndDate"] is None
    assert len(period_client.calls) == 4


def test_empty_delayed_and_wrong_dates(period_client, monkeypatch):
    client = period_client.client
    for period in ("week", "month"):
        empty = kline(client, period=period, end="09-18" if period == "week" else "08-31", debug=True)
        assert empty.status_code == 200, empty.text
        body = empty.json()
        assert body["bars"] == [] and body["meta"]["nextEndDate"] is None
        assert body["dataStatus"]["status"] == "EMPTY"
        assert body["debugInfo"]["exceptions"][0]["code"] == "ID_SOURCE_EMPTY"
        assert ("周线" if period == "week" else "月线") in body["debugInfo"]["exceptions"][0]["message"]
    assert len(period_client.calls) == (2 if period_client.dg else 0)
    for period in ("week", "month"):
        delayed = kline(client, period=period, end="10-12", debug=True, limit=1)
        assert delayed.status_code == 200, delayed.text
        body = delayed.json()
        assert body["dataStatus"] == {"status": "DELAYED", "expectedTradeDate": "2026-10-12",
                                      "observedTradeDate": "2026-10-09"}
        assert body["meta"]["nextEndDate"] == "2026-09-30"
        assert body["debugInfo"]["exceptions"][0]["code"] == "ID_SOURCE_DELAYED"
        assert ("周线" if period == "week" else "月线") in body["debugInfo"]["exceptions"][0]["message"]
    missing_version = kline(client, period="week", end="10-08", startDate="2026-10-08")
    assert missing_version.status_code == 500 and missing_version.json()["code"] == "ID_QUERY_FAILED"
    missing_bar = kline(client, tsCode=GAP)
    assert missing_bar.status_code == 500 and missing_bar.json()["code"] == "ID_QUERY_FAILED"

    method = "calculate_with_source" if period_client.dg else "calculate"
    calculate = getattr(execution.TechnicalIndicatorService, method)

    def misalign(self, request):
        result = calculate(self, request)
        if period_client.dg:
            return replace(result, result=replace(result.result, source_as_of=(day("10-08"),)))
        return replace(result, source_as_of=(day("10-08"),))

    monkeypatch.setattr(execution.TechnicalIndicatorService, method, misalign)
    response = kline(client, limit=1)
    assert response.status_code == 500 and response.json()["code"] == "ID_QUERY_FAILED"
    assert period_client.engine.pool.checkedout() == 0


def test_selection_failure_and_cancellation_release_resources(period_client, monkeypatch):
    source = period_client.app.state.technical_indicator_runtime.source
    owner, method = ((LakePriceLocator, "_read_rows") if period_client.dg else
                     (source, "index_period_page"))
    original = getattr(owner, method)
    cleanup = DuckDBExecutor.cleanup_drop
    dropped = []

    def record_cleanup(executor, name):
        cleanup(executor, name)
        if name == "ti_index_period_rows":
            dropped.append(name)

    monkeypatch.setattr(DuckDBExecutor, "cleanup_drop", record_cleanup)

    def fail(*args, **kwargs):
        raise SourceReadError("fixture source read failed")

    def cancel(*args, **kwargs):
        if period_client.dg:
            args[0].control.request_stop("cancel")
            return original(*args, **kwargs)
        page = original(*args, **kwargs)
        kwargs["control"].request_stop("cancel")
        return page

    for interrupt in (fail, cancel):
        with monkeypatch.context() as patch:
            patch.setattr(owner, method, interrupt)
            response = kline(period_client.client)
            assert response.status_code == 500 and response.json()["code"] == "ID_QUERY_FAILED"
        assert not period_client.calls
        assert period_client.engine.pool.checkedout() == 0
    assert kline(period_client.client).status_code == 200
    assert len(period_client.calls) == 1
    if period_client.dg:
        assert len(dropped) == 2


def test_route_capability_validation_and_existing_auth(period_client, monkeypatch):
    client = period_client.client
    for path in ("/page-init", "/debug/page-init"):
        response = client.get(PATH + path, params={"tsCode": CODE, "tradeDate": "2026-09-18"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["chartDefaults"]["availablePeriods"][:3] == ["day", "week", "month"]
        assert payload["chartDefaults"]["defaultPeriod"] == "day"
        assert payload["capabilities"]["supportsWeeklyMonthly"] is True
        assert payload["capabilities"]["nineTurnPeriods"] == ["day"]
    assert kline(client, tsCode=OTHER, limit=1).status_code == 200
    for params in ({"limit": 501}, {"limit": 0}, {"period": "m5"}, {"startDate": "2026-10-12"}, {"adjustment": "none"}):
        response = kline(client, **params)
        assert response.status_code == 400 and response.json()["code"] == "ID_REQUEST_INVALID"
    assert kline(client, tsCode="999999.SH").status_code == 404

    with monkeypatch.context() as patch:
        patch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
        get_settings.cache_clear()
        assert kline(client).status_code == 401
    get_settings.cache_clear()
    period_client.app.state.technical_indicator_runtime = None
    rejected = kline(client)
    assert rejected.status_code == 400 and rejected.json()["code"] == "ID_REQUEST_INVALID"
    disabled = client.get(PATH + "/page-init", params={"tsCode": CODE, "tradeDate": "2026-09-18"}).json()
    assert disabled["capabilities"]["supportsWeeklyMonthly"] is False
    assert "week" not in disabled["chartDefaults"]["availablePeriods"]
