"""LLD §14.1 ordinary API checks. Real SQLite/route; controlled calculation.

P01/R01–R05 are deliberately not executed here. The temporary serving schema
uses the current EquityDailyBar/Security/TradeCalendar producer definition.
"""
from datetime import date, timedelta
import os
import subprocess
import sys

import pytest

from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security
from tests.stock_daily_kline_helpers import backend_for_client
from tests.web.test_wealth_stock_detail_api import _ensure_stock_detail_tables, _seed_stock_detail_data
from tests.web.test_wealth_stock_detail_api import app_client as app_client


PATH = "/api/v1/wealth/market/stock-detail/kline"


def test_original_limits_and_openapi(app_client, db_session, monkeypatch, record_property):
    _ensure_stock_detail_tables(db_session)
    db_session.add(Security(ts_code="600000.SH", symbol="600000", name="浦发银行",
                            security_type="EQUITY", source="tushare"))
    days = tuple(date(2020, 1, 1) + timedelta(days=i) for i in range(500))
    db_session.add_all(EquityDailyBar(
        ts_code="600000.SH", trade_date=day, open=10,
        high=11, low=9, close=10, pre_close=10, change_amount=0, pct_chg=0,
        vol=100, amount=1000,
    ) for day in days)
    db_session.commit()
    with backend_for_client(app_client, monkeypatch, db_session.get_bind(), record_property) as (_, calls, _):
        for limit in (None, 1, 500):
            params = {"tsCode": "600000.SH", "endDate": days[-1].isoformat()}
            if limit is not None:
                params["limit"] = limit
            if limit == 1:
                params["tradeDate"] = params["endDate"]
            expected_limit = 500 if limit is None else limit
            response = app_client.get(PATH, params=params)
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["meta"]["count"] == payload["meta"]["limit"] == len(payload["bars"]) == expected_limit
            assert [bar["tradeDate"] for bar in payload["bars"]] == [day.isoformat() for day in days[-expected_limit:]]
            assert payload["adjustment"] == "forward" and payload["sourceAdjustment"] == "qfq"
            assert set(payload) == {"pageContext", "stockRef", "period", "adjustment", "sourceAdjustment",
                                    "bars", "meta", "dataStatus", "debugInfo", "nineTurnMarkers"}
            assert payload["nineTurnMarkers"] == []
            assert response.headers["content-type"] == "application/json"
        assert len(calls) == 3
        for item in calls:
            assert len(item.calculations) == 13
            assert sum(spec["calculation_id"] == "nineturn" for spec in item.calculations) == 1
            assert sum(spec["calculation_id"] == "price" for spec in item.calculations) == 1
    operation = app_client.app.openapi()["paths"][PATH]["get"]
    params = {item["name"]: item["schema"] for item in operation["parameters"] if item["in"] == "query"}
    assert set(params) == {"tsCode", "period", "adjustment", "tradeDate", "startDate", "endDate", "limit", "debug"}
    # The shared day/week/month route has no static limit default; day resolves
    # None to 500 in the route, already asserted by the real requests above.
    assert params["limit"]["anyOf"] and params["period"]["default"] == "day"
    assert params["adjustment"]["default"] == "forward"
    outputs = operation["responses"]["200"]["content"]["application/json"]["schema"]["anyOf"]
    assert {item["$ref"].rsplit("/", 1)[-1] for item in outputs} == {
        "StockDetailKlineResponseDto", "StockDetailPeriodKlineResponseDto",
    }
    schemas = app_client.app.openapi()["components"]["schemas"]
    for model in ("StockDetailKlineResponseDto", "StockDetailPeriodKlineResponseDto"):
        assert "nineTurnMarkers" in schemas[model]["required"]


def test_prewait_errors_unknown_and_empty(app_client, db_session, monkeypatch, record_property):
    _seed_stock_detail_data(db_session)
    with backend_for_client(app_client, monkeypatch, db_session.get_bind(), record_property) as (backend, calls, controls):
        original = backend.runtime.admission.acquire
        admissions = []
        async def acquire(control):
            admissions.append(control)
            return await original(control)
        monkeypatch.setattr(backend.runtime.admission, "acquire", acquire)
        for changes in ({"period": "quarter"}, {"adjustment": "qfq"}, {"limit": 0}, {"limit": 501},
                        {"startDate": "2026-05-29", "endDate": "2026-05-28"}):
            response = app_client.get(PATH, params={"tsCode": "603806.SH", **changes})
            assert response.status_code == 400 and response.json()["code"] == "400001"
        assert not admissions and not calls and len(controls) == 5
        unknown = app_client.get(PATH, params={"tsCode": "UNKNOWN", "endDate": "2026-05-29"})
        assert unknown.status_code == 404 and unknown.json()["code"] == "404001"
        assert len(admissions) == 1 and not calls
        empty = app_client.get(PATH, params={"tsCode": "603806.SH", "endDate": "1900-01-01"})
        assert empty.status_code == 200 and empty.json()["bars"] == []
        assert empty.json()["dataStatus"]["status"] == "EMPTY" and not calls
        assert empty.json()["nineTurnMarkers"] == []
        normal = app_client.get(PATH, params={"tsCode": " 603806.sh ", "endDate": "2026-05-29", "limit": 2, "sql": "ignored"})
        assert normal.status_code == 200 and len(normal.json()["bars"]) == 2
        assert len(admissions) == 3 and len(calls) == 1
        assert len(controls) == 8 and not backend.runtime.admission.active_leases


@pytest.mark.parametrize("debug", [False, True])
def test_prod_daily_maps_nine_turn_from_the_single_calculation(app_client, db_session, monkeypatch, record_property, debug):
    # The real Prod route, selection query and assembler consume literal counts;
    # backend_for_client substitutes only calculation/Control/PG resource ownership.
    _seed_stock_detail_data(db_session)
    with backend_for_client(app_client, monkeypatch, db_session.get_bind(), record_property,
                            overrides={("nineturn", "up_count"): 9}) as (_, calls, _):
        response = app_client.get(PATH, params={"tsCode": "603806.SH", "endDate": "2026-05-29", "debug": int(debug)})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(calls) == 1
    assert payload["nineTurnMarkers"] == [
        {"tradeDate": day, "tradeTime": None, "direction": "UP", "sequenceNumber": 9, "completed": True}
        for day in ("2026-05-28", "2026-05-29")
    ]
    assert "quote" not in payload and "nextEndDate" not in payload["meta"]
    assert (payload["debugInfo"] is not None) == debug


def test_prod_page_init_keeps_daily_nine_turn_capability_and_prior_quote(app_client, db_session):
    _ensure_stock_detail_tables(db_session)
    previous = date(2026, 8, 12)
    anchor = date(2026, 8, 13)
    db_session.add_all([
        Security(ts_code="000001.SZ", symbol="000001", name="平安银行", security_type="EQUITY"),
        TradeCalendar(exchange="SSE", trade_date=previous, is_open=True, pretrade_date=date(2026, 8, 11)),
        TradeCalendar(exchange="SSE", trade_date=anchor, is_open=True, pretrade_date=previous),
        EquityFactorPro(ts_code="000001.SZ", trade_date=previous, close_qfq=11,
                        turnover_rate=99, volume_ratio=99, source="tushare"),
        EquityDailyBasic(ts_code="000001.SZ", trade_date=previous, turnover_rate=0, volume_ratio=None),
        EquityDailyBasic(ts_code="000001.SZ", trade_date=anchor, turnover_rate=1, volume_ratio=2),
    ])
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/page-init",
        params={"tsCode": "000001.SZ", "tradeDate": anchor.isoformat()},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["quote"]["tradeDate"] == previous.isoformat()
    assert payload["quote"]["turnoverRate"] == 0
    assert payload["quote"]["volumeRatio"] is None
    assert payload["capabilities"]["supportsNineTurn"] is True
    assert payload["capabilities"]["nineTurnPeriods"] == ["day"]


@pytest.mark.parametrize("environment", ["local", "prod"])
def test_main_router_retires_only_the_stock_daily_nine_turn_endpoint(tmp_path, environment):
    # The main router snapshots its profile at import. A fresh process gives
    # each case the real aggregation without starting the Web lifespan.
    env_file = tmp_path / "test.env"
    env_file.write_text("")
    script = """
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.api.v1.router import router

stock = "/api/v1/wealth/market/stock-detail"
index = "/api/v1/wealth/market/index-detail"
app = FastAPI()
app.include_router(router, prefix="/api")
with TestClient(app) as client:
    paths = client.get("/openapi.json").json()["paths"]
    assert client.get(f"{stock}/nine-turn", params={"tsCode": "000001.SZ"}).status_code == 404
    assert f"{stock}/nine-turn" not in paths
    assert f"{stock}/kline" in paths
    assert f"{index}/nine-turn" in paths
    schema = paths[f"{stock}/page-init"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    expected = "LocalStockDetailPageInitResponseDto" if sys.argv[1] == "local" else "StockDetailPageInitResponseDto"
    assert schema["$ref"].rsplit("/", 1)[-1] == expected
    if sys.argv[1] == "prod":
        minute = f"{stock}/minute-nine-turn"
        assert minute not in paths
        assert client.get(minute, params={"tsCode": "000001.SZ", "freq": 30}).status_code == 404
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, environment],
        env={
            **os.environ,
            "APP_ENV": environment,
            "GOLDENSHARE_ENV_FILE": str(env_file),
            "GOLDENSHARE_LAKE_ROOT": str(tmp_path),
            "WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED": "false",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
