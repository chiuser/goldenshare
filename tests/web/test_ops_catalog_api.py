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
    workflows = {item["key"]: item for item in payload["workflows"]}

    assert "daily.maintain" in actions
    assert "dc_hot.maintain" in actions
    assert "cyq_chips.maintain" in actions
    assert "etf_sh_cons.maintain" in actions
    assert "index_weight.maintain" in actions
    assert "index_mins.maintain" in actions
    assert "idx_factor_pro.maintain" in actions
    assert "fund_company.maintain" in actions
    assert "mkt_idx_bmk.maintain" in actions
    assert "fund_basic.maintain" in actions
    assert "fund_manager.maintain" in actions
    assert "fund_share.maintain" in actions
    assert "fund_div.maintain" in actions
    assert "fund_portfolio.maintain" in actions
    assert "express.maintain" in actions
    assert "maintenance.rebuild_dm" in actions
    legacy_keys = [
        "sync" + "_daily.daily",
        "sync" + "_history.stock_basic",
        "back" + "fill" + "_index_series.index_weight",
    ]
    assert all(key not in actions for key in legacy_keys)
    assert "daily_market_close_maintenance" in workflow_keys
    assert "reference_data_refresh" in workflow_keys
    assert "reference_data_natural_day_maintenance" not in workflow_keys
    assert "index_extension_maintenance" in workflow_keys
    assert "index_extension_" + "back" + "fill" not in workflow_keys
    assert {item["domain_display_name"] for item in payload["workflows"]} == {"工作流"}
    assert {item["group_label"] for item in payload["workflows"]} == {"工作流"}
    assert [param["key"] for param in workflows["daily_market_close_maintenance"]["parameters"]] == [
        "trade_date",
        "start_date",
        "end_date",
    ]
    assert [param["key"] for param in workflows["daily_moneyflow_maintenance"]["parameters"]] == [
        "trade_date",
        "start_date",
        "end_date",
    ]
    assert workflows["reference_data_refresh"]["parameters"] == []
    assert [param["key"] for param in workflows["index_extension_maintenance"]["parameters"]] == [
        "start_date",
        "end_date",
    ]
    assert "sources" not in payload

    daily = actions["daily.maintain"]
    assert daily["action_type"] == "dataset_action"
    assert daily["target_key"] == "daily"
    assert daily["target_display_name"] == "股票日线"
    assert daily["group_key"] == "equity_market"
    assert daily["group_label"] == "A股行情"
    assert daily["domain_key"] == "equity_market"
    assert daily["domain_display_name"] == "股票行情"
    assert daily["freshness_policy"] == "continuous_open_day"
    assert daily["schedule_enabled"] is True
    assert [param["key"] for param in daily["parameters"]][:3] == ["trade_date", "start_date", "end_date"]

    stk_auction_o = actions["stk_auction_o.maintain"]
    assert stk_auction_o["target_display_name"] == "股票开盘集合竞价"
    assert stk_auction_o["group_key"] == "equity_market"
    assert stk_auction_o["group_label"] == "A股行情"
    assert stk_auction_o["freshness_policy"] == "continuous_open_day"

    stk_auction_c = actions["stk_auction_c.maintain"]
    assert stk_auction_c["target_display_name"] == "股票收盘集合竞价"
    assert stk_auction_c["group_key"] == "equity_market"
    assert stk_auction_c["group_label"] == "A股行情"
    assert stk_auction_c["freshness_policy"] == "continuous_open_day"
    assert [param["key"] for param in daily["parameters"]] == ["trade_date", "start_date", "end_date", "ts_code"]

    cyq_chips = actions["cyq_chips.maintain"]
    assert cyq_chips["target_display_name"] == "每日筹码分布"
    assert cyq_chips["group_key"] == "technical_indicators"
    assert cyq_chips["group_label"] == "技术指标"
    assert cyq_chips["freshness_policy"] == "continuous_open_day"
    assert [param["key"] for param in cyq_chips["parameters"]] == ["trade_date", "start_date", "end_date", "ts_code"]

    etf_sh_cons = actions["etf_sh_cons.maintain"]
    assert etf_sh_cons["target_display_name"] == "ETF 申赎清单"
    assert etf_sh_cons["group_key"] == "etf_fund"
    assert etf_sh_cons["group_label"] == "ETF基金"
    assert etf_sh_cons["freshness_policy"] == "continuous_open_day"
    assert [param["key"] for param in etf_sh_cons["parameters"]] == ["trade_date", "start_date", "end_date", "ts_code"]

    bse_mapping = actions["bse_mapping.maintain"]
    assert bse_mapping["group_key"] == "reference_data"
    assert bse_mapping["group_label"] == "A股基础数据"
    assert [param["key"] for param in bse_mapping["parameters"]] == ["o_code", "n_code"]

    bak_basic = actions["bak_basic.maintain"]
    assert bak_basic["group_key"] == "reference_data"
    assert bak_basic["group_label"] == "A股基础数据"
    assert [param["key"] for param in bak_basic["parameters"]] == ["trade_date", "start_date", "end_date", "ts_code"]

    namechange = actions["namechange.maintain"]
    assert namechange["group_key"] == "reference_data"
    assert namechange["group_label"] == "A股基础数据"
    assert namechange["freshness_policy"] == "snapshot_run_trace"
    assert namechange["date_selection_rule"] == "none"
    assert [param["key"] for param in namechange["parameters"]] == ["ts_code"]

    st = actions["st.maintain"]
    assert st["group_key"] == "reference_data"
    assert st["group_label"] == "A股基础数据"
    assert st["date_selection_rule"] == "none"
    assert [param["key"] for param in st["parameters"]] == ["ts_code"]

    stock_company = actions["stock_company.maintain"]
    assert stock_company["group_key"] == "reference_data"
    assert stock_company["group_label"] == "A股基础数据"
    stock_company_params = {param["key"]: param for param in stock_company["parameters"]}
    assert list(stock_company_params) == ["ts_code", "exchange"]
    assert stock_company_params["exchange"]["options"] == ["SSE", "SZSE", "BSE"]
    assert stock_company_params["exchange"]["default_value"] == ["SSE", "SZSE", "BSE"]
    assert stock_company_params["exchange"]["multi_value"] is True

    for action_key in (
        "adj_factor.maintain",
        "cyq_perf.maintain",
        "cyq_chips.maintain",
        "etf_sh_cons.maintain",
        "fund_daily.maintain",
        "index_daily.maintain",
        "index_daily_basic.maintain",
    ):
        assert [param["key"] for param in actions[action_key]["parameters"]] == [
            "trade_date",
            "start_date",
            "end_date",
            "ts_code",
        ]

    dc_hot = actions["dc_hot.maintain"]
    assert dc_hot["group_key"] == "leader_board"
    assert dc_hot["group_label"] == "榜单"
    dc_hot_params = {param["key"]: param for param in dc_hot["parameters"]}
    assert dc_hot_params["market"]["options"] == ["A股市场", "ETF基金", "港股市场"]
    assert dc_hot_params["market"]["default_value"] == ["A股市场", "ETF基金", "港股市场"]
    assert dc_hot_params["hot_type"]["options"] == ["人气榜", "飙升榜"]
    assert dc_hot_params["hot_type"]["default_value"] == ["人气榜", "飙升榜"]
    assert dc_hot_params["is_new"]["options"] == ["Y"]
    assert dc_hot_params["is_new"]["multi_value"] is False
    assert dc_hot_params["is_new"]["default_value"] == "Y"

    index_mins = actions["index_mins.maintain"]
    assert index_mins["group_key"] == "index_market_data"
    assert index_mins["group_label"] == "A股指数行情"
    assert index_mins["schedule_enabled"] is True
    index_mins_params = {param["key"]: param for param in index_mins["parameters"]}
    assert list(index_mins_params) == ["trade_date", "start_date", "end_date", "ts_code", "freq"]
    assert index_mins_params["freq"]["multi_value"] is True
    assert index_mins_params["freq"]["default_value"] == ["1min", "5min", "15min", "30min", "60min"]

    idx_factor_pro = actions["idx_factor_pro.maintain"]
    assert idx_factor_pro["target_display_name"] == "指数技术因子(专业版)"
    assert idx_factor_pro["group_key"] == "index_market_data"
    assert idx_factor_pro["group_label"] == "A股指数行情"
    assert idx_factor_pro["freshness_policy"] == "continuous_open_day"
    assert idx_factor_pro["schedule_enabled"] is True
    assert [param["key"] for param in idx_factor_pro["parameters"]] == [
        "trade_date",
        "start_date",
        "end_date",
    ]

    assert actions["maintenance.rebuild_dm"]["action_type"] == "maintenance_action"
    assert actions["maintenance.rebuild_dm"]["display_name"] == "刷新数据集市快照"

    catalog_items = [*actions.values(), *workflows.values()]
    assert sum(item["schedule_enabled"] for item in catalog_items) == 89
    assert all(
        (item["automation_capability"] is not None) is item["schedule_enabled"]
        for item in catalog_items
    )

    daily_capability = actions["daily.maintain"]["automation_capability"]
    assert daily_capability == {
        "version": 1,
        "default_trigger_mode": "schedule",
        "trigger_options": [
            {"mode": "schedule", "allowed_schedule_types": ["cron", "once"]},
            {"mode": "probe", "allowed_schedule_types": ["cron", "once"]},
            {"mode": "schedule_probe_fallback", "allowed_schedule_types": ["cron", "once"]},
        ],
        "probe_conditions": [
            {
                "kind": "freshness_latest_open",
                "label": "最新业务日命中最新交易日",
                "description": "最新业务日达到最新开市交易日后创建维护任务。",
                "allowed_trigger_modes": ["probe", "schedule_probe_fallback"],
                "calendar_policy": "dataset_default",
                "time_input": "dataset_default",
                "filters": {
                    "mode": "dataset_default",
                    "required_fields": [],
                    "allowed_values": {},
                    "require_complete_allowed_values": False,
                },
                "probe": {
                    "source": "system_default",
                    "source_label": "系统默认来源",
                    "window": {"mode": "operator_default", "start": None, "end": None},
                    "probe_interval_seconds": {"mode": "operator_default", "value": None},
                    "max_triggers_per_day": {"mode": "operator_default", "value": None},
                },
            }
        ],
        "calendar_policy_rules": [],
        "time_input_contract": {
            "supported_modes": ["point", "range"],
            "point_field": "trade_date",
            "range_start_field": "start_date",
            "range_end_field": "end_date",
            "granularity": "day",
        },
    }

    margin_detail_capability = actions["margin_detail.maintain"]["automation_capability"]
    assert margin_detail_capability == {
        "version": 1,
        "default_trigger_mode": "probe",
        "trigger_options": [{"mode": "probe", "allowed_schedule_types": ["cron", "once"]}],
        "probe_conditions": [
            {
                "kind": "remote_margin_detail_ready",
                "label": "源站已完整发布融资融券交易明细",
                "description": "确认三个市场代表证券均已返回上一开市日数据后，创建全市场单日维护任务。",
                "allowed_trigger_modes": ["probe"],
                "calendar_policy": "forbidden",
                "time_input": "forbidden",
                "filters": {
                    "mode": "forbidden",
                    "required_fields": [],
                    "allowed_values": {},
                    "require_complete_allowed_values": False,
                },
                "probe": {
                    "source": "system_default",
                    "source_label": "系统默认来源",
                    "window": {"mode": "fixed", "start": "09:00", "end": "09:30"},
                    "probe_interval_seconds": {"mode": "fixed", "value": 300},
                    "max_triggers_per_day": {"mode": "fixed", "value": 1},
                },
            }
        ],
        "calendar_policy_rules": [],
        "time_input_contract": {
            "supported_modes": ["point", "range"],
            "point_field": "trade_date",
            "range_start_field": "start_date",
            "range_end_field": "end_date",
            "granularity": "day",
        },
    }
    for workflow in workflows.values():
        if workflow["schedule_enabled"]:
            assert workflow["automation_capability"] == {
                "version": 1,
                "default_trigger_mode": "schedule",
                "trigger_options": [{"mode": "schedule", "allowed_schedule_types": ["cron", "once"]}],
                "probe_conditions": [],
                "calendar_policy_rules": [],
                "time_input_contract": None,
            }
        else:
            assert workflow["automation_capability"] is None

    fund_share = actions["fund_share.maintain"]
    assert fund_share["group_key"] == "public_fund"
    assert fund_share["group_label"] == "公募基金"
    assert fund_share["freshness_policy"] == "event_run_trace"
    assert [param["key"] for param in fund_share["parameters"]] == ["trade_date", "start_date", "end_date"]
    assert fund_share["automation_capability"]["default_trigger_mode"] == "schedule"
    assert fund_share["automation_capability"]["trigger_options"] == [
        {"mode": "schedule", "allowed_schedule_types": ["cron"]}
    ]
    assert fund_share["automation_capability"]["probe_conditions"] == []
    assert fund_share["automation_capability"]["calendar_policy_rules"] == [
        {
            "policy": "trigger_day_point",
            "schedule_types": ["cron"],
            "cron_repeat_modes": ["daily", "weekly", "monthly", "intraday_interval"],
            "explicit_time_input": "forbidden",
            "generated_time_mode": "point",
            "generated_time_field": "trade_date",
            "policy_parameters": [],
        }
    ]

    fund_div = actions["fund_div.maintain"]
    assert fund_div["group_key"] == "public_fund"
    assert fund_div["group_label"] == "公募基金"
    assert fund_div["freshness_policy"] == "event_run_trace"
    assert [param["key"] for param in fund_div["parameters"]] == ["ann_date", "start_date", "end_date"]
    assert fund_div["automation_capability"]["probe_conditions"] == []
    assert fund_div["automation_capability"]["calendar_policy_rules"] == [
        {
            "policy": "trigger_day_point",
            "schedule_types": ["cron"],
            "cron_repeat_modes": ["daily", "weekly", "monthly"],
            "explicit_time_input": "forbidden",
            "generated_time_mode": "point",
            "generated_time_field": "ann_date",
            "policy_parameters": [],
        }
    ]

    fund_portfolio = actions["fund_portfolio.maintain"]
    assert fund_portfolio["group_key"] == "public_fund"
    assert fund_portfolio["group_label"] == "公募基金"
    assert fund_portfolio["freshness_policy"] == "event_run_trace"
    assert [param["key"] for param in fund_portfolio["parameters"]] == [
        "trade_date",
        "start_date",
        "end_date",
        "ts_code",
    ]
    assert fund_portfolio["automation_capability"]["probe_conditions"] == []
    assert fund_portfolio["automation_capability"]["calendar_policy_rules"] == [
        {
            "policy": "latest_completed_calendar_quarter",
            "schedule_types": ["cron", "once"],
            "cron_repeat_modes": ["weekly", "monthly"],
            "explicit_time_input": "forbidden",
            "generated_time_mode": "point",
            "generated_time_field": "trade_date",
            "policy_parameters": [],
        }
    ]

    express = actions["express.maintain"]
    assert express["target_display_name"] == "业绩快报"
    assert express["group_key"] == "equity_financial"
    assert express["group_label"] == "A股财务数据"
    assert express["group_order"] == 3
    assert express["freshness_policy"] == "event_run_trace"
    assert [param["key"] for param in express["parameters"]] == ["ann_date", "start_date", "end_date"]
    assert express["automation_capability"]["default_trigger_mode"] == "schedule"
    assert express["automation_capability"]["trigger_options"] == [
        {"mode": "schedule", "allowed_schedule_types": ["cron"]}
    ]
    assert express["automation_capability"]["probe_conditions"] == []
    assert express["automation_capability"]["calendar_policy_rules"] == [
        {
            "policy": "since_last_success_day_range",
            "schedule_types": ["cron"],
            "cron_repeat_modes": ["daily", "weekly", "monthly"],
            "explicit_time_input": "forbidden",
            "generated_time_mode": "range",
            "generated_time_field": "start_date_end_date",
            "policy_parameters": [
                {
                    "key": "initial_start_date",
                    "display_name": "首次覆盖开始日期",
                    "param_type": "date",
                    "description": "首次自动同步从该自然日开始；后续从最后成功窗口的下一日续跑。",
                    "required": True,
                    "options": [],
                    "multi_value": False,
                    "default_value": None,
                }
            ],
        }
    ]


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
