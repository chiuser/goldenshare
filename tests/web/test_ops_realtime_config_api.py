from __future__ import annotations

from subprocess import CompletedProcess

from sqlalchemy import delete, func, select

from src.app.dependencies.realtime import get_realtime_state_store
from src.app.web.app import app
from src.foundation.realtime import InMemoryRealtimeStateStore, REALTIME_CONFIG_APPLY_STATE_HEALTH_KEY
from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.ops.models.ops.config_revision import ConfigRevision


def _login_headers(app_client, user_factory, *, username: str = "admin", is_admin: bool = True) -> dict[str, str]:
    user_factory(username=username, password="secret", is_admin=is_admin)
    login = app_client.post("/api/v1/auth/login", json={"username": username, "password": "secret"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _get_detail(app_client, headers: dict[str, str], object_key: str) -> dict:
    response = app_client.get(f"/api/v1/ops/realtime/config/objects/{object_key}", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_realtime_config_api_rejects_non_admin(app_client, user_factory) -> None:
    headers = _login_headers(app_client, user_factory, username="user", is_admin=False)
    body = {"runtime_config": {"enabled": True}}
    publish_body = {"version": 1, "runtime_config": {"enabled": True}}

    cases = [
        ("get", "/api/v1/ops/realtime/config/objects", None),
        ("get", "/api/v1/ops/realtime/config/objects/stock_rt_daily", None),
        ("post", "/api/v1/ops/realtime/config/objects/stock_rt_daily/validate", body),
        ("put", "/api/v1/ops/realtime/config/objects/stock_rt_daily", publish_body),
        ("get", "/api/v1/ops/realtime/config/objects/stock_rt_daily/revisions", None),
        ("post", "/api/v1/ops/realtime/config/collector/restart", None),
    ]
    for method, url, payload in cases:
        request = getattr(app_client, method)
        response = request(url, headers=headers, json=payload) if payload is not None else request(url, headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"


def test_realtime_config_list_and_detail_return_field_metadata(app_client, user_factory) -> None:
    headers = _login_headers(app_client, user_factory)

    list_response = app_client.get("/api/v1/ops/realtime/config/objects", headers=headers)
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert [item["object_key"] for item in list_payload["items"]] == ["stock_rt_daily", "stock_rt_min"]
    assert list_payload["items"][0]["apply_state"]["status"] == "unknown"
    assert list_payload["items"][0]["apply_state"]["restart_pending"] is None

    daily_detail = _get_detail(app_client, headers, "stock_rt_daily")
    assert daily_detail["apply_state"]["status"] == "unknown"
    daily_field_keys = [field["key"] for field in daily_detail["fields"] if field["editable"]]
    assert "source_timeout_seconds" not in daily_field_keys
    assert daily_detail["locked_config"]["feed_key"] == "tushare_stock_rt_k"
    assert any(field["key"] == "feed_key" and not field["editable"] for field in daily_detail["fields"])

    min_detail = _get_detail(app_client, headers, "stock_rt_min")
    min_fields = {field["key"]: field for field in min_detail["fields"]}
    assert min_fields["enabled_freqs"]["control"] == "checkbox_group"
    assert [item["value"] for item in min_fields["enabled_freqs"]["options"]] == ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"]
    assert min_detail["locked_config"]["feed_key_pattern"] == "tushare_stock_rt_min_{freq}"
    assert min_fields["feed_key_pattern"]["editable"] is False


def test_realtime_config_apply_state_reports_applied_and_pending(app_client, user_factory) -> None:
    store = InMemoryRealtimeStateStore()
    app.dependency_overrides[get_realtime_state_store] = lambda: store
    headers = _login_headers(app_client, user_factory)
    store.set_health(
        REALTIME_CONFIG_APPLY_STATE_HEALTH_KEY,
        {
            "collector_id": "collector-1",
            "process_started_at": "2026-06-02T10:00:00+08:00",
            "applied_at": "2026-06-02T10:01:00+08:00",
            "objects": {
                "stock_rt_daily": {"version": 1},
                "stock_rt_min": {"version": 0},
            },
        },
    )

    daily_detail = _get_detail(app_client, headers, "stock_rt_daily")
    min_detail = _get_detail(app_client, headers, "stock_rt_min")

    assert daily_detail["apply_state"] == {
        "status": "applied",
        "restart_pending": False,
        "published_version": 1,
        "applied_version": 1,
        "collector_id": "collector-1",
        "applied_at": "2026-06-02T10:01:00+08:00",
        "process_started_at": "2026-06-02T10:00:00+08:00",
        "message": "collector 已应用当前配置版本",
    }
    assert min_detail["apply_state"]["status"] == "pending_restart"
    assert min_detail["apply_state"]["restart_pending"] is True
    assert min_detail["apply_state"]["published_version"] == 1
    assert min_detail["apply_state"]["applied_version"] == 0


def test_realtime_config_validate_reports_diff_without_persisting(app_client, user_factory, db_session) -> None:
    headers = _login_headers(app_client, user_factory)
    detail = _get_detail(app_client, headers, "stock_rt_min")
    draft = dict(detail["effective_config"])
    draft["poll_interval_seconds"] = 90

    response = app_client.post(
        "/api/v1/ops/realtime/config/objects/stock_rt_min/validate",
        headers=headers,
        json={"runtime_config": draft},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert {"field": "poll_interval_seconds", "before": 60, "after": 90} in payload["diff"]
    assert payload["impact"]["requires_collector_restart"] is True
    assert "tushare_stock_rt_min_1min" in payload["impact"]["affected_feeds"]

    record = db_session.get(RealtimeRuntimeConfigRecord, "stock_rt_min")
    assert record.version == 1
    assert record.runtime_config_json["poll_interval_seconds"] == 60


def test_realtime_config_validate_reports_runtime_rule_errors(app_client, user_factory) -> None:
    headers = _login_headers(app_client, user_factory)
    detail = _get_detail(app_client, headers, "stock_rt_min")

    cases = [
        ({"enabled_freqs": ["BAD"]}, "invalid stock realtime minute freq"),
        ({"enabled_freqs": []}, "enabled_freqs cannot be empty"),
        ({"max_calls_per_minute": 4}, "cannot cover"),
        ({"stale_after_seconds": 30}, "stale_after_seconds must be greater than or equal to poll_interval_seconds"),
    ]
    for change, expected_message in cases:
        draft = dict(detail["effective_config"])
        draft.update(change)
        response = app_client.post(
            "/api/v1/ops/realtime/config/objects/stock_rt_min/validate",
            headers=headers,
            json={"runtime_config": draft},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is False
        assert payload["errors"][0]["code"] == "validation_error"
        assert expected_message in payload["errors"][0]["message"]


def test_realtime_config_rejects_locked_unknown_and_wrong_shape_fields(app_client, user_factory) -> None:
    headers = _login_headers(app_client, user_factory)
    min_detail = _get_detail(app_client, headers, "stock_rt_min")

    cases = [
        ({"ts_code_pattern": "600*.SH"}, "locked_field"),
        ({"feed_key_pattern": "changed_{freq}"}, "locked_field"),
        ({"unknown_field": 1}, "unknown_field"),
        ({"enabled_freqs": "1MIN,5MIN"}, "validation_error"),
    ]
    for change, expected_code in cases:
        draft = dict(min_detail["effective_config"])
        draft.update(change)
        response = app_client.post(
            "/api/v1/ops/realtime/config/objects/stock_rt_min/validate",
            headers=headers,
            json={"runtime_config": draft},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is False
        assert payload["errors"][0]["code"] == expected_code

    publish_response = app_client.put(
        "/api/v1/ops/realtime/config/objects/stock_rt_min",
        headers=headers,
        json={"version": min_detail["version"], "runtime_config": {**min_detail["effective_config"], "unknown_field": 1}},
    )
    assert publish_response.status_code == 422
    assert publish_response.json()["code"] == "unknown_field"


def test_realtime_config_publish_updates_record_and_records_revision(app_client, user_factory, db_session) -> None:
    headers = _login_headers(app_client, user_factory)
    detail = _get_detail(app_client, headers, "stock_rt_daily")
    first_draft = dict(detail["effective_config"])
    first_draft["enabled"] = True

    first_response = app_client.put(
        "/api/v1/ops/realtime/config/objects/stock_rt_daily",
        headers=headers,
        json={"version": detail["version"], "runtime_config": first_draft},
    )

    assert first_response.status_code == 200
    first_payload = first_response.json()
    assert first_payload["version"] == 2
    assert first_payload["effective_config"]["enabled"] is True
    assert first_payload["requires_collector_restart"] is True
    assert first_payload["warnings"][0]["message"] == "发布后需要重启 collector 才会生效"
    assert first_payload["revision_id"] is not None

    second_draft = dict(first_payload["effective_config"])
    second_draft["enabled"] = False
    second_response = app_client.put(
        "/api/v1/ops/realtime/config/objects/stock_rt_daily",
        headers=headers,
        json={"version": first_payload["version"], "runtime_config": second_draft},
    )
    assert second_response.status_code == 200
    assert second_response.json()["version"] == 3

    record = db_session.get(RealtimeRuntimeConfigRecord, "stock_rt_daily")
    assert record.version == 3
    assert record.runtime_config_json["enabled"] is False
    assert record.updated_by_user_id is not None

    revisions = app_client.get(
        "/api/v1/ops/realtime/config/objects/stock_rt_daily/revisions",
        headers=headers,
    )
    assert revisions.status_code == 200
    revisions_payload = revisions.json()
    assert revisions_payload["total"] == 2
    assert [item["after_json"]["version"] for item in revisions_payload["items"]] == [3, 2]
    assert revisions_payload["items"][0]["object_type"] == "realtime_runtime_config"
    assert revisions_payload["items"][0]["action"] == "published"
    assert revisions_payload["items"][0]["changed_by_username"] == "admin"


def test_realtime_config_publish_returns_pending_restart_when_collector_has_old_version(app_client, user_factory) -> None:
    store = InMemoryRealtimeStateStore()
    app.dependency_overrides[get_realtime_state_store] = lambda: store
    headers = _login_headers(app_client, user_factory)
    store.set_health(
        REALTIME_CONFIG_APPLY_STATE_HEALTH_KEY,
        {
            "collector_id": "collector-1",
            "process_started_at": "2026-06-02T10:00:00+08:00",
            "applied_at": "2026-06-02T10:01:00+08:00",
            "objects": {
                "stock_rt_daily": {"version": 1},
                "stock_rt_min": {"version": 1},
            },
        },
    )
    detail = _get_detail(app_client, headers, "stock_rt_daily")
    draft = dict(detail["effective_config"])
    draft["enabled"] = True

    response = app_client.put(
        "/api/v1/ops/realtime/config/objects/stock_rt_daily",
        headers=headers,
        json={"version": detail["version"], "runtime_config": draft},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 2
    assert payload["apply_state"]["status"] == "pending_restart"
    assert payload["apply_state"]["restart_pending"] is True
    assert payload["apply_state"]["applied_version"] == 1


def test_realtime_config_publish_rejects_stale_version_without_revision(app_client, user_factory, db_session) -> None:
    headers = _login_headers(app_client, user_factory)
    detail = _get_detail(app_client, headers, "stock_rt_daily")
    draft = dict(detail["effective_config"])
    draft["enabled"] = True

    response = app_client.put(
        "/api/v1/ops/realtime/config/objects/stock_rt_daily",
        headers=headers,
        json={"version": 0, "runtime_config": draft},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    record = db_session.get(RealtimeRuntimeConfigRecord, "stock_rt_daily")
    assert record.version == 1
    revision_count = db_session.scalar(
        select(func.count()).select_from(ConfigRevision).where(ConfigRevision.object_type == "realtime_runtime_config")
    )
    assert revision_count == 0


def test_realtime_config_missing_runtime_row_returns_structured_error(app_client, user_factory, db_session) -> None:
    headers = _login_headers(app_client, user_factory)
    db_session.execute(delete(RealtimeRuntimeConfigRecord).where(RealtimeRuntimeConfigRecord.object_key == "stock_rt_min"))
    db_session.commit()

    response = app_client.get("/api/v1/ops/realtime/config/objects", headers=headers)

    assert response.status_code == 422
    assert response.json()["code"] == "runtime_config_missing"


def test_realtime_config_restart_collector_uses_fixed_systemctl_command(app_client, user_factory, db_session, monkeypatch) -> None:
    headers = _login_headers(app_client, user_factory)
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> CompletedProcess[str]:
        calls.append(args)
        return CompletedProcess(args=args, returncode=0, stdout="active", stderr="")

    monkeypatch.setattr("src.ops.services.realtime_config_service._run_systemctl_command", fake_run)

    response = app_client.post("/api/v1/ops/realtime/config/collector/restart", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["active"] is True
    assert payload["service_name"] == "goldenshare-realtime-collector.service"
    assert calls == [
        ["restart", "goldenshare-realtime-collector.service"],
        ["status", "goldenshare-realtime-collector.service"],
    ]
    revision_count = db_session.scalar(select(func.count()).select_from(ConfigRevision))
    assert revision_count == 0


def test_realtime_config_restart_collector_returns_failed_on_systemctl_error(app_client, user_factory, monkeypatch) -> None:
    headers = _login_headers(app_client, user_factory)

    def fake_run(args: list[str]) -> CompletedProcess[str]:
        if args[0] == "restart":
            return CompletedProcess(args=args, returncode=1, stdout="", stderr="not allowed")
        return CompletedProcess(args=args, returncode=3, stdout="", stderr="inactive")

    monkeypatch.setattr("src.ops.services.realtime_config_service._run_systemctl_command", fake_run)

    response = app_client.post("/api/v1/ops/realtime/config/collector/restart", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["active"] is False
    assert payload["message"] == "not allowed"
