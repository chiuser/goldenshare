from __future__ import annotations

from pathlib import Path

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.biz.api.wealth.market import stock_detail_trend_channel
from src.foundation.config.stock_daily_trend_channel_capability import (
    StockDailyTrendChannelCapability,
)
from src.foundation.clients.local_lake.stock_daily_trend_channel_reader import (
    StockDailyTrendChannelLakeReader,
    StockDailyTrendChannelReadError,
)
from src.foundation.models.core_serving.security_serving import Security


def _write_partition(root: Path, trade_date: str) -> None:
    target = (
        root
        / "gold/indicator/stock_daily_trend_channel"
        / f"trade_date={trade_date}"
        / "part-000.parquet"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE result AS SELECT
              '000001.SZ'::VARCHAR AS ts_code,
              ?::DATE AS trade_date,
              10.0::DOUBLE AS open, 11.0::DOUBLE AS high,
              9.0::DOUBLE AS low, 10.5::DOUBLE AS close,
              12.0::DOUBLE AS short_upper, 9.5::DOUBLE AS short_lower,
              'INSIDE'::VARCHAR AS short_position, 'UP'::VARCHAR AS short_state,
              13.0::DOUBLE AS long_upper, 8.5::DOUBLE AS long_lower,
              'INSIDE'::VARCHAR AS long_position, 'DOWN'::VARCHAR AS long_state,
              'UP_DOWN'::VARCHAR AS combined_state,
              'stock-daily-trend-channel-v1'::VARCHAR AS formula_version
            """,
            [trade_date],
        )
        connection.execute("COPY result TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()


def _client(root: Path, monkeypatch, db_session) -> TestClient:
    monkeypatch.setattr(
        "src.foundation.clients.local_lake.stock_daily_trend_channel_reader.FORMAL_LAKE_ROOT",
        root,
    )
    monkeypatch.setattr(
        stock_detail_trend_channel,
        "resolve_stock_daily_trend_channel_capability",
        lambda _settings: StockDailyTrendChannelCapability(True, root, None),
    )
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(stock_detail_trend_channel.router)
    app.dependency_overrides[get_db_session] = lambda: db_session
    return TestClient(app)


def _seed_stock(db_session) -> None:
    db_session.add(
        Security(
            ts_code="000001.SZ",
            symbol="000001",
            name="平安银行",
            exchange="SZSE",
            list_status="L",
            security_type="EQUITY",
            source="tushare",
        )
    )
    db_session.commit()


def _seed_non_equity(db_session) -> None:
    db_session.add(
        Security(
            ts_code="510300.SH",
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
            list_status="L",
            security_type="ETF",
            source="tushare",
        )
    )
    db_session.commit()


def test_api_returns_camel_case_bars_in_lake_order(
    tmp_path: Path,
    monkeypatch,
    db_session,
) -> None:
    _seed_stock(db_session)
    for trade_date in ("2026-08-25", "2026-08-26", "2026-08-27"):
        _write_partition(tmp_path, trade_date)
    closed_readers: list[object] = []
    original_close = StockDailyTrendChannelLakeReader.close

    def track_close(reader) -> None:
        closed_readers.append(reader)
        original_close(reader)

    monkeypatch.setattr(
        StockDailyTrendChannelLakeReader,
        "close",
        track_close,
    )

    with _client(tmp_path, monkeypatch, db_session) as client:
        response = client.get(
            "/wealth/market/stock-detail/trend-channel",
            params={"tsCode": "000001.SZ", "endDate": "2026-08-26", "limit": 2},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [bar["tradeDate"] for bar in payload["bars"]] == [
        "2026-08-25",
        "2026-08-26",
    ]
    assert payload["formula"]["version"] == "stock-daily-trend-channel-v1"
    assert payload["bars"][0]["shortChannel"]["state"] == "UP"
    assert payload["meta"] == {
        "count": 2,
        "limit": 2,
        "endDate": "2026-08-26",
    }
    assert payload["dataStatus"]["status"] == "READY"
    assert len(closed_readers) == 1


def test_api_applies_default_and_maximum_limits(
    tmp_path: Path,
    monkeypatch,
    db_session,
) -> None:
    _seed_stock(db_session)
    _write_partition(tmp_path, "2026-08-26")

    with _client(tmp_path, monkeypatch, db_session) as client:
        default_response = client.get(
            "/wealth/market/stock-detail/trend-channel",
            params={"tsCode": "000001.SZ", "endDate": "2026-08-26"},
        )
        maximum_response = client.get(
            "/wealth/market/stock-detail/trend-channel",
            params={
                "tsCode": "000001.SZ",
                "endDate": "2026-08-26",
                "limit": 2_000,
            },
        )

    assert default_response.status_code == 200
    assert default_response.json()["meta"]["limit"] == 300
    assert maximum_response.status_code == 200
    assert maximum_response.json()["meta"]["limit"] == 2_000


def test_api_uses_registered_400_404_and_503_errors(
    tmp_path: Path,
    monkeypatch,
    db_session,
) -> None:
    _seed_stock(db_session)
    _seed_non_equity(db_session)
    (tmp_path / "gold/indicator/stock_daily_trend_channel").mkdir(parents=True)
    with _client(tmp_path, monkeypatch, db_session) as client:
        invalid = client.get(
            "/wealth/market/stock-detail/trend-channel",
            params={"tsCode": "bad", "limit": "x"},
        )
        missing_stock = client.get(
            "/wealth/market/stock-detail/trend-channel",
            params={"tsCode": "600000.SH", "endDate": "2026-08-26"},
        )
        non_equity = client.get(
            "/wealth/market/stock-detail/trend-channel",
            params={"tsCode": "510300.SH", "endDate": "2026-08-26"},
        )
        not_ready = client.get(
            "/wealth/market/stock-detail/trend-channel",
            params={"tsCode": "000001.SZ", "endDate": "2026-08-26"},
        )

    assert invalid.status_code == 400
    assert invalid.json()["code"] == "INVALID_ARGUMENT"
    assert missing_stock.status_code == 404
    assert missing_stock.json()["code"] == "STOCK_NOT_FOUND"
    assert non_equity.status_code == 404
    assert non_equity.json()["code"] == "STOCK_NOT_FOUND"
    assert not_ready.status_code == 503
    assert not_ready.json()["code"] == "STOCK_TREND_CHANNEL_SOURCE_NOT_READY"


def test_api_maps_unexpected_duckdb_failure_to_registered_500(
    tmp_path: Path,
    monkeypatch,
    db_session,
) -> None:
    _seed_stock(db_session)
    _write_partition(tmp_path, "2026-08-26")
    closed_readers: list[object] = []

    def raise_read_error(_self, _request):
        raise StockDailyTrendChannelReadError("duckdb failed")

    monkeypatch.setattr(
        "src.foundation.clients.local_lake.stock_daily_trend_channel_reader.StockDailyTrendChannelLakeReader.read",
        raise_read_error,
    )
    monkeypatch.setattr(
        "src.foundation.clients.local_lake.stock_daily_trend_channel_reader.StockDailyTrendChannelLakeReader.close",
        lambda reader: closed_readers.append(reader),
    )

    with _client(tmp_path, monkeypatch, db_session) as client:
        response = client.get(
            "/wealth/market/stock-detail/trend-channel",
            params={"tsCode": "000001.SZ", "endDate": "2026-08-26"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "STOCK_TREND_CHANNEL_READ_FAILED"
    assert len(closed_readers) == 1
