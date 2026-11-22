import json
from datetime import date
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.auth.dependencies import get_current_user
from src.app.exceptions import install_exception_handlers
from src.app.runtime import data_audit
from src.biz.api.wealth.data_center import home
from src.biz.services.wealth.data_center.data_audit import DataAuditReader
from src.foundation.config.settings import Settings

ROOT = "/api/v1/wealth/data-center"
DAY = "2026-11-20"
RUN = str(uuid4())


@pytest.fixture
def summary():
    return {
        "schema_version": 1, "business_date": DAY,
        "observed_at": "2026-11-21T00:12:00+08:00",
        "generated_at": "2026-11-21T00:12:01+08:00",
        "summary": {"complete": 0, "gap": 1, "pending": 0, "not_applicable": 0},
        "rows": [{
            "dataset_name": "ETF 日线行情", "scope": {"asset_key": "silver_etf_daily"},
            "version": {"target_version": "test-etf-content-id", "inputs": [], "rule_version": "test"},
            "update": {"status": "updated"},
            "completeness": {
                "status": "gap", "reason": {"code": "coverage_gap", "message": "缺两只"},
                "checked_at": None, "components": [], "missing_count": 2, "evidence": [],
            },
        }],
    }


def test_local_api_pins_details_and_only_reads_a_summary(monkeypatch, summary):
    requests = []

    def respond(request):
        assert str(request.url) == "http://127.0.0.1:3000/graphql"
        payload = json.loads(request.content)
        requests.append(payload)
        if "runsOrError" in payload["query"]:
            filters = payload["variables"]["filter"]
            expected_tags = [{"key": "audit/business_date", "value": DAY}]
            valid = filters["tags"] == expected_tags and filters.get("runIds", [RUN]) == [RUN]
            assert filters["pipelineName"] == "daily_data_audit_summary_job"
            assert filters["statuses"] == ["SUCCESS"]
            return httpx.Response(200, json={"data": {"runsOrError": {
                "__typename": "Runs", "results": [{"runId": RUN}] if valid else [],
            }}})
        assert payload["variables"] == {"id": RUN}
        return httpx.Response(200, json={"data": {"logsForRun": {"events": [{
            "stepKey": "generate_data_audit_summary", "metadataEntries": [
                {"label": "data_audit_summary", "jsonString": json.dumps(summary)},
            ],
        }]}}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        monkeypatch.setattr(data_audit, "DataAuditReader", lambda _client: DataAuditReader(transport))
        app = FastAPI()
        data_audit.install_data_audit(app, Settings(APP_ENV="local", WEALTH_LOCAL_DATA_AUDIT_ENABLED=True))
        app.dependency_overrides[get_current_user] = lambda: object()
        with TestClient(app) as client:
            path = f"{ROOT}/data-audit/days/{DAY}"
            day = client.get(path).json()
            assert day["summary"] == summary["summary"]
            assert day["summary_run_id"] == RUN
            assert day["rows"][0]["update"]["status"] == "updated"
            assert day["rows"][0]["completeness"]["status"] == "gap"
            assert "evidence" not in day["rows"][0]["completeness"]
            assert len(requests) == 2
            detail = client.get(f"{path}/assets/silver_etf_daily", params={"summary_run_id": RUN})
            assert detail.json()["completeness"]["missing_count"] == 2
            assert requests[2]["variables"]["filter"]["runIds"] == [RUN]
            assert client.get(f"{path}/assets/silver_etf_daily", params={"summary_run_id": str(uuid4())}).status_code == 404
            assert client.get(f"{ROOT}/data-audit/days/2026-11-18").json()["state"] == "not_generated"
            assert client.post(path, json={}).status_code == 405


@pytest.mark.parametrize(("env", "enabled", "exposed"), [
    ("local", True, True), ("dev", True, True), ("dev", False, False), ("prod", True, False),
])
def test_feature_flag_controls_card_authenticated_routes_and_production(monkeypatch, env, enabled, exposed):
    settings = Settings(APP_ENV=env, WEALTH_LOCAL_DATA_AUDIT_ENABLED=enabled)
    monkeypatch.setattr(home, "get_settings", lambda: settings)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(home.router, prefix="/api/v1")
    data_audit.install_data_audit(app, settings)
    with TestClient(app) as client:
        modules = client.get(ROOT + "/modules").json()["modules"]
        assert any(card["moduleKey"] == "data-audit" for card in modules) is exposed
        assert client.get(f"{ROOT}/data-audit/days/{DAY}").status_code == (401 if exposed else 404)


def test_unreachable_dg_is_not_an_empty_summary():
    def respond(request):
        raise httpx.ConnectError("DG offline", request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        result = DataAuditReader(transport).read(date.fromisoformat(DAY))
        assert result["state"] == "unavailable"
        assert result["summary"] is None


def test_prod_direct_page_obeys_the_same_flag(monkeypatch):
    import importlib

    web = importlib.import_module("src.app.web.app")
    settings = Settings(APP_ENV="prod", WEALTH_LOCAL_DATA_AUDIT_ENABLED=True)
    monkeypatch.setattr(web, "get_settings", lambda: settings)
    client = TestClient(web.app)
    response = client.get("/wealth/data-center/data-audit", headers={"host": "localhost"})
    assert response.status_code == 404
