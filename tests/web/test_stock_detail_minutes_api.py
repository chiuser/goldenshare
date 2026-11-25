from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.auth.dependencies import get_current_user_optional
from src.app.auth.dependencies import get_web_settings as auth_settings
from src.app.dependencies import get_db_session
from src.app.dependencies.stock_minute_technical_indicators import run_stock_minute_page
from src.app.exceptions import install_exception_handlers
from src.app.runtime.technical_indicators.composition import create_runtime
from src.biz.api.wealth.market import stock_detail_minute_nine_turn, stock_detail_minutes
from src.foundation.config.settings import Settings
from tests.foundation.technical_indicators.test_stock_minutes_recent import CODE, _write_factor, _write_minutes, minute

PREFIX = "/wealth/market/stock-detail"
DAY = "2026-11-17"


@pytest.fixture
def minute_client(tmp_path):
    settings = Settings(
        _env_file=None, APP_ENV="local", WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=True,
        GOLDENSHARE_LAKE_ROOT=str(tmp_path),
    )

    @asynccontextmanager
    async def lifespan(app):
        runtime = create_runtime(settings)
        app.state.technical_indicator_runtime = runtime
        try:
            yield
        finally:
            await runtime.aclose()

    app = FastAPI(lifespan=lifespan)
    install_exception_handlers(app)
    app.include_router(stock_detail_minutes.build_router(run_page=run_stock_minute_page))
    app.include_router(stock_detail_minute_nine_turn.build_router(run_page=run_stock_minute_page))
    app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_db_session] = lambda: SimpleNamespace(
        info={}, get=lambda _, code: SimpleNamespace(security_type="EQUITY") if code == CODE else None,
    )
    with TestClient(app) as client:
        yield client


def _sample(root):
    _write_minutes(root, 30, 17, [
        (minute(17, 9, 30), 7, 7, 7, 7, 1, 7),
        (minute(17, 10, 0), 8, 10, 8, 9, 2, 18),
        (minute(17, 10, 30), 9, 10, 8, 9, 3, 27),
        (minute(17, 11, 0), 9, 10, 8, 9, 4, 36),
        (minute(17, 11, 30), 10, 11, 9, 10, 5, 50),
        (minute(17, 13, 30), 10, 11, 9, 10, 6, 60),
        (minute(17, 14, 0), 11, 12, 10, 11, 7, 77),
        (minute(17, 14, 30), 11, 12, 10, 11, 8, 88),
        (minute(17, 15, 0), 11, 12, 10, 11, 9, 99),
    ])
    _write_factor(root, 17, 2)
    _write_factor(root, 18, 4)


def _get(client, path, **params):
    return client.get(f"{PREFIX}/{path}", params={"tsCode": CODE, "freq": 90, "endDate": DAY, **params})


def test_stock_minutes_chart_and_standalone_routes_match_one_calculation(minute_client, tmp_path):
    _sample(tmp_path)
    response = _get(minute_client, "minutes", debug=1)
    assert response.status_code == 200, response.text
    body = response.json()
    bars = body["bars"]
    times = [f"{DAY}T{clock}:00+08:00" for clock in ("11:00", "14:00", "15:00")]
    assert [bar["tradeTime"] for bar in bars] == times
    assert [item["tradeTime"] for item in body["indicators"]] == times
    assert (bars[0]["open"], bars[0]["close"], bars[0]["vol"], bars[0]["amount"]) == (3.5, 4.5, 10, 88)
    assert body["meta"]["limit"] == 500
    assert body["dataStatus"]["status"] == "READY"
    assert body["debugInfo"]["sourceDatasets"] == ["silver/quote/stk_mins", "silver/quote/adj_factor"]
    indicators = _get(minute_client, "minute-indicators")
    nine_turn = _get(minute_client, "minute-nine-turn", debug=1)
    assert indicators.status_code == nine_turn.status_code == 200
    assert indicators.json()["items"] == body["indicators"]
    standalone = nine_turn.json()
    assert standalone.pop("debugInfo")["sourceDatasets"] == body["debugInfo"]["sourceDatasets"]
    assert standalone == {key: value for key, value in body["nineTurn"].items() if key != "debugInfo"}
    assert body["nineTurn"]["meta"]["sourceRowCount"] == body["nineTurn"]["meta"]["matchedRowCount"] == 3
    assert body["nineTurn"]["meta"]["missingRowCount"] == 0


def test_stock_minutes_read_a_legacy_cursor_and_preserve_earlier_same_day_bars(minute_client, tmp_path):
    _sample(tmp_path)
    # This is the v1 wire format, with the old bars route's effective endDate.
    cursor = base64.urlsafe_b64encode(json.dumps({
        "v": 1, "dataset": "bars", "tsCode": CODE, "freq": 90, "startDate": None, "endDate": DAY,
        "beforeTradeDate": DAY, "beforeTradeTime": "15:00:00.000000",
    }).encode()).decode().rstrip("=")
    first = _get(minute_client, "minutes", limit=1).json()
    assert first["bars"][0]["tradeTime"] == f"{DAY}T15:00:00+08:00"
    assert first["meta"]["hasMore"]
    page = _get(minute_client, "minutes", limit=1, cursor=cursor)
    assert page.status_code == 200, page.text
    assert page.json()["bars"][0]["tradeTime"] == f"{DAY}T14:00:00+08:00"
    assert page.json()["meta"]["hasMore"]
    assert _get(minute_client, "minutes", cursor=first["meta"]["nextCursor"]).json()["meta"]["count"] == 2
    assert _get(minute_client, "minute-indicators", cursor=cursor).status_code == 400
    nine_cursor = first["nineTurn"]["meta"]["nextCursor"]
    assert _get(minute_client, "minute-nine-turn", cursor=nine_cursor).json()["meta"]["sourceRowCount"] == 2


def test_stock_minutes_short_period_has_no_nine_turn_and_large_limit_returns_actual_count(minute_client, tmp_path):
    _write_minutes(tmp_path, 1, 17, [(minute(17, 9, 30), 8, 9, 7, 8, 2, 16)])
    _write_factor(tmp_path, 17, 2)
    response = _get(minute_client, "minutes", freq=1, limit=10_000)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["limit"] == 10_000
    assert body["meta"]["count"] == 1
    assert len(body["indicators"]) == 1
    assert body["nineTurn"] is None


def test_stock_minutes_empty_delayed_and_source_contract_failure(minute_client, tmp_path):
    folder = tmp_path / "silver/quote/stk_mins/freq=30"
    folder.mkdir(parents=True)
    assert _get(minute_client, "minutes").json()["dataStatus"]["status"] == "DELAYED"
    assert minute_client.get(f"{PREFIX}/minutes", params={"tsCode": CODE, "freq": 90}).json()["dataStatus"]["status"] == "EMPTY"
    _write_minutes(tmp_path, 30, 17, [
        (minute(17, h, m), 8, 8, 8, 8, 2, 16) for h, m in ((14, 30), (15, 0))
    ])
    _write_factor(tmp_path, 18, 2)
    empty = _get(minute_client, "minutes", tsCode="000001.SZ", startDate=DAY, debug=1).json()
    assert empty["dataStatus"]["status"] == "DELAYED"
    assert empty["debugInfo"]["scannedFileCount"] == 1
    assert empty["debugInfo"]["elapsedMs"] > 0
    response = _get(minute_client, "minutes")
    assert response.status_code == 503
    assert response.json()["code"] == "SM_SOURCE_CONTRACT_INVALID"
    nine_turn = _get(minute_client, "minute-nine-turn")
    assert nine_turn.status_code == 500
    assert nine_turn.json()["code"] == "NT_SOURCE_CONTRACT_INVALID"


@pytest.mark.parametrize("params", [{"freq": 2}, {"startDate": "2023-12-31"}, {"startDate": "2026-11-18"}])
def test_stock_minutes_rejects_invalid_frequency_or_date_window(minute_client, params):
    response = _get(minute_client, "minutes", **params)
    assert response.status_code == 400
    assert response.json()["code"] == "SM_REQUEST_INVALID"


def test_stock_minutes_use_existing_auth_and_reject_oversized_final_body(minute_client, tmp_path, monkeypatch):
    from src.app.dependencies import stock_minute_technical_indicators

    monkeypatch.setattr(
        auth_settings(), "quote_api_auth_required", True,
    )
    minute_client.app.dependency_overrides[get_current_user_optional] = lambda: None
    assert _get(minute_client, "minutes").status_code == 401
    minute_client.app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(id=1)
    _sample(tmp_path)
    full = _get(minute_client, "minutes").content
    monkeypatch.setattr(stock_minute_technical_indicators, "MAX_RESPONSE_BYTES", len(full) - 1)
    response = _get(minute_client, "minutes")
    assert response.status_code == 400
    assert response.json()["code"] == "SM_REQUEST_INVALID"
