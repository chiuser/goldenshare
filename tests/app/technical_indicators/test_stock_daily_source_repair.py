"""Exercise the stock route and kernel against isolated formal-layout Lake inputs."""

from contextlib import asynccontextmanager, contextmanager
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import stock_daily_technical_indicators as wiring
from src.app.web.middleware.access_log import AccessLogMiddleware
from src.biz.api.wealth.market.stock_detail import router
from src.foundation.config.settings import Settings
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.security_serving import Security
from goldenshare_technical_indicators.errors import SourceContractError, SourceReadError
from goldenshare_technical_indicators.service import TechnicalIndicatorService


PATH = "/api/v1/wealth/market/stock-detail/kline"
CODE = "600000.SH"
START = date(2026, 1, 5)
DAYS = tuple(START + timedelta(days=i) for i in range(29) if i % 7 < 5)
OTHER_DAY = date(2026, 2, 3)


def write_table(root, path, rows, schema=None):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), file)
    return file


@pytest.fixture
def source_client(tmp_path, monkeypatch):
    # DG physical schemas follow the stock daily, adjustment factor and stock
    # lifecycle contracts. Prices and adjustment expectations are independent literals.
    root = tmp_path
    for day in (*DAYS, OTHER_DAY):
        write_table(root, f"silver/quote/stock_daily/trade_date={day}/part-000.parquet", [{
            "ts_code": CODE if day in DAYS else "601398.SH", "trade_date": day,
            "open": 20.0, "high": 20.0, "low": 20.0, "close": 20.0, "pre_close": 10.0,
            "change_amount": 0.0, "pct_chg": 0.0, "vol": 100.0, "amount": 1000.0,
        }])
        write_table(root, f"silver/quote/adj_factor/trade_date={day}/part-000.parquet", [{
            "ts_code": CODE, "trade_date": day, "adj_factor": 1.0 if day in DAYS else 2.0,
        }])
    write_table(root, "silver/basic/stock_lifecycle/full/part-000.parquet",
                [{"ts_code": CODE, "list_date": START, "delist_date": None}],
                pa.schema([("ts_code", pa.string()), ("list_date", pa.date32()), ("delist_date", pa.date32())]))
    suspend = pa.schema([("ts_code", pa.string()), ("trade_date", pa.date32()),
                         ("suspend_type", pa.string()), ("suspend_timing", pa.string())])
    for day in DAYS:
        write_table(root, f"silver/quote/stock_suspend_daily/trade_date={day}/part-000.parquet", [], suspend)
    calendar = [
        {"exchange": "SSE", "trade_date": START + timedelta(days=i), "is_open": i % 7 < 5}
        for i in range((OTHER_DAY - START).days + 1)
    ]
    write_table(root, "silver/calendar/trade_calendar/full/part-000.parquet", calendar)

    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        for model in (Security, TradeCalendar):
            model.__table__.create(connection)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as session:
        session.add(Security(ts_code=CODE, name="浦发银行"))
        session.add_all(TradeCalendar(**row) for row in calendar)
        session.commit()

    @contextmanager
    def read_session(session_factory, control):
        control.check_active()
        with session_factory() as session:
            yield session

    original_calculate = TechnicalIndicatorService.calculate
    calculations = []

    def calculate(service, request):
        result = original_calculate(service, request)
        calculations.append(result)
        return result

    monkeypatch.setattr(wiring, "open_stock_daily_read_session", read_session)
    monkeypatch.setattr(TechnicalIndicatorService, "calculate", calculate)

    @contextmanager
    def client_for(env="local", *, source_root=root):
        @asynccontextmanager
        async def lifespan(app):
            settings = Settings(_env_file=None, APP_ENV=env, GOLDENSHARE_LAKE_ROOT=str(source_root))
            async with wiring.stock_daily_technical_indicators_lifespan(
                app, settings_provider=lambda: settings, session_factory_provider=lambda: factory,
            ):
                yield

        app = FastAPI(lifespan=lifespan)
        app.include_router(router, prefix="/api/v1")
        app.add_middleware(AccessLogMiddleware)
        app.dependency_overrides[require_quote_access] = lambda: None
        wiring.install_stock_daily_technical_indicators(app)
        with TestClient(app) as client:
            yield client

    try:
        yield SimpleNamespace(client_for=client_for, calculations=calculations, root=root)
    finally:
        engine.dispose()


def request(client, **params):
    return client.get(PATH, params={"tsCode": CODE, "endDate": "2026-02-02", "debug": 1, **params})


def check_values(payload, days):
    assert [bar["tradeDate"] for bar in payload["bars"]] == [d.isoformat() for d in days]
    assert payload["meta"]["count"] == len(days)
    for bar in payload["bars"]:
        assert (bar["open"], bar["high"], bar["low"], bar["close"], bar["vol"], bar["amount"]) == (10, 10, 10, 10, 100, 1000)
        assert bar["factors"]["macd"] == {"dif": 0, "dea": 0, "macd": 0}
        assert bar["factors"]["kdj"] == {"k": 50, "d": 50, "j": 50}


def test_stock_uses_latest_basis_even_on_an_older_page(source_client):
    with source_client.client_for() as client:
        response = request(client, limit=2, startDate="2026-01-30")
        assert response.status_code == 200, response.text
        older = request(client, limit=1, endDate="2026-01-29")
        assert older.status_code == 200, older.text
    payload = response.json()
    check_values(payload, DAYS[-2:])
    check_values(older.json(), (DAYS[-3],))
    assert all(bar["factors"]["boll"] == {"upper": 10, "middle": 10, "lower": 10} for bar in payload["bars"])
    first, previous = source_client.calculations
    assert first.statistics.source_rows == 21
    assert first.source.id == previous.source.id == "stock_daily"
    assert first.price_adjustment.basis_date == previous.price_adjustment.basis_date == OTHER_DAY
    assert payload["debugInfo"]["sourceTables"] == [
        "core_serving.security_serving", "silver/quote/stock_daily", "silver/quote/adj_factor", "raw/tushare/daily_basic",
    ]


def test_full_short_history_preserves_nulls(source_client):
    with source_client.client_for("dev") as client:
        response = request(client)
        assert response.status_code == 200, response.text
    payload = response.json()
    check_values(payload, DAYS)
    for bar in payload["bars"][:19]:
        assert bar["factors"]["ma"]["ma20"] is None
        assert bar["factors"]["boll"] == {"upper": None, "middle": None, "lower": None}
    assert [bar["factors"]["ma"]["ma20"] for bar in payload["bars"][19:]] == [10, 10]


def test_dg_skips_unrelated_file(source_client):
    with source_client.client_for("dev") as client:
        response = request(client, endDate="2026-02-03", limit=1)
        assert response.status_code == 200, response.text
    check_values(response.json(), DAYS[-1:])
    assert source_client.calculations[0].statistics.source_rows == 21


def test_empty_and_missing_source(source_client):
    with source_client.client_for() as client:
        response = request(client, endDate="1900-01-01")
        assert response.status_code == 200
        assert response.json()["bars"] == []
        assert response.json()["dataStatus"]["status"] == "EMPTY"
    with source_client.client_for(source_root=source_client.root / "absent") as client:
        with pytest.raises(SourceReadError, match="Lake root is not readable"):
            request(client)
    assert not source_client.calculations


@pytest.mark.parametrize("factors", [(), (0.0,), (float("nan"),), (1.0, 1.0)])
def test_no_adjusted_result_is_returned_when_warmup_factor_is_invalid(source_client, factors):
    partition = f"silver/quote/adj_factor/trade_date={DAYS[0]}/part-000.parquet"
    if factors:
        write_table(source_client.root, partition,
                    [{"ts_code": CODE, "trade_date": DAYS[0], "adj_factor": value} for value in factors])
    else:
        (source_client.root / partition).unlink()
    with source_client.client_for() as client:
        with pytest.raises(SourceContractError, match="factor"):
            request(client, limit=1)
    assert not source_client.calculations


@pytest.mark.parametrize("factors", [(0.0,), (2.0, 2.0)])
def test_invalid_latest_basis_is_rejected_outside_page_window(source_client, factors):
    write_table(source_client.root, f"silver/quote/adj_factor/trade_date={OTHER_DAY}/part-000.parquet",
                [{"ts_code": CODE, "trade_date": OTHER_DAY, "adj_factor": value} for value in factors])
    with source_client.client_for() as client:
        with pytest.raises(SourceContractError, match="adjustment factor basis"):
            request(client, limit=1)
    assert not source_client.calculations
