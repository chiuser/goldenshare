from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.app.exceptions import install_exception_handlers
from src.biz.api.wealth.market import index_detail_minutes
from src.biz.queries.wealth.market.index_detail_minutes.index_detail_minutes_query_service import (
    IndexDetailMinutesQueryService,
)
from src.biz.schemas.wealth.market.index_detail_minutes import IndexMinutesResponseDto
from src.biz.services.wealth.market.index_detail_minutes.index_minute_response_policy import (
    enforce_index_minute_response_size,
)
from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteRequestError
from src.foundation.config.local_minute_capability import LocalMinuteCapability


def _write_silver(root: Path) -> None:
    target = root / "silver/quote/major_index_mins/freq=5min/trade_date=2026-08-11/part-000.parquet"
    target.parent.mkdir(parents=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars (
              ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
              open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
              vol DOUBLE, amount DOUBLE, exchange VARCHAR, vwap DOUBLE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO bars VALUES
              ('000001.SH', '5min', TIMESTAMP '2026-08-11 09:30:00', 1, 1.1, 1.2, .9, 10, 100, 'SSE', 1.05),
              ('000001.SH', '5min', TIMESTAMP '2026-08-11 09:35:00', 1.1, 1.2, 1.3, 1, 11, 110, 'SSE', 1.15)
            """
        )
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()


def _write_gold(root: Path) -> None:
    target = root / "gold/indicator/major_index_mins_technical/freq=5/trade_date=2026-08-11/part-000.parquet"
    target.parent.mkdir(parents=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE indicators (
              ts_code VARCHAR, freq SMALLINT, trade_date DATE, trade_time TIMESTAMP,
              ma_5 DOUBLE, ma_10 DOUBLE, ma_20 DOUBLE, ma_30 DOUBLE,
              ma_60 DOUBLE, ma_90 DOUBLE, ma_250 DOUBLE,
              boll_mid DOUBLE, boll_upper DOUBLE, boll_lower DOUBLE,
              macd_dif DOUBLE, macd_dea DOUBLE, macd DOUBLE,
              kdj_k DOUBLE, kdj_d DOUBLE, kdj_j DOUBLE,
              observation_count INTEGER, params_key VARCHAR, indicator_version INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO indicators VALUES (
              '000001.SH', 5, DATE '2026-08-11', TIMESTAMP '2026-08-11 09:35:00',
              1, 2, 3, 4, 5, 6, NULL, 3, 4, 2, .1, .2, -.2,
              50, 45, 60, 120,
              'ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3', 1
            )
            """
        )
        connection.execute("COPY indicators TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()


def _client(monkeypatch: pytest.MonkeyPatch, lake_root: Path) -> TestClient:
    service = IndexDetailMinutesQueryService(lake_root)
    monkeypatch.setattr(index_detail_minutes, "_service", lambda: service)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(index_detail_minutes.router)
    return TestClient(app)


def test_index_minute_api_returns_real_silver_bars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_silver(tmp_path)
    with _client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/wealth/market/index-detail/minutes",
            params={"tsCode": "000001.SH", "freq": "5", "endDate": "2026-08-11", "limit": "1"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataStatus"]["status"] == "READY"
    assert payload["dataStatus"]["code"] is None
    assert payload["meta"]["hasMore"] is True
    assert payload["bars"][0]["tradeTime"] == "2026-08-11T09:35:00+08:00"
    assert "vwap" not in payload["bars"][0]
    assert "preClose" not in payload["bars"][0]


def test_index_indicator_api_freezes_gold_dto_and_missing_gold_does_not_affect_bars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_silver(tmp_path)
    with _client(monkeypatch, tmp_path) as client:
        missing = client.get(
            "/wealth/market/index-detail/minute-indicators",
            params={"tsCode": "000001.SH", "freq": "5", "endDate": "2026-08-11"},
        )
        bars = client.get(
            "/wealth/market/index-detail/minutes",
            params={"tsCode": "000001.SH", "freq": "5", "endDate": "2026-08-11"},
        )
    assert missing.status_code == 200
    assert missing.json()["dataStatus"]["status"] == "DELAYED"
    assert missing.json()["dataStatus"]["code"] == "IM_SOURCE_NOT_READY"
    assert bars.json()["dataStatus"]["status"] == "READY"

    _write_gold(tmp_path)
    with _client(monkeypatch, tmp_path) as client:
        ready = client.get(
            "/wealth/market/index-detail/minute-indicators",
            params={"tsCode": "000001.SH", "freq": "5", "endDate": "2026-08-11"},
        )
    item = ready.json()["items"][0]
    assert item["ma250"] is None
    assert item["observationCount"] == 120
    assert item["indicatorVersion"] == 1


def test_index_minute_api_enforces_universe_and_bse_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch, tmp_path) as client:
        bse = client.get(
            "/wealth/market/index-detail/minutes",
            params={"tsCode": "899050.BJ", "freq": "5", "endDate": "2026-08-11"},
        )
        lake_only = client.get(
            "/wealth/market/index-detail/minutes",
            params={"tsCode": "000680.SH", "freq": "5", "endDate": "2026-08-11"},
        )

    assert bse.status_code == 200
    assert bse.json()["dataStatus"]["status"] == "EMPTY"
    assert bse.json()["dataStatus"]["code"] == "IM_SOURCE_NOT_READY"
    assert lake_only.status_code == 404
    assert lake_only.json()["code"] == "ID_NOT_FOUND"


@pytest.mark.parametrize(
    "query",
    [
        "tsCode=000001.SH&freq=7",
        "tsCode=000001.SH&freq=5&limit=10001",
        "tsCode=000001.SH&freq=5&unknown=1",
        "tsCode=000001.SH&freq=5&freq=15",
        "tsCode=000001.SH&freq=5&startDate=2026-08-12&endDate=2026-08-11",
        "tsCode=000001.SH&freq=5&cursor=",
    ],
)
def test_index_minute_api_strict_invalid_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    with _client(monkeypatch, tmp_path) as client:
        response = client.get(f"/wealth/market/index-detail/minutes?{query}")

    assert response.status_code == 400
    assert response.json()["code"] == "ID_REQUEST_INVALID"


def test_app_router_profile_matrix_does_not_mount_index_minutes_in_prod(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib

    app_router = importlib.import_module("src.app.api.v1.router")

    disabled = LocalMinuteCapability(enabled=False, lake_root=None, reason_code=None)
    monkeypatch.setattr(app_router, "resolve_local_minute_capability", lambda _settings: disabled)
    monkeypatch.setattr(app_router, "resolve_index_minute_capability", lambda _settings: disabled)
    target = APIRouter(prefix="/v1")
    app_router._include_local_minute_router(target)
    paths = {route.path for route in target.routes}
    assert "/v1/wealth/market/index-detail/minutes" not in paths

    enabled = LocalMinuteCapability(enabled=True, lake_root=tmp_path, reason_code=None)
    monkeypatch.setattr(app_router, "resolve_local_minute_capability", lambda _settings: enabled)
    monkeypatch.setattr(app_router, "resolve_index_minute_capability", lambda _settings: enabled)
    local_target = APIRouter(prefix="/v1")
    app_router._include_local_minute_router(local_target)
    local_paths = {route.path for route in local_target.routes}
    assert "/v1/wealth/market/index-detail/minutes" in local_paths
    assert "/v1/wealth/market/index-detail/minute-indicators" in local_paths


def test_index_minute_response_size_guard_rejects_payload_above_5mb() -> None:
    response = IndexMinutesResponseDto.model_validate({
        "tsCode": "000001.SH",
        "freq": 5,
        "bars": [{
            "tsCode": "000001.SH", "freq": 5, "tradeDate": "2026-08-11",
            "tradeTime": "2026-08-11T09:35:00+08:00", "open": 1, "high": 1,
            "low": 1, "close": 1, "vol": 1, "amount": 1, "exchange": "X" * 5_000_000,
        }],
        "meta": {
            "count": 1, "limit": 1, "hasMore": False, "nextCursor": None,
            "startDate": None, "endDate": None, "observedStartDate": "2026-08-11",
            "observedEndDate": "2026-08-11",
        },
        "dataStatus": {
            "status": "READY", "code": None, "expectedEndDate": None,
            "observedEndDate": "2026-08-11", "message": None,
        },
    })

    with pytest.raises(IndexMinuteRequestError, match="5MB"):
        enforce_index_minute_response_size(response)
