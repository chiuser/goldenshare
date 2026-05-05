from __future__ import annotations

import pytest
from sqlalchemy import select

from src.ops.action_catalog import END_DATE_PARAM, START_DATE_PARAM, TRADE_DATE_PARAM, WORKFLOW_DEFINITION_REGISTRY, WorkflowDefinition
from src.ops.models.ops.task_run import TaskRun


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


def _time_modes(action: dict) -> dict[str, dict]:
    return {
        item["mode"]: item
        for item in action["time_form"]["modes"]
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
    assert "leader_board" in group_keys
    assert "workflow" in group_keys
    equity_group = next(group for group in payload["groups"] if group["group_key"] == "equity_market")
    assert equity_group["group_label"] == "A股行情"
    leader_board_group = next(group for group in payload["groups"] if group["group_key"] == "leader_board")
    assert leader_board_group["group_label"] == "榜单"
    workflow_group = next(group for group in payload["groups"] if group["group_key"] == "workflow")
    assert workflow_group["group_label"] == "工作流"

    actions = _actions_by_key(payload)
    assert any(action["action_key"] == "dc_hot.maintain" for action in leader_board_group["actions"])
    assert actions["daily.maintain"]["display_name"] == "维护股票日线"
    assert actions["daily.maintain"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert actions["daily.maintain"]["time_form"]["default_mode"] == "point"
    assert [item["mode"] for item in actions["daily.maintain"]["time_form"]["modes"]] == ["point", "range"]
    daily_modes = _time_modes(actions["daily.maintain"])
    assert daily_modes["point"]["control"] == "trade_date"
    assert daily_modes["point"]["selection_rule"] == "trading_day_only"
    assert daily_modes["range"]["control"] == "trade_date_range"
    assert daily_modes["range"]["selection_rule"] == "trading_day_only"
    assert actions["daily.maintain"]["action_type"] == "dataset_action"

    assert _time_modes(actions["stk_period_bar_week.maintain"])["point"]["control"] == "calendar_date"
    assert _time_modes(actions["stk_period_bar_week.maintain"])["point"]["selection_rule"] == "week_friday"
    assert _time_modes(actions["stk_period_bar_month.maintain"])["point"]["control"] == "calendar_date"
    assert _time_modes(actions["stk_period_bar_month.maintain"])["point"]["selection_rule"] == "month_end"
    assert [item["mode"] for item in actions["dividend.maintain"]["time_form"]["modes"]] == ["range"]
    assert _time_modes(actions["dividend.maintain"])["range"]["control"] == "calendar_date_range"
    assert [item["mode"] for item in actions["broker_recommend.maintain"]["time_form"]["modes"]] == ["point", "range"]
    assert _time_modes(actions["broker_recommend.maintain"])["point"]["control"] == "month"
    assert _time_modes(actions["broker_recommend.maintain"])["range"]["control"] == "month_range"
    assert [item["mode"] for item in actions["index_weight.maintain"]["time_form"]["modes"]] == ["range"]
    assert _time_modes(actions["index_weight.maintain"])["range"]["control"] == "month_window_range"
    assert [item["mode"] for item in actions["stock_basic.maintain"]["time_form"]["modes"]] == ["none"]
    assert _time_modes(actions["stock_basic.maintain"])["none"]["control"] == "none"
    for action_key in (
        "bse_mapping.maintain",
        "etf_basic.maintain",
        "etf_index.maintain",
        "hk_basic.maintain",
        "stock_company.maintain",
        "ths_index.maintain",
        "ths_member.maintain",
        "us_basic.maintain",
    ):
        assert actions[action_key]["date_model"]["input_shape"] == "none"
        assert actions[action_key]["date_model"]["window_mode"] == "none"
        assert [item["mode"] for item in actions[action_key]["time_form"]["modes"]] == ["none"]
        assert _time_modes(actions[action_key])["none"]["control"] == "none"
    assert actions["trade_cal.maintain"]["time_form"]["default_mode"] == "none"
    assert [item["mode"] for item in actions["trade_cal.maintain"]["time_form"]["modes"]] == ["none", "point", "range"]
    trade_cal_modes = _time_modes(actions["trade_cal.maintain"])
    assert trade_cal_modes["none"]["control"] == "none"
    assert trade_cal_modes["point"]["control"] == "calendar_date"
    assert trade_cal_modes["point"]["selection_rule"] == "calendar_day"
    assert trade_cal_modes["range"]["control"] == "calendar_date_range"
    assert trade_cal_modes["range"]["selection_rule"] == "calendar_day"
    assert actions["bak_basic.maintain"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert [item["mode"] for item in actions["bak_basic.maintain"]["time_form"]["modes"]] == ["point", "range"]
    bak_basic_modes = _time_modes(actions["bak_basic.maintain"])
    assert bak_basic_modes["point"]["control"] == "trade_date"
    assert bak_basic_modes["point"]["selection_rule"] == "trading_day_only"
    assert bak_basic_modes["range"]["control"] == "trade_date_range"
    assert bak_basic_modes["range"]["selection_rule"] == "trading_day_only"
    assert actions["namechange.maintain"]["date_model"]["input_shape"] == "none"
    assert [item["mode"] for item in actions["namechange.maintain"]["time_form"]["modes"]] == ["none"]
    namechange_modes = _time_modes(actions["namechange.maintain"])
    assert namechange_modes["none"]["control"] == "none"
    assert namechange_modes["none"]["selection_rule"] == "none"
    assert actions["st.maintain"]["date_model"]["input_shape"] == "ann_date_or_start_end"
    assert [item["mode"] for item in actions["st.maintain"]["time_form"]["modes"]] == ["point", "range"]
    st_modes = _time_modes(actions["st.maintain"])
    assert st_modes["point"]["control"] == "calendar_date"
    assert st_modes["point"]["selection_rule"] == "calendar_day"
    assert st_modes["range"]["control"] == "calendar_date_range"
    assert st_modes["range"]["selection_rule"] == "calendar_day"

    single_code_actions = (
        "daily.maintain",
        "adj_factor.maintain",
        "cyq_perf.maintain",
        "fund_daily.maintain",
        "index_daily.maintain",
        "index_daily_basic.maintain",
    )
    for action_key in single_code_actions:
        filter_keys = [item["key"] for item in actions[action_key]["filters"]]
        assert filter_keys == ["ts_code"]

    assert [item["key"] for item in actions["bse_mapping.maintain"]["filters"]] == ["o_code", "n_code"]
    assert [item["key"] for item in actions["bak_basic.maintain"]["filters"]] == ["ts_code"]
    assert [item["key"] for item in actions["namechange.maintain"]["filters"]] == ["ts_code"]
    st_filters = {item["key"]: item for item in actions["st.maintain"]["filters"]}
    assert list(st_filters) == ["ts_code", "imp_date"]
    assert st_filters["imp_date"]["param_type"] == "date"
    stock_company_filters = {item["key"]: item for item in actions["stock_company.maintain"]["filters"]}
    assert list(stock_company_filters) == ["ts_code", "exchange"]
    assert stock_company_filters["exchange"]["param_type"] == "enum"
    assert stock_company_filters["exchange"]["multi_value"] is True
    assert stock_company_filters["exchange"]["options"] == ["SSE", "SZSE", "BSE"]
    assert stock_company_filters["exchange"]["default_value"] == ["SSE", "SZSE", "BSE"]

    dc_hot_filter_keys = [item["key"] for item in actions["dc_hot.maintain"]["filters"]]
    dc_hot_filters = {item["key"]: item for item in actions["dc_hot.maintain"]["filters"]}
    assert dc_hot_filter_keys == ["ts_code", "market", "hot_type", "is_new"]
    assert "offset" not in dc_hot_filter_keys
    assert "limit" not in dc_hot_filter_keys
    assert dc_hot_filters["market"]["default_value"] == ["A股市场", "ETF基金", "港股市场", "美股市场"]
    assert dc_hot_filters["hot_type"]["default_value"] == ["人气榜", "飙升榜"]
    assert dc_hot_filters["is_new"]["default_value"] == "Y"

    assert [item["mode"] for item in actions["stk_mins.maintain"]["time_form"]["modes"]] == ["point", "range"]
    assert _time_modes(actions["stk_mins.maintain"])["point"]["control"] == "trade_date"
    stk_mins_filter_keys = [item["key"] for item in actions["stk_mins.maintain"]["filters"]]
    assert stk_mins_filter_keys == ["ts_code", "freq"]

    suspend_d_filters = {item["key"]: item for item in actions["suspend_d.maintain"]["filters"]}
    assert suspend_d_filters["suspend_type"]["param_type"] == "enum"
    assert suspend_d_filters["suspend_type"]["multi_value"] is True
    assert suspend_d_filters["suspend_type"]["options"] == ["S", "R"]

    dc_member_filters = {item["key"]: item for item in actions["dc_member.maintain"]["filters"]}
    assert dc_member_filters["idx_type"]["param_type"] == "enum"
    assert dc_member_filters["idx_type"]["multi_value"] is True
    assert dc_member_filters["idx_type"]["options"] == ["行业板块", "概念板块", "地域板块"]

    assert actions["news.maintain"]["display_name"] == "维护新闻快讯"
    assert actions["news.maintain"]["date_model"]["observed_field"] == "news_time"
    assert [item["mode"] for item in actions["news.maintain"]["time_form"]["modes"]] == ["point", "range"]
    assert _time_modes(actions["news.maintain"])["point"]["control"] == "calendar_date"
    news_filters = {item["key"]: item for item in actions["news.maintain"]["filters"]}
    assert news_filters["src"]["param_type"] == "enum"
    assert news_filters["src"]["multi_value"] is True
    assert news_filters["src"]["options"] == [
        "sina",
        "wallstreetcn",
        "10jqka",
        "eastmoney",
        "yuncaijing",
        "fenghuang",
        "jinrongjie",
        "cls",
        "yicai",
    ]

    assert [item["mode"] for item in actions["workflow:daily_market_close_maintenance"]["time_form"]["modes"]] == ["point", "range"]
    assert _time_modes(actions["workflow:daily_market_close_maintenance"])["point"]["control"] == "trade_date"
    assert [item["mode"] for item in actions["workflow:daily_moneyflow_maintenance"]["time_form"]["modes"]] == ["point", "range"]
    assert [item["mode"] for item in actions["workflow:reference_data_natural_day_maintenance"]["time_form"]["modes"]] == ["point", "range"]
    assert _time_modes(actions["workflow:reference_data_natural_day_maintenance"])["point"]["control"] == "calendar_date"
    assert _time_modes(actions["workflow:reference_data_natural_day_maintenance"])["range"]["control"] == "calendar_date_range"
    assert [item["mode"] for item in actions["workflow:index_extension_maintenance"]["time_form"]["modes"]] == ["range"]
    assert "交易日历（按完整日历刷新）" in actions["workflow:reference_data_refresh"]["description"]


def test_ops_manual_actions_renders_natural_day_workflow_with_calendar_date_controls(app_client, user_factory, monkeypatch) -> None:
    workflow = WorkflowDefinition(
        key="test_reference_data_natural_day_workflow",
        display_name="基础数据自然日测试流程",
        description="按自然日维护测试流程。",
        parameters=(TRADE_DATE_PARAM, START_DATE_PARAM, END_DATE_PARAM),
        steps=(),
        schedule_enabled=True,
        manual_enabled=True,
        time_regime="natural_day",
    )
    monkeypatch.setitem(WORKFLOW_DEFINITION_REGISTRY, workflow.key, workflow)
    headers = _admin_headers(app_client, user_factory)

    response = app_client.get("/api/v1/ops/manual-actions", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    actions = _actions_by_key(payload)
    action = actions["workflow:test_reference_data_natural_day_workflow"]
    modes = _time_modes(action)
    assert [item["mode"] for item in action["time_form"]["modes"]] == ["point", "range"]
    assert modes["point"]["control"] == "calendar_date"
    assert modes["point"]["selection_rule"] == "calendar_day"
    assert modes["range"]["control"] == "calendar_date_range"
    assert modes["range"]["selection_rule"] == "calendar_day"


def test_ops_manual_action_task_run_creates_point_job(app_client, user_factory, db_session) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/daily.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "point", "trade_date": "2026-04-24"}, "filters": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["task_type"] == "dataset_action"
    assert payload["run"]["resource_key"] == "daily"
    assert payload["run"]["action"] == "maintain"
    assert payload["run"]["status"] == "queued"
    assert payload["run"]["time_input"] == {"mode": "point", "trade_date": "2026-04-24"}
    assert payload["run"]["filters"] == {}
    task_run = db_session.scalar(select(TaskRun).where(TaskRun.id == payload["run"]["id"]))
    assert task_run is not None
    assert task_run.request_payload_json == {
        "task_type": "dataset_action",
        "resource_key": "daily",
        "action": "maintain",
        "time_input": {"mode": "point", "trade_date": "2026-04-24"},
        "filters": {},
    }


def test_ops_manual_action_task_run_supports_trade_cal_default_none_mode(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/trade_cal.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "none"}, "filters": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "trade_cal"
    assert payload["run"]["time_input"] == {"mode": "none"}
    assert payload["run"]["filters"] == {}


def test_ops_manual_action_task_run_supports_bse_mapping_snapshot_filters(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/bse_mapping.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "none"}, "filters": {"o_code": "838163.BJ"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "bse_mapping"
    assert payload["run"]["time_input"] == {"mode": "none"}
    assert payload["run"]["filters"] == {"o_code": "838163.BJ"}


def test_ops_manual_action_task_run_supports_bak_basic_point_filters(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/bak_basic.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "point", "trade_date": "2026-04-24"}, "filters": {"ts_code": "000001.SZ"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "bak_basic"
    assert payload["run"]["time_input"] == {"mode": "point", "trade_date": "2026-04-24"}
    assert payload["run"]["filters"] == {"ts_code": "000001.SZ"}


def test_ops_manual_action_task_run_applies_stock_company_exchange_defaults(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/stock_company.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "none"}, "filters": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "stock_company"
    assert payload["run"]["time_input"] == {"mode": "none"}
    assert payload["run"]["filters"] == {"exchange": ["SSE", "SZSE", "BSE"]}


def test_ops_manual_action_task_run_routes_namechange_to_snapshot_mode(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/namechange.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "none"}, "filters": {"ts_code": "000001.SZ"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "namechange"
    assert payload["run"]["time_input"] == {"mode": "none"}
    assert payload["run"]["filters"] == {"ts_code": "000001.SZ"}


def test_ops_manual_action_task_run_routes_st_range_to_ann_date_mode(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/st.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-04-23", "end_date": "2026-04-24"},
            "filters": {"imp_date": "2026-04-25"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "st"
    assert payload["run"]["time_input"] == {
        "mode": "range",
        "start_date": "2026-04-23",
        "end_date": "2026-04-24",
        "date_field": "ann_date",
    }
    assert payload["run"]["filters"] == {"imp_date": "2026-04-25"}


def test_ops_manual_action_task_run_returns_readable_not_found_message(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/not_exist/task-runs",
        headers=headers,
        json={"time_input": {"mode": "none"}, "filters": {}},
    )

    assert response.status_code == 404
    assert response.json()["message"] == "手动任务不存在"


def test_ops_manual_action_task_run_creates_range_job_with_filters(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/dc_hot.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-04-01", "end_date": "2026-04-24"},
            "filters": {"market": ["A股市场", "ETF基金"], "hot_type": ["人气榜"], "is_new": "Y"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "dc_hot"
    assert payload["run"]["time_input"] == {"mode": "range", "start_date": "2026-04-01", "end_date": "2026-04-24"}
    assert payload["run"]["filters"] == {
        "market": ["A股市场", "ETF基金"],
        "hot_type": ["人气榜"],
        "is_new": "Y",
    }


def test_ops_manual_action_task_run_returns_readable_time_validation_message(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/daily.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "range", "start_date": "2026-04-24", "end_date": "2026-04-01"}, "filters": {}},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "开始日期不能晚于结束日期"


@pytest.mark.parametrize(
    "action_key",
    (
        "daily.maintain",
        "adj_factor.maintain",
        "cyq_perf.maintain",
        "fund_daily.maintain",
        "index_daily.maintain",
        "index_daily_basic.maintain",
    ),
)
def test_ops_manual_action_task_run_rejects_removed_exchange_filter(
    app_client,
    user_factory,
    action_key: str,
) -> None:
    headers = _admin_headers(app_client, user_factory)
    filters = {"exchange": "SSE"}
    if action_key == "index_daily.maintain":
        filters["ts_code"] = "000300.SH"

    response = app_client.post(
        f"/api/v1/ops/manual-actions/{action_key}/task-runs",
        headers=headers,
        json={"time_input": {"mode": "point", "trade_date": "2026-04-24"}, "filters": filters},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "不支持的筛选项：exchange"


def test_ops_manual_action_task_run_uses_workflow_catalog_title(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/workflow:daily_market_close_maintenance/task-runs",
        headers=headers,
        json={"time_input": {"mode": "point", "trade_date": "2026-04-24"}, "filters": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["task_type"] == "workflow"
    assert payload["run"]["title"] == "每日收盘后维护"
    assert payload["run"]["time_input"] == {"mode": "point", "trade_date": "2026-04-24"}


def test_ops_manual_action_task_run_supports_natural_day_workflow(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/workflow:reference_data_natural_day_maintenance/task-runs",
        headers=headers,
        json={"time_input": {"mode": "point", "trade_date": "2026-04-24"}, "filters": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["task_type"] == "workflow"
    assert payload["run"]["title"] == "基础数据自然日维护"
    assert payload["run"]["time_input"] == {"mode": "point", "trade_date": "2026-04-24"}


def test_ops_manual_action_task_run_rejects_workflow_without_required_time_mode(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/workflow:daily_moneyflow_maintenance/task-runs",
        headers=headers,
        json={"time_input": {"mode": "none"}, "filters": {}},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "不支持的时间模式：none"


def test_ops_manual_action_task_run_applies_dc_hot_safe_defaults(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/dc_hot.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "point", "trade_date": "2026-04-24"},
            "filters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "dc_hot"
    assert payload["run"]["time_input"] == {"mode": "point", "trade_date": "2026-04-24"}
    assert payload["run"]["filters"] == {
        "market": ["A股市场", "ETF基金", "港股市场", "美股市场"],
        "hot_type": ["人气榜", "飙升榜"],
        "is_new": "Y",
    }


def test_ops_manual_action_task_run_routes_stk_mins_to_minute_history(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/stk_mins.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-04-23", "end_date": "2026-04-24"},
            "filters": {"freq": ["30min", "60min"]},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "stk_mins"
    assert payload["run"]["time_input"] == {"mode": "range", "start_date": "2026-04-23", "end_date": "2026-04-24"}
    assert payload["run"]["filters"] == {"freq": ["30min", "60min"]}


def test_ops_manual_action_task_run_routes_natural_day_range_to_dataset_action(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/dividend.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-04-01", "end_date": "2026-04-24"},
            "filters": {"ts_code": "000001.SZ"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "dividend"
    assert payload["run"]["time_input"] == {
        "mode": "range",
        "start_date": "2026-04-01",
        "end_date": "2026-04-24",
        "date_field": "ann_date",
    }
    assert payload["run"]["filters"] == {"ts_code": "000001.SZ"}


def test_ops_manual_action_task_run_supports_month_and_month_window(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    month_point = app_client.post(
        "/api/v1/ops/manual-actions/broker_recommend.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "point", "month": "2026-04"}, "filters": {}},
    )
    month_range = app_client.post(
        "/api/v1/ops/manual-actions/broker_recommend.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "range", "start_month": "2026-04", "end_month": "2026-06"}, "filters": {}},
    )
    month_window = app_client.post(
        "/api/v1/ops/manual-actions/index_weight.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_month": "2026-04", "end_month": "2026-06"},
            "filters": {"index_code": "000300.SH"},
        },
    )

    assert month_point.status_code == 200
    assert month_point.json()["run"]["resource_key"] == "broker_recommend"
    assert month_point.json()["run"]["time_input"] == {"mode": "point", "month": "202604"}
    assert month_point.json()["run"]["filters"] == {}

    assert month_range.status_code == 200
    assert month_range.json()["run"]["resource_key"] == "broker_recommend"
    assert month_range.json()["run"]["time_input"] == {"mode": "range", "start_month": "202604", "end_month": "202606"}
    assert month_range.json()["run"]["filters"] == {}

    assert month_window.status_code == 200
    assert month_window.json()["run"]["resource_key"] == "index_weight"
    assert month_window.json()["run"]["time_input"] == {"mode": "range", "start_month": "202604", "end_month": "202606"}
    assert month_window.json()["run"]["filters"] == {"index_code": "000300.SH"}


def test_ops_manual_action_task_run_rejects_unknown_filter(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/daily.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "point", "trade_date": "2026-04-24"},
            "filters": {"offset": 100},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
