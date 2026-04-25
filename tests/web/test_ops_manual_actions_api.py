from __future__ import annotations


def _admin_headers(app_client, user_factory) -> dict[str, str]:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _actions_by_key(payload: dict) -> dict[str, dict]:
    return {
        action["action_key"]: action
        for group in payload["groups"]
        for action in group["actions"]
    }


def test_ops_manual_actions_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/manual-actions", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_manual_actions_returns_date_model_driven_catalog(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.get("/api/v1/ops/manual-actions", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    group_keys = [group["group_key"] for group in payload["groups"]]
    assert "equity_market" in group_keys
    assert "reference_data" in group_keys
    assert "workflow" in group_keys

    actions = _actions_by_key(payload)
    assert actions["daily"]["display_name"] == "维护股票日线"
    assert actions["daily"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert actions["daily"]["time_form"]["control"] == "trade_date_or_range"
    assert actions["daily"]["time_form"]["allowed_modes"] == ["point", "range"]
    assert actions["daily"]["time_form"]["selection_rule"] == "trading_day_only"
    assert actions["daily"]["action_type"] == "dataset_action"
    assert actions["daily"]["route_spec_keys"] == ["daily.maintain"]

    assert actions["stk_period_bar_week"]["time_form"]["selection_rule"] == "week_last_trading_day"
    assert actions["stk_period_bar_month"]["time_form"]["selection_rule"] == "month_last_trading_day"
    assert actions["dividend"]["time_form"]["control"] == "calendar_date_or_range"
    assert actions["dividend"]["time_form"]["allowed_modes"] == ["range"]
    assert actions["broker_recommend"]["time_form"]["control"] == "month_or_range"
    assert actions["broker_recommend"]["time_form"]["allowed_modes"] == ["point", "range"]
    assert actions["index_weight"]["time_form"]["control"] == "month_window_range"
    assert actions["index_weight"]["time_form"]["allowed_modes"] == ["range"]
    assert actions["stock_basic"]["time_form"]["control"] == "none"
    assert actions["stock_basic"]["time_form"]["allowed_modes"] == ["none"]

    dc_hot_filter_keys = [item["key"] for item in actions["dc_hot"]["filters"]]
    assert dc_hot_filter_keys == ["ts_code", "market", "hot_type", "is_new"]
    assert "offset" not in dc_hot_filter_keys
    assert "limit" not in dc_hot_filter_keys

    assert actions["stk_mins"]["time_form"]["control"] == "trade_date_or_range"
    assert actions["stk_mins"]["time_form"]["allowed_modes"] == ["point", "range"]
    assert actions["stk_mins"]["route_spec_keys"] == ["stk_mins.maintain"]
    stk_mins_filter_keys = [item["key"] for item in actions["stk_mins"]["filters"]]
    assert stk_mins_filter_keys == ["ts_code", "freq"]


def test_ops_manual_action_execution_creates_point_job(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/daily/executions",
        headers=headers,
        json={"time_input": {"mode": "point", "trade_date": "2026-04-24"}, "filters": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec_type"] == "dataset_action"
    assert payload["spec_key"] == "daily.maintain"
    assert payload["status"] == "queued"
    assert payload["run_profile"] == "point_incremental"
    assert payload["params_json"] == {
        "dataset_key": "daily",
        "action": "maintain",
        "trade_date": "2026-04-24",
        "time_input": {"mode": "point", "trade_date": "2026-04-24"},
        "filters": {},
    }


def test_ops_manual_action_execution_creates_range_job_with_filters(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/dc_hot/executions",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-04-01", "end_date": "2026-04-24"},
            "filters": {"market": ["A股市场", "ETF基金"], "hot_type": ["人气榜"], "is_new": "Y"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec_type"] == "dataset_action"
    assert payload["spec_key"] == "dc_hot.maintain"
    assert payload["run_profile"] == "range_rebuild"
    assert payload["params_json"] == {
        "market": ["A股市场", "ETF基金"],
        "hot_type": ["人气榜"],
        "is_new": "Y",
        "start_date": "2026-04-01",
        "end_date": "2026-04-24",
        "dataset_key": "dc_hot",
        "action": "maintain",
        "time_input": {"mode": "range", "start_date": "2026-04-01", "end_date": "2026-04-24"},
        "filters": {"market": ["A股市场", "ETF基金"], "hot_type": ["人气榜"], "is_new": "Y"},
    }


def test_ops_manual_action_execution_applies_dc_hot_safe_defaults(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/dc_hot/executions",
        headers=headers,
        json={
            "time_input": {"mode": "point", "trade_date": "2026-04-24"},
            "filters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec_key"] == "dc_hot.maintain"
    assert payload["run_profile"] == "point_incremental"
    assert payload["params_json"] == {
        "market": ["A股市场", "ETF基金", "港股市场", "美股市场"],
        "hot_type": ["人气榜", "飙升榜"],
        "is_new": "Y",
        "trade_date": "2026-04-24",
        "dataset_key": "dc_hot",
        "action": "maintain",
        "time_input": {"mode": "point", "trade_date": "2026-04-24"},
        "filters": {
            "market": ["A股市场", "ETF基金", "港股市场", "美股市场"],
            "hot_type": ["人气榜", "飙升榜"],
            "is_new": "Y",
        },
    }


def test_ops_manual_action_execution_routes_stk_mins_to_minute_history(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/stk_mins/executions",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-04-23", "end_date": "2026-04-24"},
            "filters": {"freq": ["30min", "60min"]},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec_key"] == "stk_mins.maintain"
    assert payload["run_profile"] == "range_rebuild"
    assert payload["params_json"] == {
        "freq": ["30min", "60min"],
        "start_date": "2026-04-23",
        "end_date": "2026-04-24",
        "dataset_key": "stk_mins",
        "action": "maintain",
        "time_input": {"mode": "range", "start_date": "2026-04-23", "end_date": "2026-04-24"},
        "filters": {"freq": ["30min", "60min"]},
    }


def test_ops_manual_action_execution_routes_natural_day_range_to_dataset_action(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/dividend/executions",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-04-01", "end_date": "2026-04-24"},
            "filters": {"ts_code": "000001.SZ"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec_key"] == "dividend.maintain"
    assert payload["run_profile"] == "range_rebuild"
    assert payload["params_json"] == {
        "ts_code": "000001.SZ",
        "start_date": "2026-04-01",
        "end_date": "2026-04-24",
        "dataset_key": "dividend",
        "action": "maintain",
        "time_input": {"mode": "range", "start_date": "2026-04-01", "end_date": "2026-04-24"},
        "filters": {"ts_code": "000001.SZ"},
    }


def test_ops_manual_action_execution_supports_month_and_month_window(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    month_point = app_client.post(
        "/api/v1/ops/manual-actions/broker_recommend/executions",
        headers=headers,
        json={"time_input": {"mode": "point", "month": "2026-04"}, "filters": {}},
    )
    month_range = app_client.post(
        "/api/v1/ops/manual-actions/broker_recommend/executions",
        headers=headers,
        json={"time_input": {"mode": "range", "start_month": "2026-04", "end_month": "2026-06"}, "filters": {}},
    )
    month_window = app_client.post(
        "/api/v1/ops/manual-actions/index_weight/executions",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_month": "2026-04", "end_month": "2026-06"},
            "filters": {"index_code": "000300.SH"},
        },
    )

    assert month_point.status_code == 200
    assert month_point.json()["spec_key"] == "broker_recommend.maintain"
    assert month_point.json()["params_json"] == {
        "dataset_key": "broker_recommend",
        "action": "maintain",
        "month": "202604",
        "time_input": {"mode": "point", "month": "202604"},
        "filters": {},
    }

    assert month_range.status_code == 200
    assert month_range.json()["spec_key"] == "broker_recommend.maintain"
    assert month_range.json()["params_json"] == {
        "dataset_key": "broker_recommend",
        "action": "maintain",
        "start_month": "202604",
        "end_month": "202606",
        "time_input": {"mode": "range", "start_month": "202604", "end_month": "202606"},
        "filters": {},
    }

    assert month_window.status_code == 200
    assert month_window.json()["spec_key"] == "index_weight.maintain"
    assert month_window.json()["params_json"] == {
        "index_code": "000300.SH",
        "start_date": "2026-04-01",
        "end_date": "2026-06-30",
        "dataset_key": "index_weight",
        "action": "maintain",
        "time_input": {"mode": "range", "start_date": "2026-04-01", "end_date": "2026-06-30"},
        "filters": {"index_code": "000300.SH"},
    }


def test_ops_manual_action_execution_rejects_unknown_filter(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/daily/executions",
        headers=headers,
        json={
            "time_input": {"mode": "point", "trade_date": "2026-04-24"},
            "filters": {"offset": 100},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
