from __future__ import annotations


def test_ops_catalog_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/catalog", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"

def test_ops_catalog_returns_registered_specs_for_admin(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/catalog", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    job_keys = {item["key"] for item in payload["job_specs"]}
    workflow_keys = {item["key"] for item in payload["workflow_specs"]}

    assert "sync_history.stock_basic" in job_keys
    assert "sync_history.hk_basic" in job_keys
    assert "sync_history.us_basic" in job_keys
    assert "sync_history.ths_member" in job_keys
    assert "sync_daily.daily" in job_keys
    assert "backfill_index_series.index_weight" in job_keys
    assert "maintenance.rebuild_dm" in job_keys
    assert "daily_market_close_sync" in workflow_keys
    assert "reference_data_refresh" in workflow_keys
    workflows = {item["key"]: item for item in payload["workflow_specs"]}
    jobs = {item["key"]: item for item in payload["job_specs"]}
    assert jobs["sync_history.ths_member"]["supports_schedule"] is True
    assert next(param for param in jobs["sync_history.hk_basic"]["supported_params"] if param["key"] == "list_status")["options"] == ["L", "D", "P"]
    assert next(param for param in jobs["sync_history.us_basic"]["supported_params"] if param["key"] == "classify")["options"] == ["ADR", "GDR", "EQ"]
    dc_hot_daily = jobs["sync_daily.dc_hot"]
    assert [param["key"] for param in dc_hot_daily["supported_params"]] == ["trade_date", "ts_code", "market", "hot_type", "is_new"]
    assert next(param for param in dc_hot_daily["supported_params"] if param["key"] == "market")["options"] == ["A股市场", "ETF基金", "港股市场", "美股市场"]
    assert workflows["daily_market_close_sync"]["supports_schedule"] is True
    assert workflows["index_extension_backfill"]["supports_schedule"] is False


def test_ops_catalog_includes_schedule_binding_counts(app_client, user_factory, job_schedule_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    job_schedule_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        display_name="股票主数据刷新",
        status="active",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        created_by_user_id=admin.id,
        updated_by_user_id=admin.id,
    )
    job_schedule_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
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
    assert jobs["sync_history.stock_basic"]["schedule_binding_count"] == 2
    assert jobs["sync_history.stock_basic"]["active_schedule_count"] == 1
    assert workflows["daily_market_close_sync"]["schedule_binding_count"] == 1
    assert workflows["daily_market_close_sync"]["active_schedule_count"] == 1
