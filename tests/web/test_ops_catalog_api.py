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
    jobs = {item["key"]: item for item in payload["job_specs"]}
    workflow_keys = {item["key"] for item in payload["workflow_specs"]}

    assert "daily.maintain" in jobs
    assert "dc_hot.maintain" in jobs
    assert "index_weight.maintain" in jobs
    assert "maintenance.rebuild_dm" in jobs
    legacy_keys = [
        "sync" + "_daily.daily",
        "sync" + "_history.stock_basic",
        "backfill" + "_index_series.index_weight",
    ]
    assert all(key not in jobs for key in legacy_keys)
    assert "daily_market_close_sync" in workflow_keys
    assert "reference_data_refresh" in workflow_keys

    daily = jobs["daily.maintain"]
    assert daily["spec_type"] == "dataset_action"
    assert daily["resource_key"] == "daily"
    assert daily["resource_display_name"] == "股票日线"
    assert daily["supports_schedule"] is True
    assert [param["key"] for param in daily["supported_params"]][:3] == ["trade_date", "start_date", "end_date"]

    dc_hot = jobs["dc_hot.maintain"]
    dc_hot_params = {param["key"]: param for param in dc_hot["supported_params"]}
    assert dc_hot_params["market"]["options"] == ["A股市场", "ETF基金", "港股市场", "美股市场"]
    assert dc_hot_params["hot_type"]["options"] == ["人气榜", "飙升榜"]
    assert dc_hot_params["is_new"]["options"] == ["Y"]
    assert dc_hot_params["is_new"]["multi_value"] is False

    assert jobs["maintenance.rebuild_dm"]["spec_type"] == "job"


def test_ops_catalog_includes_schedule_binding_counts(app_client, user_factory, job_schedule_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    job_schedule_factory(
        spec_type="dataset_action",
        spec_key="stock_basic.maintain",
        display_name="股票主数据刷新",
        status="active",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    job_schedule_factory(
        spec_type="dataset_action",
        spec_key="stock_basic.maintain",
        display_name="股票主数据刷新（暂停）",
        status="paused",
        schedule_type="once",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    job_schedule_factory(
        spec_type="workflow",
        spec_key="daily_market_close_sync",
        display_name="每日收盘同步",
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
    jobs = {item["key"]: item for item in payload["job_specs"]}
    workflows = {item["key"]: item for item in payload["workflow_specs"]}
    assert jobs["stock_basic.maintain"]["schedule_binding_count"] == 2
    assert jobs["stock_basic.maintain"]["active_schedule_count"] == 1
    assert workflows["daily_market_close_sync"]["schedule_binding_count"] == 1
    assert workflows["daily_market_close_sync"]["active_schedule_count"] == 1
