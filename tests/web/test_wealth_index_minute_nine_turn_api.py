from __future__ import annotations

from datetime import date

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.biz.api.wealth.market import index_detail_minute_nine_turn
from src.biz.queries.wealth.market.index_minute_nine_turn.index_minute_nine_turn_query_service import (
    IndexMinuteNineTurnQueryService,
)
from src.biz.schemas.wealth.market.nine_turn import (
    NineTurnDataStatusDto,
    NineTurnMetaDto,
    NineTurnSeriesDto,
)
from src.foundation.config.local_minute_capability import LocalMinuteCapability
from src.foundation.clients.local_lake.index_nine_turn_reader import (
    IndexNineTurnReadPage,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
)


class _FakeIndexMinuteNineTurnService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def read(self, _session, **kwargs) -> NineTurnSeriesDto:
        self.calls.append(kwargs)
        return NineTurnSeriesDto(
            subjectType="index",
            tsCode=str(kwargs["ts_code"]),
            period=str(kwargs["freq"]),
            markers=[],
            latestMarker=None,
            dataStatus=NineTurnDataStatusDto(
                status="EMPTY",
                code="NT_SOURCE_NOT_READY",
            ),
            meta=NineTurnMetaDto(
                sourceRowCount=0,
                matchedRowCount=0,
                missingRowCount=0,
                markerCount=0,
                limit=int(kwargs["limit"]),
                hasMore=False,
                endDate=kwargs["end_date"] or date(2026, 8, 14),
            ),
        )


@pytest.fixture()
def minute_client(monkeypatch, db_session):
    service = _FakeIndexMinuteNineTurnService()
    monkeypatch.setattr(index_detail_minute_nine_turn, "_service", lambda: service)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(index_detail_minute_nine_turn.router)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[require_quote_access] = lambda: None
    with TestClient(app) as client:
        yield client, service


@pytest.mark.parametrize("freq", [5, 15, 30, 60, 90, 120])
def test_local_minute_route_accepts_six_index_frequencies(
    minute_client,
    freq,
) -> None:
    client, service = minute_client

    response = client.get(
        "/wealth/market/index-detail/minute-nine-turn",
        params={"tsCode": "899050.BJ", "freq": freq, "endDate": "2026-08-13"},
    )

    assert response.status_code == 200
    assert response.json()["subjectType"] == "index"
    assert response.json()["period"] == str(freq)
    assert response.json()["dataStatus"]["code"] == "NT_SOURCE_NOT_READY"
    assert service.calls[-1]["freq"] == freq


@pytest.mark.parametrize("freq", [1, 7])
def test_local_minute_route_rejects_unsupported_frequencies(
    minute_client,
    freq,
) -> None:
    client, service = minute_client

    response = client.get(
        "/wealth/market/index-detail/minute-nine-turn",
        params={"tsCode": "000001.SH", "freq": freq},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "NT_REQUEST_INVALID"
    assert service.calls == []


def test_app_router_mounts_index_minute_nine_turn_only_when_ready(
    monkeypatch,
    tmp_path,
) -> None:
    import importlib

    app_router = importlib.import_module("src.app.api.v1.router")
    disabled = LocalMinuteCapability(enabled=False, lake_root=None, reason_code=None)
    enabled = LocalMinuteCapability(enabled=True, lake_root=tmp_path, reason_code=None)
    monkeypatch.setattr(
        app_router, "resolve_local_minute_capability", lambda _: disabled
    )
    monkeypatch.setattr(
        app_router, "resolve_index_minute_capability", lambda _: disabled
    )
    monkeypatch.setattr(
        app_router,
        "resolve_stock_nine_turn_minute_capability",
        lambda _: disabled,
    )
    monkeypatch.setattr(
        app_router,
        "resolve_index_nine_turn_minute_capability",
        lambda _: disabled,
    )
    production = APIRouter(prefix="/v1")
    app_router._include_local_minute_router(production)
    assert "/v1/wealth/market/index-detail/minute-nine-turn" not in {
        route.path for route in production.routes
    }

    monkeypatch.setattr(
        app_router,
        "resolve_index_nine_turn_minute_capability",
        lambda _: enabled,
    )
    local = APIRouter(prefix="/v1")
    app_router._include_local_minute_router(local)
    assert "/v1/wealth/market/index-detail/minute-nine-turn" in {
        route.path for route in local.routes
    }


def test_minute_service_applies_product_allowlist_before_reader(
    db_session,
    tmp_path,
) -> None:
    reader = _CountingReader()
    service = IndexMinuteNineTurnQueryService(tmp_path, reader=reader)

    with pytest.raises(IndexDetailNotFoundError):
        service.read(
            db_session,
            ts_code="000680.SH",
            freq=5,
            start_date=None,
            end_date=date(2026, 8, 14),
            limit=500,
            cursor=None,
            debug=False,
        )

    assert reader.calls == []


class _CountingReader:
    def __init__(self) -> None:
        self.calls = []

    def read(self, request):
        self.calls.append(request)
        return IndexNineTurnReadPage(
            rows=(),
            source_row_count=0,
            matched_row_count=0,
            missing_row_count=0,
            has_more=False,
            next_cursor=None,
            observed_start_date=None,
            observed_end_date=None,
            scanned_file_count=0,
            elapsed_ms=0,
        )
