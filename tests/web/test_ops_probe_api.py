from __future__ import annotations


def test_ops_probe_list_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/probes", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_probe_create_list_update_pause_resume_delete(app_client, user_factory, db_session) -> None:
    from sqlalchemy import select

    from src.ops.models.ops.config_revision import ConfigRevision

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    create = app_client.post(
        "/api/v1/ops/probes",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "收盘后日线探测",
            "dataset_key": "equity_daily",
            "source_key": "tushare",
            "window_start": "15:30",
            "window_end": "17:30",
            "probe_interval_seconds": 180,
            "probe_condition_json": {"metric": "max_trade_date", "op": ">=", "value": "today"},
            "on_success_action_json": {"action_type": "workflow", "action_key": "daily_market_close_sync"},
            "max_triggers_per_day": 2,
            "timezone_name": "Asia/Shanghai",
        },
    )
    assert create.status_code == 200
    created = create.json()
    probe_rule_id = created["id"]
    assert created["status"] == "active"
    assert created["dataset_key"] == "equity_daily"
    assert created["probe_interval_seconds"] == 180
    assert created["created_by_username"] == "admin"

    listed = app_client.get("/api/v1/ops/probes?dataset_key=equity_daily", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] == 1
    assert listed_payload["items"][0]["id"] == probe_rule_id

    updated = app_client.patch(
        f"/api/v1/ops/probes/{probe_rule_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "收盘后探测（更新）", "probe_interval_seconds": 120},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "收盘后探测（更新）"
    assert updated.json()["probe_interval_seconds"] == 120

    paused = app_client.post(f"/api/v1/ops/probes/{probe_rule_id}/pause", headers={"Authorization": f"Bearer {token}"})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = app_client.post(f"/api/v1/ops/probes/{probe_rule_id}/resume", headers={"Authorization": f"Bearer {token}"})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"

    deleted = app_client.delete(f"/api/v1/ops/probes/{probe_rule_id}", headers={"Authorization": f"Bearer {token}"})
    assert deleted.status_code == 200
    assert deleted.json()["id"] == probe_rule_id
    assert deleted.json()["status"] == "deleted"

    detail_after_delete = app_client.get(f"/api/v1/ops/probes/{probe_rule_id}", headers={"Authorization": f"Bearer {token}"})
    assert detail_after_delete.status_code == 404
    assert detail_after_delete.json()["code"] == "not_found"

    revisions = list(
        db_session.scalars(
            select(ConfigRevision)
            .where(ConfigRevision.object_type == "probe_rule")
            .where(ConfigRevision.object_id == str(probe_rule_id))
            .order_by(ConfigRevision.id.asc())
        )
    )
    assert [item.action for item in revisions] == ["created", "updated", "paused", "resumed", "deleted"]


def test_ops_probe_run_log_list_supports_rule_and_dataset_filters(
    app_client,
    user_factory,
    probe_rule_factory,
    probe_run_log_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    equity_rule = probe_rule_factory(name="股票日线探测", dataset_key="equity_daily", source_key="tushare")
    etf_rule = probe_rule_factory(name="ETF日线探测", dataset_key="etf_daily", source_key="biying")

    probe_run_log_factory(
        probe_rule_id=equity_rule.id,
        status="success",
        condition_matched=True,
        message="hit",
        payload_json={"max_trade_date": "2026-04-14"},
        triggered_execution_id=101,
    )
    probe_run_log_factory(
        probe_rule_id=etf_rule.id,
        status="failed",
        condition_matched=False,
        message="timeout",
        payload_json={"error": "timeout"},
    )

    all_runs = app_client.get("/api/v1/ops/probes/runs", headers={"Authorization": f"Bearer {token}"})
    assert all_runs.status_code == 200
    all_payload = all_runs.json()
    assert all_payload["total"] == 2
    assert {item["dataset_key"] for item in all_payload["items"]} == {"equity_daily", "etf_daily"}

    by_rule = app_client.get(f"/api/v1/ops/probes/{equity_rule.id}/runs", headers={"Authorization": f"Bearer {token}"})
    assert by_rule.status_code == 200
    by_rule_payload = by_rule.json()
    assert by_rule_payload["total"] == 1
    assert by_rule_payload["items"][0]["probe_rule_id"] == equity_rule.id
    assert by_rule_payload["items"][0]["status"] == "success"
    assert by_rule_payload["items"][0]["rule_version"] == 1
    assert by_rule_payload["items"][0]["result_code"] in {"miss", "hit", "error"}

    by_dataset = app_client.get(
        "/api/v1/ops/probes/runs?dataset_key=etf_daily",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert by_dataset.status_code == 200
    by_dataset_payload = by_dataset.json()
    assert by_dataset_payload["total"] == 1
    assert by_dataset_payload["items"][0]["dataset_key"] == "etf_daily"
    assert by_dataset_payload["items"][0]["status"] == "failed"
    assert by_dataset_payload["items"][0]["rule_version"] == 1
