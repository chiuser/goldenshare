import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.auth.dependencies import get_current_user
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.app.runtime import data_audit
from src.app.runtime.announcement_archive_lifespan import install_data_center
from src.biz.api.wealth.data_center import home
from src.biz.services.wealth.data_center.data_audit import DataAuditReader
from src.foundation.config.settings import Settings

ROOT = "/api/v1/wealth/data-center"
DAY = "2026-11-20"
RUN = str(uuid4())
AUDIT = ROOT + "/data-audit"
RAW = f"{AUDIT}/days/{DAY}/assets/raw_tushare_dc_index"
SILVER = f"{AUDIT}/days/{DAY}/assets/silver_dc_index"
CONFIRM = "daily_data_audit_board_confirm_job"
RECHECK = "daily_data_audit_board_recheck_job"
VERSION = "review-20"
RECHECK_RUN = str(uuid4())
CONFIRM_RUN = str(uuid4())
RAW_RUN = str(uuid4())
DEADLINE = "2026-11-21T01:00:00+08:00"


def _native_run(run_id, job, status, *, day=DAY, version=VERSION):
    return {
        "runId": run_id, "jobName": job, "status": status,
        "tags": [{"key": "audit/business_date", "value": day}, {"key": "audit/review_version", "value": version}],
        "runConfig": {"ops": {"recheck_dc_index": {"config": {"deadline": DEADLINE}}}},
    }


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
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
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
    app.dependency_overrides[get_db_session] = lambda: None
    with TestClient(app) as client:
        modules = client.get(ROOT + "/modules").json()["modules"]
        assert any(card["moduleKey"] == "data-audit" for card in modules) is exposed
        expected = 401 if exposed else 404
        assert client.get(f"{AUDIT}/days/{DAY}").status_code == expected
        assert client.get(RAW + "/board-standard").status_code == expected
        assert client.get(f"{AUDIT}/runs/{RECHECK_RUN}").status_code == expected
        for action in ("board-confirm", "board-recheck"):
            assert client.post(f"{RAW}/{action}", json={"review_version": VERSION}).status_code == expected


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


@pytest.fixture
def boards(monkeypatch, summary):
    old = {"category": "概念板块", "code": "BK0001.DC", "name": "历史板块"}
    new = {"category": "概念板块", "code": "BK0002.DC", "name": "新板块"}
    review = {
        "business_date": DAY, "review_version": VERSION, "raw_run_id": RAW_RUN,
        "state": "pending", "reason": "manual_review", "can_confirm": True,
        "reference": {"business_date": "2026-11-19", "version": "standard-19", "boards": [old]},
        "current": [new], "added": [new], "removed": [old], "standard": None, "recheck": None,
    }
    for key in ("raw_tushare_dc_index", "silver_dc_index"):
        summary["rows"].append({
            **summary["rows"][0], "scope": {"asset_key": key},
            **({"board_review": review} if key == "raw_tushare_dc_index" else {}),
        })
    runs, outputs, requests = {}, {}, []

    def respond(request):
        assert str(request.url) == "http://127.0.0.1:3000/graphql"
        payload = json.loads(request.content)
        requests.append(payload)
        variables = payload["variables"]
        query = payload["query"]
        if "query DataAuditSummaryRun" in query:
            assert variables["filter"]["pipelineName"] == "daily_data_audit_summary_job"
            return _graphql({"runsOrError": {"__typename": "Runs", "results": [{"runId": RUN}]}})
        if "query DataAuditSummaryRecord" in query:
            assert variables == {"id": RUN}
            return _graphql({"logsForRun": {"events": [{
                "stepKey": "generate_data_audit_summary",
                "metadataEntries": [{"label": "data_audit_summary", "jsonString": json.dumps(summary)}],
            }]}})
        if "query DataAuditBoardRuns" in query:
            assert {variables["confirm"]["pipelineName"], variables["recheck"]["pipelineName"]} == {CONFIRM, RECHECK}
            response = {}
            for name, filters in variables.items():
                assert filters["tags"] == [
                    {"key": "audit/business_date", "value": DAY}, {"key": "audit/review_version", "value": VERSION},
                ]
                matches = [run for run in reversed(list(runs.values())) if run["jobName"] == filters["pipelineName"]
                           and run["status"] in filters["statuses"] and run["tags"] == filters["tags"]]
                response[name] = {"__typename": "Runs", "results": matches[:1]}
            return _graphql(response)
        if "query DataAuditBoardRun(" in query:
            run = runs.get(variables["id"])
            return _graphql({"runOrError": {"__typename": "Run", **run} if run else {"__typename": "RunNotFoundError"}})
        if "query DataAuditBoardOutput" in query:
            run_id = variables["id"]
            event = outputs[run_id]
            log = {"__typename": "EventConnection", "hasMore": False, "cursor": "end", "events": [event]}
            if variables["cursor"] is None and run_id == RECHECK_RUN:
                log.update(hasMore=True, cursor="page-1", events=[{"stepKey": "irrelevant"}])
            return _graphql({"logsForRun": log})
        assert "mutation DataAuditBoardLaunch" in query
        params = variables["executionParams"]
        job = params["selector"]["jobName"]
        run_id = RECHECK_RUN if job == RECHECK else CONFIRM_RUN
        run = _native_run(run_id, job, "QUEUED")
        run["runConfig"] = params["runConfigData"]
        runs[run_id] = run
        return _graphql({"launchRun": {"__typename": "LaunchRunSuccess", "run": run}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        monkeypatch.setattr(data_audit, "DataAuditReader", lambda _client: DataAuditReader(transport))
        app = FastAPI()
        install_exception_handlers(app)
        install_data_center(app)
        data_audit.install_data_audit(app, Settings(APP_ENV="local", WEALTH_LOCAL_DATA_AUDIT_ENABLED=True))
        user = SimpleNamespace(id=23, is_admin=True)
        app.dependency_overrides[get_current_user] = lambda: user
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, user=user, review=review, runs=runs, outputs=outputs, requests=requests)


def _graphql(data):
    return httpx.Response(200, json={"data": data})


def _output(step, label, result):
    return {"stepKey": step, "metadataEntries": [{"label": label, "jsonString": json.dumps(result)}]}


def test_board_review_uses_raw_summary_and_keeps_board_payload_off_existing_gets(boards):
    assert boards.client.get(RAW + "/board-standard").json() == boards.review
    assert boards.client.get(SILVER + "/board-standard").json() == {**boards.review, "can_confirm": False}
    assert "board_review" not in boards.client.get(RAW).json()
    daily = boards.client.get(f"{AUDIT}/days/{DAY}").json()
    assert daily["can_operate"] is True
    assert all("board_review" not in row for row in daily["rows"])
    assert boards.client.get(RAW.replace("raw_tushare_dc_index", "unknown") + "/board-standard").status_code == 404


def test_recheck_submit_poll_and_immediate_same_version_result(boards):
    path = RAW + "/board-recheck"
    start = datetime.now(UTC)
    response = boards.client.post(path, json={"review_version": VERSION})
    assert response.status_code == 202
    queued = response.json()
    expires_at = datetime.fromisoformat(queued["deadline"])
    window = timedelta(seconds=600)
    assert start + window <= expires_at <= datetime.now(UTC) + window
    assert queued == {"run_id": RECHECK_RUN, "status": "QUEUED", "deadline": queued["deadline"]}
    assert boards.requests[-1]["variables"]["executionParams"] == {
        "selector": {"repositoryLocationName": "orchestrator", "repositoryName": "__repository__", "jobName": RECHECK},
        "runConfigData": {"ops": {"recheck_dc_index": {"config": {
            "business_date": DAY, "review_version": VERSION, "requested_by": "23",
            "retry_run_id": None, "deadline": queued["deadline"],
        }}}},
        "executionMetadata": {"tags": [
            {"key": "audit/business_date", "value": DAY}, {"key": "audit/review_version", "value": VERSION},
        ]},
    }
    assert boards.client.get(f"{AUDIT}/runs/{RECHECK_RUN}").json() == {
        **queued, "business_date": DAY, "review_version": VERSION, "job_name": RECHECK, "result": None, "error": None,
    }
    assert boards.client.post(path, json={"review_version": VERSION}).json() == queued
    assert boards.client.post(RAW + "/board-confirm", json={"review_version": VERSION}).status_code == 409
    result = {"business_date": DAY, "review_version": VERSION, "run_id": RECHECK_RUN, "has_confirmed_gap": True, "results": [
        {"code": "BK0001.DC", "classification": {"status": "success"}, "member": {"status": "not_returned"}},
    ]}
    boards.runs[RECHECK_RUN]["status"] = "SUCCESS"
    boards.outputs[RECHECK_RUN] = _output("recheck_dc_index", "dc_index_recheck", result)
    polled = boards.client.get(f"{AUDIT}/runs/{RECHECK_RUN}").json()
    assert polled["status"] == "SUCCESS"
    assert polled["result"] == result
    assert boards.client.get(RAW + "/board-standard").json() == {
        **boards.review, "recheck": result, "reason": "confirmed_source_gap", "can_confirm": False,
    }
    blocked = boards.client.post(RAW + "/board-confirm", json={"review_version": VERSION})
    assert (blocked.status_code, blocked.json()["code"]) == (409, "board_confirmed_gap")
    assert sum("mutation" in x["query"] for x in boards.requests) == 1

    # DG saves the new source result before the daily summary refreshes.
    boards.review.update(reason="confirmed_source_gap", recheck=result, can_confirm=False)
    cleared_run_id = "00000000-0000-0000-0000-000000000004"
    cleared = {**result, "run_id": cleared_run_id, "has_confirmed_gap": False, "results": [{
        "code": "BK0001.DC", "classification": {"status": "not_returned"},
        "member": {"status": "not_returned"},
    }]}
    boards.runs[cleared_run_id] = {**boards.runs[RECHECK_RUN], "runId": cleared_run_id}
    boards.outputs[cleared_run_id] = _output("recheck_dc_index", "dc_index_recheck", cleared)
    assert boards.client.get(RAW + "/board-standard").json() == {
        **boards.review, "recheck": cleared, "reason": "manual_review", "can_confirm": True,
    }


def test_confirm_returns_standard_before_summary_refresh_and_blocks_second_confirmation(boards):
    response = boards.client.post(RAW + "/board-confirm", json={"review_version": VERSION})
    assert response.status_code == 202
    assert response.json() == {"run_id": CONFIRM_RUN, "status": "QUEUED"}
    params = boards.requests[-1]["variables"]["executionParams"]
    assert params["selector"]["jobName"] == CONFIRM
    assert params["runConfigData"] == {"ops": {"save_dc_index_standard": {"config": {
        "business_date": DAY, "review_version": VERSION, "requested_by": "23",
    }}}}
    standard = {
        "business_date": DAY, "review_version": VERSION, "raw_run_id": RAW_RUN,
        "reference_version": "standard-19", "boards": boards.review["current"], "version": CONFIRM_RUN,
    }
    boards.runs[CONFIRM_RUN]["status"] = "SUCCESS"
    boards.outputs[CONFIRM_RUN] = _output("save_dc_index_standard", "dc_index_standard", standard)
    assert boards.client.get(SILVER + "/board-standard").json() == {
        **boards.review, "standard": standard, "state": "ready", "reason": None, "can_confirm": False,
    }
    assert boards.client.get(f"{AUDIT}/runs/{CONFIRM_RUN}").json()["result"] == standard
    assert boards.client.post(RAW + "/board-confirm", json={"review_version": VERSION}).status_code == 409


@pytest.mark.parametrize(("action", "step"), [
    ("board-confirm", "save_dc_index_standard"), ("board-recheck", "recheck_dc_index"),
])
def test_history_candidate_passes_its_verified_version_to_dg(boards, action, step):
    boards.review["used_history"] = True
    response = boards.client.post(RAW + f"/{action}", json={"review_version": VERSION})
    assert response.status_code == 202
    config = boards.requests[-1]["variables"]["executionParams"]["runConfigData"]["ops"][step]["config"]
    assert config["use_history"] is True
    assert (config["business_date"], config["review_version"]) == (DAY, VERSION)


def test_board_operation_permissions_scope_and_retry_identity(boards):
    boards.user.is_admin = False
    assert boards.client.get(RAW + "/board-standard").status_code == 200
    assert boards.client.get(f"{AUDIT}/days/{DAY}").json()["can_operate"] is False
    request_count = len(boards.requests)
    assert boards.client.post(RAW + "/board-confirm", json={"review_version": VERSION}).status_code == 403
    assert boards.client.post(RAW + "/board-recheck", json={"review_version": VERSION}).status_code == 403
    assert boards.client.get(f"{AUDIT}/runs/{CONFIRM_RUN}").status_code == 403
    assert len(boards.requests) == request_count

    boards.user.is_admin = True
    assert boards.client.post(SILVER + "/board-confirm", json={"review_version": VERSION}).status_code == 422
    assert boards.client.post(RAW + "/board-confirm", json={"review_version": "old-version"}).status_code == 409
    assert boards.client.post(RAW + "/board-recheck", json={"review_version": VERSION, "codes": ["BK0003.DC"]}).status_code == 422
    assert boards.client.post(RAW.replace(DAY, "invalid") + "/board-confirm", json={"review_version": VERSION}).status_code == 422
    assert boards.client.get(f"{AUDIT}/runs/{RECHECK_RUN}").status_code == 404
    boards.runs[RUN] = _native_run(RUN, "daily_data_audit_summary_job", "SUCCESS")
    assert boards.client.get(f"{AUDIT}/runs/{RUN}").status_code == 404

    retry_path = RAW + "/board-recheck"
    old_run = str(uuid4())
    retry = {"review_version": VERSION, "retry_run_id": old_run}
    boards.runs[old_run] = _native_run(old_run, RECHECK, "FAILURE", day="2026-11-19")
    assert boards.client.post(retry_path, json=retry).status_code == 422
    boards.runs[old_run] = _native_run(old_run, RECHECK, "QUEUED")
    assert boards.client.post(retry_path, json=retry).status_code == 409
    assert not any("mutation" in x["query"] for x in boards.requests)
    boards.runs[old_run]["status"] = "FAILURE"
    assert boards.client.get(f"{AUDIT}/runs/{old_run}").json()["error"]["code"] == "board_run_failed"
    assert boards.client.post(retry_path, json=retry).status_code == 409
    boards.runs[old_run]["status"] = "SUCCESS"
    boards.outputs[old_run] = _output("recheck_dc_index", "dc_index_recheck", {
        "business_date": DAY, "review_version": VERSION, "run_id": old_run, "has_confirmed_gap": False,
        "results": [{"code": "BK0001.DC", "classification": {"status": "failed"}, "member": {"status": "not_returned"}}],
    })
    assert boards.client.post(retry_path, json=retry).status_code == 202
    config = boards.requests[-1]["variables"]["executionParams"]["runConfigData"]["ops"]["recheck_dc_index"]["config"]
    assert config["retry_run_id"] == old_run


def test_board_output_with_wrong_version_cannot_be_published_as_current(boards):
    boards.runs[RECHECK_RUN] = _native_run(RECHECK_RUN, RECHECK, "SUCCESS")
    boards.outputs[RECHECK_RUN] = _output("recheck_dc_index", "dc_index_recheck", {
        "business_date": DAY, "review_version": "wrong-version", "run_id": RECHECK_RUN,
        "results": [], "has_confirmed_gap": False,
    })
    assert boards.client.get(f"{AUDIT}/runs/{RECHECK_RUN}").status_code == 503
    assert boards.client.get(RAW + "/board-standard").status_code == 503
    assert boards.client.post(RAW + "/board-confirm", json={"review_version": VERSION}).status_code == 503
    assert not any("mutation" in x["query"] for x in boards.requests)


def test_missing_reference_is_readable_and_cannot_submit(boards):
    boards.review.update(review_version=None, reference=None, state="reference_missing", can_confirm=False)
    assert boards.client.get(RAW + "/board-standard").json() == boards.review
    assert boards.client.post(RAW + "/board-confirm", json={"review_version": VERSION}).status_code == 409
    assert all("DataAuditBoardRuns" not in x["query"] and "mutation" not in x["query"] for x in boards.requests)


def test_industry_change_alone_cannot_trigger_source_recheck(boards):
    for board in (*boards.review["added"], *boards.review["removed"]):
        board["category"] = "行业板块"
    assert boards.client.post(RAW + "/board-recheck", json={"review_version": VERSION}).status_code == 409
    assert not any("mutation" in x["query"] for x in boards.requests)
