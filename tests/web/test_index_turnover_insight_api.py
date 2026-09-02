from __future__ import annotations

from datetime import date, datetime
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.biz.api.wealth.market import index_turnover_insight as api
from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_calculator import (
    IndexTurnoverInsightCalculator,
)
from src.biz.schemas.wealth.market.index_turnover_insight import (
    IndexTurnoverInsightResponseDto,
    IndexTurnoverInsightTradingDayDto,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_universe import (
    INDEX_TURNOVER_INSIGHT_UNIVERSE,
)
from src.foundation.config.settings import get_settings


def _error_response() -> IndexTurnoverInsightResponseDto:
    calculator = IndexTurnoverInsightCalculator()
    return IndexTurnoverInsightResponseDto(
        status="ERROR",
        tradingDay=IndexTurnoverInsightTradingDayDto(
            market="CN_A",
            expectedTradeDate=date(2026, 9, 1),
            observedTradeDate=None,
            previousObservedTradeDate=None,
            isTradingDay=True,
            sessionStatus="CLOSED",
            generatedAt=datetime(2026, 9, 2, 8, 0),
        ),
        indices=[
            calculator.build_panel_dto(
                identity=identity,
                calculation=None,
                status="ERROR",
                message="error",
                exception_code="ITI_QUERY_FAILED",
            )
            for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE
        ],
        message="error",
        exceptionCode="ITI_QUERY_FAILED",
    )


def _client(service: Mock, monkeypatch) -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[require_quote_access] = lambda: None
    app.dependency_overrides[get_db_session] = lambda: Mock()
    monkeypatch.setattr(api, "_service", lambda: service)
    return TestClient(app)


def test_index_turnover_api_exposes_only_one_batch_contract(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    get_settings.cache_clear()
    service = Mock()
    service.build_index_turnover_insight.return_value = _error_response()

    with _client(service, monkeypatch) as client:
        response = client.get(
            "/api/v1/wealth/market/turnover-insight/indices",
            params={"market": "CN_A", "tradeDate": "2026-09-01", "debug": 1},
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["indices"]) == 10
    assert [item["tsCode"] for item in payload["indices"]] == [
        identity.ts_code for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE
    ]
    service.build_index_turnover_insight.assert_called_once()
    assert service.build_index_turnover_insight.call_args.kwargs == {
        "market": "CN_A",
        "trade_date": date(2026, 9, 1),
        "debug": True,
    }


def test_index_turnover_api_rejects_unknown_duplicate_and_source_parameters(
    monkeypatch,
) -> None:
    service = Mock()
    service.build_index_turnover_insight.return_value = _error_response()
    with _client(service, monkeypatch) as client:
        unknown = client.get(
            "/api/v1/wealth/market/turnover-insight/indices?codes=000001.SH"
        )
        duplicate = client.get(
            "/api/v1/wealth/market/turnover-insight/indices?debug=0&debug=1"
        )
        frequency = client.get(
            "/api/v1/wealth/market/turnover-insight/indices?freq=1"
        )

    assert unknown.status_code == 400
    assert duplicate.status_code == 400
    assert frequency.status_code == 400
    service.build_index_turnover_insight.assert_not_called()
