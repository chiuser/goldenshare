from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.core_serving.security_serving import Security
from src.ops.action_catalog import END_DATE_PARAM, START_DATE_PARAM, TRADE_DATE_PARAM, WORKFLOW_DEFINITION_REGISTRY, WorkflowDefinition
from src.ops.models.ops.index_series_active import IndexSeriesActive
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
    assert "equity_financial" in group_keys
    assert "leader_board" in group_keys
    assert "workflow" in group_keys
    equity_group = next(group for group in payload["groups"] if group["group_key"] == "equity_market")
    assert equity_group["group_label"] == "A股行情"
    leader_board_group = next(group for group in payload["groups"] if group["group_key"] == "leader_board")
    assert leader_board_group["group_label"] == "榜单"
    etf_fund_group = next(group for group in payload["groups"] if group["group_key"] == "etf_fund")
    assert etf_fund_group["group_label"] == "ETF基金"
    public_fund_group = next(group for group in payload["groups"] if group["group_key"] == "public_fund")
    assert public_fund_group["group_label"] == "公募基金"
    equity_financial_group = next(group for group in payload["groups"] if group["group_key"] == "equity_financial")
    assert equity_financial_group["group_label"] == "A股财务数据"
    assert [action["action_key"] for action in equity_financial_group["actions"]] == [
        "express.maintain",
        "fina_indicator.maintain",
        "income.maintain",
        "balancesheet.maintain",
        "cashflow.maintain",
    ]
    workflow_group = next(group for group in payload["groups"] if group["group_key"] == "workflow")
    assert workflow_group["group_label"] == "工作流"

    actions = _actions_by_key(payload)
    assert any(action["action_key"] == "dc_hot.maintain" for action in leader_board_group["actions"])
    assert any(action["action_key"] == "etf_sh_cons.maintain" for action in etf_fund_group["actions"])
    assert any(action["action_key"] == "etf_share_size.maintain" for action in etf_fund_group["actions"])
    assert any(action["action_key"] == "etf_sz_cons.maintain" for action in etf_fund_group["actions"])
    assert any(action["action_key"] == "etf_mins.maintain" for action in etf_fund_group["actions"])
    assert actions["etf_basic.maintain"]["filters"] == []
    assert [action["action_key"] for action in public_fund_group["actions"]] == [
        "fund_company.maintain",
        "mkt_idx_bmk.maintain",
        "fund_basic.maintain",
        "fund_manager.maintain",
        "fund_share.maintain",
        "fund_div.maintain",
        "fund_portfolio.maintain",
    ]
    fund_portfolio = actions["fund_portfolio.maintain"]
    assert fund_portfolio["time_form"]["max_units_per_execution"] == 8
    assert [item["mode"] for item in fund_portfolio["time_form"]["modes"]] == ["point", "range"]
    assert all(item["selection_rule"] == "quarter_end" for item in fund_portfolio["time_form"]["modes"])
    express = actions["express.maintain"]
    assert express["time_form"]["max_units_per_execution"] == 366
    assert express["filters"] == []
    assert [item["mode"] for item in express["time_form"]["modes"]] == ["point", "range"]
    assert all(item["selection_rule"] == "calendar_day" for item in express["time_form"]["modes"])
    for action_key in ("income.maintain", "balancesheet.maintain", "cashflow.maintain"):
        statement = actions[action_key]
        assert [item["mode"] for item in statement["time_form"]["modes"]] == ["point", "range"]
        report_type = statement["filters"][0]
        assert report_type["key"] == "report_type"
        assert report_type["required"] is True
        assert report_type["multi_value"] is True
        assert report_type["options"] == [str(value) for value in range(1, 13)]
        assert report_type["option_labels"]["1"] == "合并报表"
        assert report_type["select_all_enabled"] is True
        assert report_type["default_value"] == [str(value) for value in range(1, 13)]
    assert actions["daily.maintain"]["display_name"] == "维护股票日线"
    assert actions["cyq_chips.maintain"]["display_name"] == "维护每日筹码分布"
    assert actions["cyq_chips.maintain"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert actions["cyq_chips.maintain"]["time_form"]["default_mode"] == "point"
    assert [item["mode"] for item in actions["cyq_chips.maintain"]["time_form"]["modes"]] == ["point", "range"]
    assert actions["etf_sh_cons.maintain"]["display_name"] == "维护ETF 申赎清单"
    assert actions["etf_sh_cons.maintain"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert actions["etf_sh_cons.maintain"]["time_form"]["default_mode"] == "point"
    assert [item["mode"] for item in actions["etf_sh_cons.maintain"]["time_form"]["modes"]] == ["point", "range"]
    assert actions["etf_share_size.maintain"]["display_name"] == "维护ETF 份额规模"
    assert actions["etf_share_size.maintain"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert actions["etf_share_size.maintain"]["time_form"]["default_mode"] == "point"
    assert [item["mode"] for item in actions["etf_share_size.maintain"]["time_form"]["modes"]] == ["point", "range"]
    assert actions["etf_sz_cons.maintain"]["display_name"] == "维护ETF 每日持仓组合（深市）"
    assert actions["etf_sz_cons.maintain"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert actions["etf_sz_cons.maintain"]["time_form"]["default_mode"] == "point"
    assert [item["mode"] for item in actions["etf_sz_cons.maintain"]["time_form"]["modes"]] == ["point", "range"]
    assert actions["etf_mins.maintain"]["display_name"] == "维护ETF 历史分钟行情"
    assert actions["etf_mins.maintain"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert [item["mode"] for item in actions["etf_mins.maintain"]["time_form"]["modes"]] == ["point", "range"]
    etf_mins_filters = {
        item["key"]: item for item in actions["etf_mins.maintain"]["filters"]
    }
    assert etf_mins_filters["ts_code"]["multi_value"] is True
    assert "逗号分隔" in etf_mins_filters["ts_code"]["description"]
    assert etf_mins_filters["freq"]["required"] is True
    assert etf_mins_filters["freq"]["multi_value"] is True
    assert etf_mins_filters["freq"]["options"] == [
        "1min",
        "5min",
        "15min",
        "30min",
        "60min",
    ]
    assert actions["idx_factor_pro.maintain"]["display_name"] == "维护指数技术因子(专业版)"
    assert actions["idx_factor_pro.maintain"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert actions["idx_factor_pro.maintain"]["time_form"]["default_mode"] == "point"
    assert [item["mode"] for item in actions["idx_factor_pro.maintain"]["time_form"]["modes"]] == ["point", "range"]
    idx_factor_pro_modes = _time_modes(actions["idx_factor_pro.maintain"])
    assert idx_factor_pro_modes["point"]["control"] == "trade_date"
    assert idx_factor_pro_modes["point"]["selection_rule"] == "trading_day_only"
    assert idx_factor_pro_modes["range"]["control"] == "trade_date_range"
    assert idx_factor_pro_modes["range"]["selection_rule"] == "trading_day_only"
    assert actions["daily.maintain"]["date_model"]["input_shape"] == "trade_date_or_start_end"
    assert actions["daily.maintain"]["time_form"]["default_mode"] == "point"
    assert [item["mode"] for item in actions["daily.maintain"]["time_form"]["modes"]] == ["point", "range"]
    daily_modes = _time_modes(actions["daily.maintain"])
    assert daily_modes["point"]["control"] == "trade_date"
    assert daily_modes["point"]["selection_rule"] == "trading_day_only"
    assert daily_modes["range"]["control"] == "trade_date_range"
    assert daily_modes["range"]["selection_rule"] == "trading_day_only"
    assert actions["daily.maintain"]["action_type"] == "dataset_action"

    news_linking = actions["maintenance.materialize_news_stock_links"]
    assert news_linking["action_type"] == "maintenance_action"
    assert news_linking["time_form"]["default_mode"] == "range"
    assert [item["mode"] for item in news_linking["time_form"]["modes"]] == ["range"]
    news_range = _time_modes(news_linking)["range"]
    assert news_range["control"] == "calendar_date_range"
    assert news_range["selection_rule"] == "calendar_day"
    assert news_range["date_field"] == "news_time"
    assert "截止日期包含整天" in news_range["description"]
    assert news_linking["filters"] == []

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
    assert actions["st.maintain"]["date_model"]["input_shape"] == "none"
    assert [item["mode"] for item in actions["st.maintain"]["time_form"]["modes"]] == ["none"]
    st_modes = _time_modes(actions["st.maintain"])
    assert st_modes["none"]["control"] == "none"
    assert st_modes["none"]["selection_rule"] == "none"
    for action_key in (
        "fund_company.maintain",
        "mkt_idx_bmk.maintain",
        "fund_basic.maintain",
        "fund_manager.maintain",
    ):
        assert actions[action_key]["date_model"]["input_shape"] == "none"
        assert [item["mode"] for item in actions[action_key]["time_form"]["modes"]] == ["none"]
        assert actions[action_key]["filters"] == []

    single_code_actions = (
        "daily.maintain",
        "adj_factor.maintain",
        "cyq_perf.maintain",
        "cyq_chips.maintain",
        "etf_sh_cons.maintain",
        "etf_share_size.maintain",
        "etf_sz_cons.maintain",
        "fund_daily.maintain",
        "index_daily.maintain",
        "index_daily_basic.maintain",
    )
    for action_key in single_code_actions:
        filter_keys = [item["key"] for item in actions[action_key]["filters"]]
        assert filter_keys == ["ts_code"]

    assert [item["key"] for item in actions["bse_mapping.maintain"]["filters"]] == ["o_code", "n_code"]
    assert [item["key"] for item in actions["bak_basic.maintain"]["filters"]] == ["ts_code"]
    assert actions["idx_factor_pro.maintain"]["filters"] == []
    assert [item["key"] for item in actions["namechange.maintain"]["filters"]] == ["ts_code"]
    st_filters = {item["key"]: item for item in actions["st.maintain"]["filters"]}
    assert list(st_filters) == ["ts_code"]
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
    assert dc_hot_filters["market"]["default_value"] == ["A股市场", "ETF基金", "港股市场"]
    assert dc_hot_filters["hot_type"]["default_value"] == ["人气榜", "飙升榜"]
    assert dc_hot_filters["is_new"]["default_value"] == "Y"

    assert [item["mode"] for item in actions["stk_mins.maintain"]["time_form"]["modes"]] == ["point", "range"]
    assert _time_modes(actions["stk_mins.maintain"])["point"]["control"] == "trade_date"
    stk_mins_filter_keys = [item["key"] for item in actions["stk_mins.maintain"]["filters"]]
    assert stk_mins_filter_keys == ["ts_code", "freq"]
    assert [item["mode"] for item in actions["index_mins.maintain"]["time_form"]["modes"]] == ["point", "range"]
    assert _time_modes(actions["index_mins.maintain"])["point"]["control"] == "trade_date"
    index_mins_filters = {item["key"]: item for item in actions["index_mins.maintain"]["filters"]}
    assert list(index_mins_filters) == ["ts_code", "freq"]
    assert index_mins_filters["freq"]["multi_value"] is True
    assert index_mins_filters["freq"]["required"] is False
    assert index_mins_filters["freq"]["options"] == ["1min", "5min", "15min", "30min", "60min"]
    assert index_mins_filters["freq"]["default_value"] == ["1min", "5min", "15min", "30min", "60min"]

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
    assert [item["mode"] for item in actions["workflow:reference_data_refresh"]["time_form"]["modes"]] == ["none"]
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


def test_ops_manual_action_creates_one_etf_mins_task_with_multi_code_filters(
    app_client,
    user_factory,
    db_session,
) -> None:
    headers = _admin_headers(app_client, user_factory)
    db_session.add_all(
        [
            EtfBasic(
                ts_code="510300.SH",
                list_date=date(2012, 5, 28),
                list_status="L",
                exchange="SH",
            ),
            EtfBasic(
                ts_code="159915.SZ",
                list_date=date(2011, 12, 5),
                list_status="L",
                exchange="SZ",
            ),
        ]
    )
    db_session.flush()

    response = app_client.post(
        "/api/v1/ops/manual-actions/etf_mins.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {
                "mode": "range",
                "start_date": "2026-01-01",
                "end_date": "2026-08-28",
            },
            "filters": {
                "ts_code": ["510300.SH", "159915.SZ"],
                "freq": ["1min", "5min"],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "etf_mins"
    assert payload["run"]["filters"] == {
        "ts_code": ["510300.SH", "159915.SZ"],
        "freq": ["1min", "5min"],
    }
    task_run = db_session.scalar(
        select(TaskRun).where(TaskRun.id == payload["run"]["id"])
    )
    assert task_run is not None
    assert task_run.filters_json == {
        "ts_code": ["510300.SH", "159915.SZ"],
        "freq": ["1min", "5min"],
    }


def test_ops_manual_action_creates_news_time_natural_day_range(app_client, user_factory, db_session) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/maintenance.materialize_news_stock_links/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-08-21", "end_date": "2026-08-22"},
            "filters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()["run"]
    assert payload["time_input"] == {
        "mode": "range",
        "start_date": "2026-08-21",
        "end_date": "2026-08-22",
    }
    task_run = db_session.get(TaskRun, payload["id"])
    assert task_run is not None
    frozen = task_run.request_payload_json
    assert frozen["run_mode"] == "manual_range"
    assert frozen["window_field"] == "news_time"
    assert frozen["window_start"] == "2026-08-20T16:00:00+00:00"
    assert frozen["window_end"] == "2026-08-22T16:00:00+00:00"
    assert frozen["cursor_end"] == frozen["window_end"]
    assert frozen["news_scope"] == "all"
    assert "mode" not in frozen
    assert "overlap_seconds" not in frozen


@pytest.mark.parametrize(
    "time_input",
    (
        {"mode": "range", "end_date": "2026-08-22"},
        {"mode": "range", "start_date": "2026-08-21"},
        {"mode": "range", "start_date": "2026/08/21", "end_date": "2026-08-22"},
        {"mode": "range", "start_date": "2026-08-23", "end_date": "2026-08-22"},
    ),
)
def test_ops_manual_action_rejects_invalid_news_time_range(app_client, user_factory, time_input: dict) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/maintenance.materialize_news_stock_links/task-runs",
        headers=headers,
        json={"time_input": time_input, "filters": {}},
    )

    assert response.status_code == 422


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


def test_ops_manual_action_financial_statement_defaults_to_real_report_types_and_rejects_empty(
    app_client,
    user_factory,
) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/income.maintain/task-runs",
        headers=headers,
        json={"time_input": {"mode": "point", "ann_date": "2026-08-29"}, "filters": {}},
    )
    assert response.status_code == 200
    assert response.json()["run"]["filters"] == {
        "report_type": [str(value) for value in range(1, 13)]
    }

    empty = app_client.post(
        "/api/v1/ops/manual-actions/income.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "point", "ann_date": "2026-08-29"},
            "filters": {"report_type": []},
        },
    )
    assert empty.status_code == 422


def test_ops_manual_action_task_run_supports_public_fund_full_snapshots(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    for action_key, dataset_key in (
        ("fund_company.maintain", "fund_company"),
        ("mkt_idx_bmk.maintain", "mkt_idx_bmk"),
        ("fund_basic.maintain", "fund_basic"),
        ("fund_manager.maintain", "fund_manager"),
    ):
        response = app_client.post(
            f"/api/v1/ops/manual-actions/{action_key}/task-runs",
            headers=headers,
            json={"time_input": {"mode": "none"}, "filters": {}},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["run"]["resource_key"] == dataset_key
        assert payload["run"]["time_input"] == {"mode": "none"}
        assert payload["run"]["filters"] == {}


@pytest.mark.parametrize(
    "payload",
    (
        {"time_input": {"mode": "none"}, "filters": {"ts_code": "000001.OF"}},
        {"time_input": {"mode": "point", "trade_date": "2026-08-06"}, "filters": {}},
    ),
)
def test_ops_manual_action_task_run_rejects_scoped_fund_manager_snapshots(
    app_client,
    user_factory,
    payload: dict,
) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/fund_manager.maintain/task-runs",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422


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


def test_ops_manual_action_task_run_routes_st_snapshot_mode(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/st.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "none"},
            "filters": {"ts_code": "000001.SZ"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "st"
    assert payload["run"]["time_input"] == {"mode": "none"}
    assert payload["run"]["filters"] == {"ts_code": "000001.SZ"}


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


def test_ops_manual_action_fund_portfolio_preflights_eight_and_rejects_nine_units(
    app_client,
    user_factory,
    db_session,
) -> None:
    headers = _admin_headers(app_client, user_factory)

    accepted = app_client.post(
        "/api/v1/ops/manual-actions/fund_portfolio.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2014-01-01", "end_date": "2015-12-31"},
            "filters": {},
        },
    )

    assert accepted.status_code == 200
    accepted_id = accepted.json()["run"]["id"]
    assert db_session.get(TaskRun, accepted_id) is not None

    before_ids = set(db_session.scalars(select(TaskRun.id)).all())
    rejected = app_client.post(
        "/api/v1/ops/manual-actions/fund_portfolio.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2014-01-01", "end_date": "2016-03-31"},
            "filters": {},
        },
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "units_exceeded"
    assert rejected.json()["message"] == "本次范围会生成 9 个处理单元，超过单次上限 8 个。请缩小时间范围后重试。"
    assert set(db_session.scalars(select(TaskRun.id)).all()) == before_ids


def test_ops_manual_action_express_preflights_day_range_and_rejects_filters(
    app_client,
    user_factory,
    db_session,
) -> None:
    headers = _admin_headers(app_client, user_factory)

    accepted = app_client.post(
        "/api/v1/ops/manual-actions/express.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2025-01-01", "end_date": "2026-01-01"},
            "filters": {},
        },
    )

    assert accepted.status_code == 200
    accepted_run = db_session.get(TaskRun, accepted.json()["run"]["id"])
    assert accepted_run is not None
    assert accepted_run.time_input_json == {
        "mode": "range",
        "start_date": "2025-01-01",
        "end_date": "2026-01-01",
        "date_field": "ann_date",
    }

    before_ids = set(db_session.scalars(select(TaskRun.id)).all())
    too_wide = app_client.post(
        "/api/v1/ops/manual-actions/express.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2025-01-01", "end_date": "2026-01-02"},
            "filters": {},
        },
    )
    assert too_wide.status_code == 422
    assert too_wide.json()["code"] == "units_exceeded"
    assert set(db_session.scalars(select(TaskRun.id)).all()) == before_ids

    filtered = app_client.post(
        "/api/v1/ops/manual-actions/express.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "point", "ann_date": "2025-04-08", "date_field": "ann_date"},
            "filters": {"ts_code": "000001.SZ"},
        },
    )
    assert filtered.status_code == 422
    assert filtered.json()["code"] == "validation_error"
    assert set(db_session.scalars(select(TaskRun.id)).all()) == before_ids


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
        "cyq_chips.maintain",
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


def test_ops_manual_action_task_run_supports_reference_data_refresh_workflow(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/workflow:reference_data_refresh/task-runs",
        headers=headers,
        json={"time_input": {"mode": "none"}, "filters": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["task_type"] == "workflow"
    assert payload["run"]["title"] == "基础主数据刷新"
    assert payload["run"]["time_input"] == {"mode": "none"}


def test_ops_manual_actions_exposes_heat_single_day_and_plan_apply_contract(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.get("/api/v1/ops/manual-actions", headers=headers)

    assert response.status_code == 200
    actions = _actions_by_key(response.json())
    single = actions["maintenance.materialize_wealth_sector_heat_daily"]
    replay = actions["maintenance.replay_wealth_sector_heat_history"]
    assert single["action_type"] == "maintenance_action"
    assert [item["mode"] for item in single["time_form"]["modes"]] == ["point"]
    assert single["filters"] == []
    assert [item["mode"] for item in replay["time_form"]["modes"]] == ["range", "none"]
    assert [item["key"] for item in replay["filters"]] == [
        "execution_mode",
        "plan_task_run_id",
        "plan_hash",
    ]
    assert replay["filters"][0]["required"] is True
    assert replay["filters"][0]["options"] == ["PLAN", "APPLY"]


def test_ops_manual_action_creates_heat_single_plan_and_apply_task_runs(
    app_client,
    user_factory,
) -> None:
    headers = _admin_headers(app_client, user_factory)

    single = app_client.post(
        "/api/v1/ops/manual-actions/maintenance.materialize_wealth_sector_heat_daily/task-runs",
        headers=headers,
        json={"time_input": {"mode": "point", "trade_date": "2026-08-12"}, "filters": {}},
    )
    replay_plan = app_client.post(
        "/api/v1/ops/manual-actions/maintenance.replay_wealth_sector_heat_history/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
            "filters": {"execution_mode": "PLAN"},
        },
    )
    replay_apply = app_client.post(
        "/api/v1/ops/manual-actions/maintenance.replay_wealth_sector_heat_history/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "none"},
            "filters": {
                "execution_mode": "APPLY",
                "plan_task_run_id": replay_plan.json()["run"]["id"],
                "plan_hash": "frozen-plan-hash",
            },
        },
    )

    assert single.status_code == 200
    assert single.json()["run"]["task_type"] == "maintenance_action"
    assert single.json()["run"]["time_input"] == {"mode": "point", "trade_date": "2026-08-12"}
    assert replay_plan.status_code == 200
    assert replay_plan.json()["run"]["time_input"] == {
        "mode": "range",
        "start_date": "2026-05-20",
        "end_date": "2026-08-12",
    }
    assert replay_plan.json()["run"]["filters"] == {"execution_mode": "PLAN"}
    assert replay_apply.status_code == 200
    assert replay_apply.json()["run"]["time_input"] == {"mode": "none"}
    assert replay_apply.json()["run"]["filters"] == {
        "execution_mode": "APPLY",
        "plan_task_run_id": replay_plan.json()["run"]["id"],
        "plan_hash": "frozen-plan-hash",
    }


def test_ops_manual_action_rejects_heat_replay_without_execution_mode(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/manual-actions/maintenance.replay_wealth_sector_heat_history/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
            "filters": {},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "执行模式不能为空"


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
        "market": ["A股市场", "ETF基金", "港股市场"],
        "hot_type": ["人气榜", "飙升榜"],
        "is_new": "Y",
    }


def test_ops_manual_action_task_run_routes_stk_mins_to_minute_history(app_client, user_factory, db_session) -> None:
    headers = _admin_headers(app_client, user_factory)
    db_session.add(Security(ts_code="000001.SZ", name="平安银行", list_status="L", security_type="EQUITY", source="tushare"))
    db_session.commit()

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


def test_ops_manual_action_task_run_routes_index_mins_to_minute_history(app_client, user_factory, db_session) -> None:
    headers = _admin_headers(app_client, user_factory)
    db_session.add(
        IndexSeriesActive(
            resource="index_mins",
            ts_code="000001.SH",
            first_seen_date=date(2026, 4, 30),
            last_seen_date=date(2026, 4, 30),
            last_checked_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    response = app_client.post(
        "/api/v1/ops/manual-actions/index_mins.maintain/task-runs",
        headers=headers,
        json={
            "time_input": {"mode": "point", "trade_date": "2026-04-30"},
            "filters": {"freq": ["30min"], "ts_code": "000001.SH"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["resource_key"] == "index_mins"
    assert payload["run"]["time_input"] == {"mode": "point", "trade_date": "2026-04-30"}
    assert payload["run"]["filters"] == {"freq": ["30min"], "ts_code": "000001.SH"}


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
