from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.biz.api.wealth.market import stock_detail_minute_nine_turn
from src.biz.schemas.wealth.market.nine_turn import (
    NineTurnDataStatusDto,
    NineTurnMarkerDto,
    NineTurnMetaDto,
    NineTurnSeriesDto,
)
from src.foundation.config.local_minute_capability import LocalMinuteCapability


class _FakeMinuteNineTurnService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def read(self, _session, **kwargs) -> NineTurnSeriesDto:
        self.calls.append(kwargs)
        return NineTurnSeriesDto(
            tsCode=str(kwargs["ts_code"]),
            period=str(kwargs["freq"]),
            markers=[
                NineTurnMarkerDto(
                    tradeDate=date(2026, 8, 13),
                    tradeTime=datetime.fromisoformat("2026-08-13T10:00:00+08:00"),
                    direction="UP",
                    sequenceNumber=3,
                    completed=False,
                )
            ],
            latestMarker=None,
            dataStatus=NineTurnDataStatusDto(status="READY"),
            meta=NineTurnMetaDto(
                sourceRowCount=1,
                matchedRowCount=1,
                missingRowCount=0,
                markerCount=1,
                limit=int(kwargs["limit"]),
                hasMore=False,
                endDate=date(2026, 8, 13),
                observedStartDate=date(2026, 8, 13),
                observedEndDate=date(2026, 8, 13),
            ),
        )


@pytest.fixture()
def minute_client(monkeypatch, db_session):
    service = _FakeMinuteNineTurnService()
    monkeypatch.setattr(stock_detail_minute_nine_turn, "_service", lambda: service)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(stock_detail_minute_nine_turn.router)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[require_quote_access] = lambda: None
    with TestClient(app) as client:
        yield client, service


@pytest.mark.parametrize("freq", [30, 60, 90, 120])
def test_local_minute_route_accepts_each_frozen_stock_frequency(
    minute_client,
    freq,
) -> None:
    client, service = minute_client

    response = client.get(
        "/wealth/market/stock-detail/minute-nine-turn",
        params={
            "tsCode": "000001.SZ",
            "freq": freq,
            "endDate": "2026-08-13",
            "limit": 500,
        },
    )

    assert response.status_code == 200
    assert response.json()["period"] == str(freq)
    assert service.calls == [
        {
            "ts_code": "000001.SZ",
            "freq": freq,
            "start_date": None,
            "end_date": date(2026, 8, 13),
            "limit": 500,
            "cursor": None,
            "debug": False,
        }
    ]


@pytest.mark.parametrize("freq", [1, 5, 15])
def test_local_minute_route_rejects_unsupported_short_periods(
    minute_client,
    freq,
) -> None:
    client, service = minute_client

    response = client.get(
        "/wealth/market/stock-detail/minute-nine-turn",
        params={"tsCode": "000001.SZ", "freq": freq},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "NT_REQUEST_INVALID"
    assert service.calls == []


def test_local_minute_route_rejects_unknown_and_repeated_parameters(
    minute_client,
) -> None:
    client, service = minute_client

    unknown = client.get(
        "/wealth/market/stock-detail/minute-nine-turn",
        params={"tsCode": "000001.SZ", "freq": 30, "foo": "bar"},
    )
    repeated = client.get(
        "/wealth/market/stock-detail/minute-nine-turn"
        "?tsCode=000001.SZ&freq=30&freq=60"
    )

    assert unknown.status_code == 400
    assert repeated.status_code == 400
    assert service.calls == []


def test_app_router_mounts_stock_minute_nine_turn_only_when_capability_is_ready(
    monkeypatch,
    tmp_path,
) -> None:
    import importlib

    app_router = importlib.import_module("src.app.api.v1.router")
    disabled = LocalMinuteCapability(enabled=False, lake_root=None, reason_code=None)
    enabled = LocalMinuteCapability(enabled=True, lake_root=tmp_path, reason_code=None)

    monkeypatch.setattr(app_router, "resolve_local_minute_capability", lambda _settings: disabled)
    monkeypatch.setattr(app_router, "resolve_index_minute_capability", lambda _settings: disabled)
    monkeypatch.setattr(
        app_router,
        "resolve_stock_nine_turn_minute_capability",
        lambda _settings: disabled,
    )
    production_target = APIRouter(prefix="/v1")
    app_router._include_local_minute_router(production_target)
    assert "/v1/wealth/market/stock-detail/minute-nine-turn" not in {
        route.path for route in production_target.routes
    }

    monkeypatch.setattr(
        app_router,
        "resolve_stock_nine_turn_minute_capability",
        lambda _settings: enabled,
    )
    local_target = APIRouter(prefix="/v1")
    app_router._include_local_minute_router(local_target)
    assert "/v1/wealth/market/stock-detail/minute-nine-turn" in {
        route.path for route in local_target.routes
    }
