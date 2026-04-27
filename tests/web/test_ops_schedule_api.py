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
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "display_name": "每日收盘维护",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "params_json": {"trade_date": "2026-03-30"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_type"] == "workflow"
    assert payload["target_key"] == "daily_market_close_maintenance"
    assert payload["target_display_name"] == "每日收盘后维护"
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


def test_ops_schedule_create_rejects_unschedulable_target(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "maintenance_action",
            "target_key": "maintenance.rebuild_index_kline_serving",
            "display_name": "错误配置",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_ops_schedule_create_returns_readable_once_time_validation_message(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "display_name": "单次维护",
            "schedule_type": "once",
            "timezone": "Asia/Shanghai",
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "单次排程必须填写下次运行时间"


def test_ops_schedule_create_rejects_dataset_action_without_maintain_suffix(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "dataset_action",
            "target_key": "daily",
            "display_name": "错误配置",
            "schedule_type": "cron",
            "cron_expr": "0 19 * * *",
            "timezone": "Asia/Shanghai",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_ops_schedule_list_update_pause_and_resume(app_client, user_factory, ops_schedule_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
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
    assert list_payload["items"][0]["target_display_name"] == "股票主数据"

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


def test_ops_schedule_delete_removes_schedule_and_records_revision(app_client, user_factory, ops_schedule_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
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

    # 删除后详情与修订查询都会返回 not_found，验证删除成功
    revisions_response = app_client.get(
        f"/api/v1/ops/schedules/{schedule.id}/revisions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revisions_response.status_code == 404
    assert revisions_response.json()["code"] == "not_found"


def test_ops_schedule_delete_active_schedule_pauses_before_delete(
    app_client,
    user_factory,
    ops_schedule_factory,
    db_session,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
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

    delete_response = app_client.delete(
        f"/api/v1/ops/schedules/{schedule.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 200

    from src.ops.models.ops.config_revision import ConfigRevision
    from sqlalchemy import select

    revisions = list(
        db_session.scalars(
            select(ConfigRevision)
            .where(ConfigRevision.object_type == "schedule")
            .where(ConfigRevision.object_id == str(schedule.id))
            .order_by(ConfigRevision.id.asc())
        )
    )
    actions = [item.action for item in revisions]
    assert actions[-2:] == ["paused", "deleted"]


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
            "target_type": "dataset_action",
            "target_key": "stock_basic.maintain",
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


def test_ops_schedule_probe_mode_creates_probe_rules_for_workflow(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    create_response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "display_name": "收盘探测触发",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
                "probe_config": {
                    "source_key": "tushare",
                    "window_start": "15:30",
                    "window_end": "17:00",
                    "probe_interval_seconds": 180,
                    "max_triggers_per_day": 1,
                    "workflow_dataset_keys": ["daily", "daily_basic"],
                },
            },
        )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["trigger_mode"] == "probe"
    assert created["probe_config"]["source_display_name"] == "Tushare"
    assert created["probe_config"]["workflow_dataset_targets"] == [
        {"dataset_key": "daily", "dataset_display_name": "股票日线"},
        {"dataset_key": "daily_basic", "dataset_display_name": "每日指标"},
    ]

    probe_response = app_client.get(
        f"/api/v1/ops/probes?schedule_id={created['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert probe_response.status_code == 200
    probe_payload = probe_response.json()
    assert probe_payload["total"] == 2
    dataset_keys = sorted(item["dataset_key"] for item in probe_payload["items"])
    assert dataset_keys == ["daily", "daily_basic"]
    names = sorted(item["name"] for item in probe_payload["items"])
    assert names == ["收盘探测触发 / 每日指标", "收盘探测触发 / 股票日线"]
    assert all(item["trigger_mode"] == "task_run" for item in probe_payload["items"])
    assert all(item["workflow_key"] == "daily_market_close_maintenance" for item in probe_payload["items"])
    assert all(item["rule_version"] == 1 for item in probe_payload["items"])
    assert all(item["on_success_action_json"]["action_type"] == "dataset_action" for item in probe_payload["items"])
    assert all("action_key" in item["on_success_action_json"] for item in probe_payload["items"])
    assert all("dataset_key" not in item["on_success_action_json"]["request"] for item in probe_payload["items"])
    assert all("action" not in item["on_success_action_json"]["request"] for item in probe_payload["items"])


def test_ops_schedule_probe_mode_rejects_unknown_workflow_dataset_key(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "display_name": "错误探测触发",
            "schedule_type": "cron",
            "trigger_mode": "probe",
            "cron_expr": "0 19 * * 1-5",
            "timezone": "Asia/Shanghai",
            "probe_config": {
                "source_key": "tushare",
                "workflow_dataset_keys": ["daily", "not_a_dataset"],
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
