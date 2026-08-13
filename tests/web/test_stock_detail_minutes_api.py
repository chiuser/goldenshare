from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.exceptions import install_exception_handlers
from src.biz.api.wealth.market import stock_detail_minutes
from src.biz.queries.wealth.market.stock_detail_minutes.stock_detail_minutes_query_service import (
    StockMinuteQueryService,
)
from src.foundation.clients.local_lake.stock_mins_reader import (
    MinuteReadPage,
    MinuteReadRequest,
    MinuteRequestError,
)
from src.foundation.config.settings import get_settings


def _write_bar(root: Path) -> None:
    target = root / "gold/quote/stk_mins_qfq/freq=5/ts_code=000638.SZ/year=2026/part-000.parquet"
    target.parent.mkdir(parents=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars (
                ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                vol DOUBLE, amount DOUBLE, exchange VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO bars VALUES
            ('000638.SZ', 5, DATE '2026-07-31', TIMESTAMP '2026-07-31 09:35:00', 1, 2, 0.5, 1.5, 10, 100, 'SZSE'),
            ('000638.SZ', 5, DATE '2026-07-31', TIMESTAMP '2026-07-31 09:40:00', 1.5, 2.5, 1, 2, 11, 110, 'SZSE')
            """
        )
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()


def _write_indicator(root: Path) -> None:
    target = root / "gold/indicator/stk_mins_qfq_macd_kdj/freq=5/ts_code=000638.SZ/year=2026/part-000.parquet"
    target.parent.mkdir(parents=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE indicators (
                ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP,
                macd_dif_qfq DOUBLE, macd_dea_qfq DOUBLE, macd_qfq DOUBLE,
                kdj_k_qfq DOUBLE, kdj_d_qfq DOUBLE, kdj_qfq DOUBLE,
                params_key VARCHAR, indicator_version INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO indicators VALUES
            ('000638.SZ', 5, DATE '2026-07-31', TIMESTAMP '2026-07-31 09:35:00', NULL, NULL, NULL, NULL, NULL, NULL, 'p', 1)
            """
        )
        connection.execute("COPY indicators TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()


def _local_client(monkeypatch: pytest.MonkeyPatch, lake_root: Path) -> TestClient:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(lake_root / "missing.env"))
    monkeypatch.setenv("WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED", "true")
    monkeypatch.setenv("GOLDENSHARE_LAKE_ROOT", str(lake_root))
    get_settings.cache_clear()
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(stock_detail_minutes.router)
    return TestClient(app)


def test_minute_api_returns_bars_with_ready_status_and_shanghai_time(tmp_path, monkeypatch) -> None:
    _write_bar(tmp_path)
    with _local_client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/wealth/market/stock-detail/minutes",
            params={
                "tsCode": "000638.SZ",
                "freq": 5,
                "startDate": "2026-07-31",
                "endDate": "2026-07-31",
                "limit": 1,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataStatus"]["status"] == "READY"
    assert payload["meta"]["count"] == 1
    assert payload["meta"]["limit"] == 1
    assert payload["meta"]["hasMore"] is True
    assert payload["bars"][0]["tradeTime"] == "2026-07-31T09:40:00+08:00"
    assert "preClose" not in payload["bars"][0]


def test_minute_indicator_api_preserves_nulls_and_explicit_mapping(tmp_path, monkeypatch) -> None:
    _write_indicator(tmp_path)
    with _local_client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/wealth/market/stock-detail/minute-indicators",
            params={"tsCode": "000638.SZ", "freq": 5, "endDate": "2026-07-31"},
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["macdDif"] is None
    assert item["kdjJ"] is None
    assert item["paramsKey"] == "p"
    assert item["indicatorVersion"] == 1


def test_minute_api_explicit_end_date_with_missing_file_is_delayed(tmp_path, monkeypatch) -> None:
    with _local_client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/wealth/market/stock-detail/minutes",
            params={"tsCode": "000638.SZ", "freq": 5, "endDate": "2026-07-31"},
        )

    assert response.status_code == 200
    assert response.json()["bars"] == []
    assert response.json()["dataStatus"]["status"] == "DELAYED"


def test_minute_api_without_end_date_and_missing_file_is_empty(tmp_path, monkeypatch) -> None:
    with _local_client(monkeypatch, tmp_path) as client:
        response = client.get("/wealth/market/stock-detail/minutes", params={"tsCode": "000638.SZ", "freq": 5})

    assert response.status_code == 200
    assert response.json()["dataStatus"]["status"] == "EMPTY"


def test_minute_api_rejects_invalid_frequency_with_registered_code(tmp_path, monkeypatch) -> None:
    with _local_client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/wealth/market/stock-detail/minutes",
            params={"tsCode": "000638.SZ", "freq": 7},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "SM_REQUEST_INVALID"


class _OversizedReader:
    def read_bars(self, request: MinuteReadRequest) -> MinuteReadPage:
        rows = tuple(
            {
                "ts_code": request.ts_code,
                "freq": request.freq,
                "trade_date": date(2026, 7, 31),
                "trade_time": __import__("datetime").datetime(2026, 7, 31, 9, 30),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "vol": 1.0,
                "amount": 1.0,
                "exchange": "x" * 700,
            }
            for _ in range(10_000)
        )
        return MinuteReadPage(rows, len(rows), False, None, date(2026, 7, 31), date(2026, 7, 31), 1, 1.0)

    def read_indicators(self, request: MinuteReadRequest) -> MinuteReadPage:
        raise AssertionError("not used")


def test_minute_query_service_rejects_response_over_5mb(tmp_path) -> None:
    with pytest.raises(MinuteRequestError) as exc_info:
        StockMinuteQueryService(tmp_path, reader=_OversizedReader()).read_bars(
            ts_code="000638.SZ",
            freq=5,
            start_date=None,
            end_date=date(2026, 7, 31),
            limit=10_000,
            cursor=None,
            debug=False,
        )

    assert getattr(exc_info.value, "code", None) == "SM_REQUEST_INVALID"
