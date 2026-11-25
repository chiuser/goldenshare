from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import json
from pathlib import Path

import duckdb
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from goldenshare_technical_indicators.errors import SourceContractError
from goldenshare_technical_indicators.service import TechnicalIndicatorService
import pytest

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies.index_minute_technical_indicators import run_index_minute_page
from src.app.exceptions import install_exception_handlers
from src.app.runtime.technical_indicators.composition import create_runtime
from src.biz.api.wealth.market import index_detail_minute_nine_turn, index_detail_minutes
from src.biz.schemas.wealth.market.index_detail_minutes import IndexMinutesResponseDto
from src.biz.services.wealth.market.index_detail_minutes.index_minute_response_policy import (
    enforce_index_minute_response_size,
)
from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteRequestError
from src.foundation.config.local_minute_capability import LocalMinuteCapability
from src.foundation.config.settings import Settings


_PREFIX = "/wealth/market/index-detail"
_SESSION_SAMPLES = {
    1: ("09:30", "09:31"),
    5: ("09:35", "09:40"),
    15: ("09:45", "10:00"),
    30: ("10:00", "10:30"),
    60: ("10:30", "11:30"),
    90: ("11:00", "14:00"),
    120: ("11:30", "15:00"),
}


def _write_bars(root: Path, freq: int, *, exclude_close: bool = False) -> None:
    # Follow the formal Gold and Silver Parquet schemas verified in stages 1 and 2.
    # Two rows suffice to produce two distinct bars for each frequency.
    if freq <= 60:
        folder = f"gold/quote/major_index_mins/freq={freq}"
        clock_times = _SESSION_SAMPLES[freq]
        frequency_column = f"{freq}::INTEGER AS freq, DATE '2026-11-09' AS trade_date"
    else:
        base, clock_times = (30, ("11:00", "14:00")) if freq == 90 else (60, _SESSION_SAMPLES[freq])
        folder = f"silver/quote/major_index_mins/freq={base}min"
        frequency_column = f"'{base}min'::VARCHAR AS freq"
    target = root / folder / "trade_date=2026-11-09/part-000.parquet"
    target.parent.mkdir(parents=True)
    close_column = "" if exclude_close else "price::DOUBLE AS close,"
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"""
            COPY (
                SELECT '000001.SH'::VARCHAR AS ts_code, {frequency_column},
                    CAST('2026-11-09 ' || clock AS TIMESTAMP) AS trade_time,
                    (price - 1)::DOUBLE AS open, (price + 1)::DOUBLE AS high,
                    (price - 2)::DOUBLE AS low, {close_column} 100.0::DOUBLE AS vol,
                    120.0::DOUBLE AS amount, 'SSE'::VARCHAR AS exchange
                FROM (VALUES ($first, 11), ($last, 12)) AS sample(clock, price)
            ) TO $target (FORMAT PARQUET)
        """, {"first": clock_times[0], "last": clock_times[1], "target": str(target)})


def _client(lake_root: Path) -> TestClient:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = create_runtime(Settings(_env_file=None, APP_ENV="local", GOLDENSHARE_LAKE_ROOT=str(lake_root)))
        app.state.technical_indicator_runtime = runtime
        try:
            yield
        finally:
            await runtime.aclose()

    app = FastAPI(lifespan=lifespan)
    install_exception_handlers(app)
    app.dependency_overrides[require_quote_access] = lambda: None
    app.include_router(index_detail_minutes.build_router(run_page=run_index_minute_page))
    app.include_router(index_detail_minute_nine_turn.build_router(run_page=run_index_minute_page))
    return TestClient(app)


def _v1_cursor(dataset: str, freq: int, clock: str) -> str:
    # Old v1 wire format. Construct this independently of the current encoder.
    payload = {
        "v": 1, "dataset": dataset,
        **({"subjectType": "index"} if dataset == "index_minute_nine_turn" else {}),
        "tsCode": "000001.SH", "freq": freq,
        "startDate": "2026-11-09", "endDate": "2026-11-09",
        "beforeTradeDate": "2026-11-09", "beforeTradeTime": f"{clock}:00.000000",
    }
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


@pytest.mark.parametrize("freq", _SESSION_SAMPLES)
def test_index_minute_apis_calculate_seven_frequencies_and_accept_v1_cursors(tmp_path: Path, freq: int) -> None:
    _write_bars(tmp_path, freq)
    oldest, newest = _SESSION_SAMPLES[freq]
    params = {"tsCode": "000001.SH", "freq": freq, "startDate": "2026-11-09", "endDate": "2026-11-09", "limit": 1}

    with _client(tmp_path) as client:
        for endpoint, field in (("minutes", "bars"), ("minute-indicators", "items")):
            response = client.get(f"{_PREFIX}/{endpoint}", params=params)
            assert response.status_code == 200, response.text
            first = response.json()
            assert first["dataStatus"]["status"] == "READY"
            assert first[field][0]["tradeTime"] == f"2026-11-09T{newest}:00+08:00"
            assert first["meta"]["hasMore"] is True

            cursor = _v1_cursor("bars" if field == "bars" else "indicators", freq, newest)
            assert first["meta"]["nextCursor"] == cursor
            response = client.get(f"{_PREFIX}/{endpoint}", params={**params, "cursor": cursor})
            assert response.status_code == 200, response.text
            last = response.json()
            assert last[field][0]["tradeTime"] == f"2026-11-09T{oldest}:00+08:00"
            assert last["meta"]["hasMore"] is False
            assert last["meta"]["nextCursor"] is None

            if field == "bars":
                assert first[field][0]["close"] == 12
                assert first[field][0]["vol"] == 100
                assert first[field][0]["amount"] == 120
                assert "vwap" not in first[field][0]
                series = first["nineTurn"]
                if freq == 1:
                    assert series is None and last["nineTurn"] is None
                else:
                    assert series["meta"]["matchedRowCount"] == 1 and series["markers"] == []
                    nine_turn_cursor = _v1_cursor("index_minute_nine_turn", freq, newest)
                    assert series["meta"]["nextCursor"] == nine_turn_cursor
                    independent = client.get(f"{_PREFIX}/minute-nine-turn", params=params)
                    assert independent.status_code == 200 and independent.json() == series
                    continued = client.get(f"{_PREFIX}/minute-nine-turn", params={**params, "cursor": nine_turn_cursor})
                    assert continued.status_code == 200 and continued.json() == last["nineTurn"]
                assert "preClose" not in first[field][0]
            else:
                assert first[field][0]["ma250"] is None
                assert first[field][0]["indicatorVersion"] == 1
                assert "observationCount" not in first[field][0]

        assert "observationCount" not in client.get("/openapi.json").text


def test_index_minute_default_cutoff_and_limit(tmp_path: Path) -> None:
    _write_bars(tmp_path, 5)
    with _client(tmp_path) as client:
        response = client.get(f"{_PREFIX}/minute-indicators", params={"tsCode": "000001.SH", "freq": 5})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["count"] == 2
    assert payload["meta"]["limit"] == 500
    assert payload["meta"]["endDate"] is None
    assert payload["dataStatus"]["status"] == "READY"


def test_index_minute_indicators_failure_preserves_independent_bars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_bars(tmp_path, 5)
    calculate = TechnicalIndicatorService.calculate_index_minutes_recent

    def fail_indicators(service, request, **kwargs):
        if request.calculations[0]["calculation_id"] != "price":
            raise SourceContractError("indicator source failed")
        return calculate(service, request, **kwargs)

    monkeypatch.setattr(TechnicalIndicatorService, "calculate_index_minutes_recent", fail_indicators)
    with _client(tmp_path) as client:
        params = {"tsCode": "000001.SH", "freq": 5, "endDate": "2026-11-09"}
        indicators = client.get(f"{_PREFIX}/minute-indicators", params=params)
        bars = client.get(f"{_PREFIX}/minutes", params=params)

    assert indicators.status_code == 500
    assert indicators.json()["code"] == "IM_SOURCE_CONTRACT_INVALID"
    assert bars.status_code == 200
    assert bars.json()["dataStatus"]["status"] == "READY"
    assert bars.json()["nineTurn"]["meta"]["matchedRowCount"] == 2


def test_index_minute_api_maps_missing_source_column_to_contract_error(tmp_path: Path) -> None:
    _write_bars(tmp_path, 5, exclude_close=True)
    with _client(tmp_path) as client:
        response = client.get(f"{_PREFIX}/minutes", params={"tsCode": "000001.SH", "freq": 5})
    assert response.status_code == 500
    assert response.json()["code"] == "IM_SOURCE_CONTRACT_INVALID"


def test_index_minute_api_enforces_universe_and_bse_empty(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        bse = client.get(
            "/wealth/market/index-detail/minutes",
            params={"tsCode": "899050.BJ", "freq": "5", "endDate": "2026-08-11"},
        )
        bse_nine_turn = client.get(
            f"{_PREFIX}/minute-nine-turn",
            params={"tsCode": "899050.BJ", "freq": 5, "endDate": "2026-08-11", "debug": 1},
        )
        lake_only = client.get(
            "/wealth/market/index-detail/minutes",
            params={"tsCode": "000680.SH", "freq": "5", "endDate": "2026-08-11"},
        )

    assert bse.status_code == 200
    assert bse.json()["dataStatus"]["status"] == "EMPTY"
    assert bse.json()["dataStatus"]["code"] == "IM_SOURCE_NOT_READY"
    assert bse.json()["nineTurn"]["dataStatus"]["status"] == "EMPTY"
    assert bse_nine_turn.status_code == 200
    assert bse_nine_turn.json()["debugInfo"]["sourceDatasets"] == []
    assert bse_nine_turn.json()["debugInfo"]["scannedFileCount"] == 0
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
    query: str,
) -> None:
    with _client(tmp_path) as client:
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
    monkeypatch.setattr(
        app_router, "resolve_local_minute_capability", lambda _settings: disabled
    )
    monkeypatch.setattr(
        app_router, "resolve_index_minute_capability", lambda _settings: disabled
    )
    target = APIRouter(prefix="/v1")
    app_router._include_local_minute_router(target)
    paths = {route.path for route in target.routes}
    assert "/v1/wealth/market/index-detail/minutes" not in paths
    assert "/v1/wealth/market/index-detail/minute-indicators" not in paths

    enabled = LocalMinuteCapability(enabled=True, lake_root=tmp_path, reason_code=None)
    monkeypatch.setattr(
        app_router, "resolve_local_minute_capability", lambda _settings: enabled
    )
    monkeypatch.setattr(
        app_router, "resolve_index_minute_capability", lambda _settings: enabled
    )
    local_target = APIRouter(prefix="/v1")
    app_router._include_local_minute_router(local_target)
    local_paths = {route.path for route in local_target.routes}
    assert "/v1/wealth/market/index-detail/minutes" in local_paths
    assert "/v1/wealth/market/index-detail/minute-indicators" in local_paths


def test_index_minute_response_size_guard_rejects_payload_above_5mb() -> None:
    response = IndexMinutesResponseDto.model_validate(
        {
            "tsCode": "000001.SH",
            "freq": 5,
            "nineTurn": None,
            "bars": [
                {
                    "tsCode": "000001.SH",
                    "freq": 5,
                    "tradeDate": "2026-08-11",
                    "tradeTime": "2026-08-11T09:35:00+08:00",
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "vol": 1,
                    "amount": 1,
                    "exchange": "X" * 5_000_000,
                }
            ],
            "meta": {
                "count": 1,
                "limit": 1,
                "hasMore": False,
                "nextCursor": None,
                "startDate": None,
                "endDate": None,
                "observedStartDate": "2026-08-11",
                "observedEndDate": "2026-08-11",
            },
            "dataStatus": {
                "status": "READY",
                "code": None,
                "expectedEndDate": None,
                "observedEndDate": "2026-08-11",
                "message": None,
            },
        }
    )

    with pytest.raises(IndexMinuteRequestError, match="5MB"):
        enforce_index_minute_response_size(response)
