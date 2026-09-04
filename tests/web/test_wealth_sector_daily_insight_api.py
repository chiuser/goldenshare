from __future__ import annotations

import pytest

from src.foundation.config.settings import get_settings
from tests.test_wealth_sector_daily_insight_query_service import (
    NOW,
    request_params,
    seed_insight,
)


PREFIX = "/api/v1/wealth/market/sector-analysis/daily-insight"


@pytest.fixture
def seeded(db_session, monkeypatch):
    seed_insight(db_session)
    monkeypatch.setattr(
        "src.biz.queries.wealth.market.context.market_page_context_query._now_cn",
        lambda: NOW,
    )


def test_real_router_query_and_serialization(app_client, seeded):
    meta = app_client.get(f"{PREFIX}/meta")
    assert meta.status_code == 200, meta.text
    assert meta.json()["status"] == "READY"
    for level in (1, 2, 3):
        params = request_params()
        params["industryLevel"] = level
        response = app_client.get(f"{PREFIX}/snapshot", params=params)
        assert response.status_code == 200, response.text
        assert response.json()["industryLevel"] == level
        assert len(response.json()["headGainers"]) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("market", "SW"),
        ("tradeDate", "20250825"),
        ("tradeDate", "2025-02-30"),
        ("industryLevel", "0"),
        ("industryLevel", "1.0"),
        ("batchKey", "bad"),
        ("hierarchyVersion", " "),
        ("debug", "2"),
        ("pageSize", "10"),
    ],
)
def test_invalid_requests_rejected_before_query(app_client, monkeypatch, key, value):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid request reached the business query")

    monkeypatch.setattr(
        "src.biz.queries.wealth.market.sector_analysis.sector_daily_insight_query_service.SectorDailyInsightQueryService.build_snapshot",
        forbidden,
    )
    params = request_params()
    params[key] = value
    response = app_client.get(f"{PREFIX}/snapshot", params=params)
    assert response.status_code == 400
    assert response.json()["code"] == "SA_SCOPE_INVALID"


@pytest.mark.parametrize(
    "key", ["tradeDate", "industryLevel", "batchKey", "hierarchyVersion"]
)
def test_required_identity_and_duplicate_query(app_client, key):
    params = request_params()
    del params[key]
    assert app_client.get(f"{PREFIX}/snapshot", params=params).status_code == 400
    params = list(request_params().items())
    params.append((key, request_params()[key]))
    assert app_client.get(f"{PREFIX}/snapshot", params=params).status_code == 400


def test_409_and_safe_500(app_client, seeded, monkeypatch):
    params = request_params()
    params["hierarchyVersion"] = "replaced"
    response = app_client.get(f"{PREFIX}/snapshot", params=params)
    assert (
        response.status_code == 409
        and response.json()["code"] == "SA_DAILY_INSIGHT_BATCH_MISMATCH"
    )

    def broken(*args, **kwargs):
        raise RuntimeError("SELECT password FROM core_serving private-server secret")

    monkeypatch.setattr(
        "src.biz.queries.wealth.market.sector_analysis.sector_daily_insight_query.SectorDailyInsightQuery.load_coverage",
        broken,
    )
    monkeypatch.setattr(
        "src.biz.queries.wealth.market.sector_analysis.sector_daily_insight_query.SectorDailyInsightQuery.load_batch",
        broken,
    )
    for suffix, params in (("meta", {}), ("snapshot", request_params())):
        response = app_client.get(f"{PREFIX}/{suffix}", params=params)
        assert (
            response.status_code == 500
            and response.json()["code"] == "SA_DAILY_INSIGHT_QUERY_FAILED"
        )
        assert not any(
            text in response.text
            for text in (
                "SELECT",
                "password",
                "core_serving",
                "private-server",
                "secret",
                "Traceback",
            )
        )


def test_quote_401_no_invented_admin_requirement(app_client, monkeypatch):
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        for suffix in ("meta", "snapshot"):
            response = app_client.get(f"{PREFIX}/{suffix}")
            assert (
                response.status_code == 401
                and response.json()["code"] == "auth_required"
            )
    finally:
        get_settings.cache_clear()
