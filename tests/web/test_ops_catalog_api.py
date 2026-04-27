from __future__ import annotations


def _admin_token(app_client, user_factory) -> str:  # type: ignore[no-untyped-def]
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    return login.json()["token"]


def test_ops_catalog_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/catalog", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_catalog_returns_dataset_actions_for_admin(app_client, user_factory) -> None:
    token = _admin_token(app_client, user_factory)

    response = app_client.get("/api/v1/ops/catalog", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    actions = {item["key"]: item for item in payload["actions"]}
    workflow_keys = {item["key"] for item in payload["workflows"]}
    sources = {item["source_key"]: item for item in payload["sources"]}

    assert "daily.maintain" in actions
    assert "dc_hot.maintain" in actions
    assert "index_weight.maintain" in actions
    assert "maintenance.rebuild_dm" in actions
    legacy_keys = [
        "sync" + "_daily.daily",
        "sync" + "_history.stock_basic",
        "back" + "fill" + "_index_series.index_weight",
    ]
    assert all(key not in actions for key in legacy_keys)
    assert "daily_market_close_maintenance" in workflow_keys
    assert "reference_data_refresh" in workflow_keys
    assert "index_extension_maintenance" in workflow_keys
    assert "index_extension_" + "back" + "fill" not in workflow_keys
    assert {item["domain_display_name"] for item in payload["workflows"]} == {"工作流"}
    assert sources["tushare"]["display_name"] == "Tushare"
    assert sources["biying"]["display_name"] == "Biying"

    daily = actions["daily.maintain"]
    assert daily["action_type"] == "dataset_action"
    assert daily["target_key"] == "daily"
    assert daily["target_display_name"] == "股票日线"
    assert daily["schedule_enabled"] is True
    assert [param["key"] for param in daily["parameters"]][:3] == ["trade_date", "start_date", "end_date"]

    dc_hot = actions["dc_hot.maintain"]
    dc_hot_params = {param["key"]: param for param in dc_hot["parameters"]}
    assert dc_hot_params["market"]["options"] == ["A股市场", "ETF基金", "港股市场", "美股市场"]
    assert dc_hot_params["market"]["default_value"] == ["A股市场", "ETF基金", "港股市场", "美股市场"]
    assert dc_hot_params["hot_type"]["options"] == ["人气榜", "飙升榜"]
    assert dc_hot_params["hot_type"]["default_value"] == ["人气榜", "飙升榜"]
    assert dc_hot_params["is_new"]["options"] == ["Y"]
    assert dc_hot_params["is_new"]["multi_value"] is False
    assert dc_hot_params["is_new"]["default_value"] == "Y"

    assert actions["maintenance.rebuild_dm"]["action_type"] == "maintenance_action"
    assert actions["maintenance.rebuild_dm"]["display_name"] == "刷新数据集市快照"


def test_ops_catalog_includes_schedule_binding_counts(app_client, user_factory, ops_schedule_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
        display_name="股票主数据刷新",
        status="active",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
        display_name="股票主数据刷新（暂停）",
        status="paused",
        schedule_type="once",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    ops_schedule_factory(
        target_type="workflow",
        target_key="daily_market_close_maintenance",
        display_name="每日收盘维护",
        status="active",
        schedule_type="cron",
        cron_expr="0 19 * * 1-5",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/catalog", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    actions = {item["key"]: item for item in payload["actions"]}
    workflows = {item["key"]: item for item in payload["workflows"]}
    assert actions["stock_basic.maintain"]["schedule_binding_count"] == 2
    assert actions["stock_basic.maintain"]["active_schedule_count"] == 1
    assert workflows["daily_market_close_maintenance"]["schedule_binding_count"] == 1
    assert workflows["daily_market_close_maintenance"]["active_schedule_count"] == 1
