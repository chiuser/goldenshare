from __future__ import annotations

from datetime import datetime, timezone


def test_ops_schedule_list_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/schedules", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_schedule_create_supports_schedulable_workflow_and_records_revision(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "spec_type": "workflow",
            "spec_key": "daily_market_close_sync",
            "display_name": "每日收盘同步",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "params_json": {"trade_date": "2026-03-30"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec_type"] == "workflow"
    assert payload["spec_key"] == "daily_market_close_sync"
    assert payload["spec_display_name"] == "每日收盘后同步"
    assert payload["status"] == "active"
    assert payload["next_run_at"] is not None

    revisions = app_client.get(
        f"/api/v1/ops/schedules/{payload['id']}/revisions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revisions.status_code == 200
    revisions_payload = revisions.json()
    assert revisions_payload["total"] == 1
    assert revisions_payload["items"][0]["action"] == "created"
    assert revisions_payload["items"][0]["changed_by_username"] == "admin"


def test_ops_schedule_create_rejects_unschedulable_spec(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "spec_type": "job",
            "spec_key": "backfill_index_series.index_weekly",
            "display_name": "错误配置",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_ops_schedule_list_update_pause_and_resume(app_client, user_factory, job_schedule_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    schedule = job_schedule_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        display_name="股票主数据刷新",
        status="active",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    list_response = app_client.get("/api/v1/ops/schedules", headers={"Authorization": f"Bearer {token}"})
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["id"] == schedule.id
    assert list_payload["items"][0]["spec_display_name"] == "历史同步 / stock_basic"

    update_response = app_client.patch(
        f"/api/v1/ops/schedules/{schedule.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "display_name": "股票主数据晚间刷新",
            "cron_expr": "30 20 * * *",
        },
    )
    assert update_response.status_code == 200
    update_payload = update_response.json()
    assert update_payload["display_name"] == "股票主数据晚间刷新"
    assert update_payload["cron_expr"] == "30 20 * * *"

    pause_response = app_client.post(
        f"/api/v1/ops/schedules/{schedule.id}/pause",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"

    resume_response = app_client.post(
        f"/api/v1/ops/schedules/{schedule.id}/resume",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resume_response.status_code == 200
    resume_payload = resume_response.json()
    assert resume_payload["status"] == "active"
    assert resume_payload["next_run_at"] is not None

    revisions_response = app_client.get(
        f"/api/v1/ops/schedules/{schedule.id}/revisions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revisions_response.status_code == 200
    revision_actions = [item["action"] for item in revisions_response.json()["items"]]
    assert revision_actions == ["resumed", "paused", "updated"]


def test_ops_schedule_delete_removes_schedule_and_records_revision(app_client, user_factory, job_schedule_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    schedule = job_schedule_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        display_name="股票主数据刷新",
        status="paused",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    delete_response = app_client.delete(
        f"/api/v1/ops/schedules/{schedule.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["id"] == schedule.id
    assert delete_response.json()["status"] == "deleted"

    list_response = app_client.get("/api/v1/ops/schedules", headers={"Authorization": f"Bearer {token}"})
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0

    revisions_response = app_client.get(
        f"/api/v1/ops/schedules/{schedule.id}/revisions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revisions_response.status_code == 404
    assert revisions_response.json()["code"] == "not_found"


def test_ops_schedule_detail_returns_not_found_for_missing_schedule(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/schedules/9999", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_ops_schedule_once_requires_timezone_aware_next_run_at(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "spec_type": "job",
            "spec_key": "sync_history.stock_basic",
            "display_name": "单次任务",
            "schedule_type": "once",
            "timezone": "Asia/Shanghai",
            "next_run_at": "2026-03-31T09:00:00",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_ops_schedule_preview_returns_next_cron_occurrences(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schedule_type": "cron",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "count": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule_type"] == "cron"
    assert payload["timezone"] == "Asia/Shanghai"
    assert len(payload["preview_times"]) == 3


def test_ops_schedule_preview_returns_once_next_run(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schedule_type": "once",
            "timezone": "Asia/Shanghai",
            "next_run_at": "2099-01-01T09:00:00+08:00",
            "count": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule_type"] == "once"
    assert len(payload["preview_times"]) == 1
    assert payload["preview_times"][0].startswith("2099-01-01T01:00:00")
