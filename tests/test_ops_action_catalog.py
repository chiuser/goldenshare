from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition, get_dataset_definition_by_action_key, list_dataset_definitions
from src.ops.action_catalog import (
    MAINTENANCE_ACTION_REGISTRY,
    WORKFLOW_DEFINITION_REGISTRY,
    WORKFLOW_DOMAIN_DISPLAY_NAME,
    WORKFLOW_DOMAIN_KEY,
    WORKFLOW_GROUP_ORDER,
    get_action_display_name,
    get_catalog_target,
)
from src.ops.catalog.dataset_catalog_view_resolver import resolve_default_dataset_catalog_item


def test_maintenance_action_registry_keeps_only_explicit_actions() -> None:
    assert set(MAINTENANCE_ACTION_REGISTRY) == {
        "maintenance.rebuild_dm",
        "maintenance.rebuild_index_kline_serving",
        "maintenance.materialize_wealth_sector_heat_daily",
        "maintenance.replay_wealth_sector_heat_history",
        "maintenance.materialize_news_stock_links",
    }
    assert {action.domain_key for action in MAINTENANCE_ACTION_REGISTRY.values()} == {"maintenance"}
    assert MAINTENANCE_ACTION_REGISTRY["maintenance.rebuild_dm"].executor_key == "refresh_materialized_view"
    assert MAINTENANCE_ACTION_REGISTRY["maintenance.rebuild_dm"].target_tables == ("dm.equity_daily_snapshot",)
    assert (
        MAINTENANCE_ACTION_REGISTRY["maintenance.rebuild_index_kline_serving"].executor_key
        == "rebuild_index_period_serving"
    )
    assert MAINTENANCE_ACTION_REGISTRY["maintenance.rebuild_index_kline_serving"].target_tables == (
        "core_serving.index_weekly_serving",
        "core_serving.index_monthly_serving",
    )
    assert MAINTENANCE_ACTION_REGISTRY["maintenance.materialize_wealth_sector_heat_daily"].executor_key == (
        "wealth_sector_heat"
    )
    heat_action = MAINTENANCE_ACTION_REGISTRY["maintenance.materialize_wealth_sector_heat_daily"]
    assert heat_action.schedule_enabled is True
    assert heat_action.readiness_condition == "wealth_sector_heat_sources_ready"
    assert dict(heat_action.readiness_policy) == {
        "timezone": "Asia/Shanghai",
        "initial_check_local_time": "21:15",
        "upstream_workflow_not_before_local_times": {
            "daily_market_close_maintenance": "21:00",
            "daily_moneyflow_maintenance": "20:00",
        },
        "retry_interval_seconds": 600,
        "deadline_next_day_local_time": "00:30",
    }
    assert MAINTENANCE_ACTION_REGISTRY["maintenance.replay_wealth_sector_heat_history"].schedule_enabled is False
    news_action = MAINTENANCE_ACTION_REGISTRY["maintenance.materialize_news_stock_links"]
    assert news_action.executor_key == "news_stock_linking"
    assert news_action.target_tables == ("core_serving.news_stock_link",)
    assert news_action.manual_time_regime == "natural_day_range"
    assert [parameter.key for parameter in news_action.parameters] == ["start_date", "end_date"]
    assert all(parameter.required for parameter in news_action.parameters)
    assert news_action.default_params == {
        "rule_version": "news-stock-rule-v1",
        "news_scope": "all",
    }
    assert news_action.schedule_repeat_policy is not None
    assert news_action.schedule_repeat_policy.allowed_modes == ("intraday_interval",)
    assert news_action.schedule_repeat_policy.default_interval_minutes == 5
    assert news_action.schedule_repeat_policy.minimum_interval_minutes == 3
    assert news_action.schedule_repeat_policy.timezone == "Asia/Shanghai"


def test_dataset_actions_are_resolved_from_dataset_definitions() -> None:
    definition = get_dataset_definition("daily")

    target = get_catalog_target("dataset_action", "daily.maintain")

    assert target == definition
    assert get_action_display_name("dataset_action", "daily.maintain") == f"维护{definition.display_name}"
    assert definition.capabilities.get_action("maintain") is not None
    assert definition.storage.target_table == "core_serving.equity_daily_bar"


def test_research_report_catalog_and_workflow_scope() -> None:
    item = resolve_default_dataset_catalog_item("research_report")
    workflow_dataset_keys = {
        step.dataset_key
        for workflow in WORKFLOW_DEFINITION_REGISTRY.values()
        for step in workflow.steps
        if step.dataset_key is not None
    }

    assert item.group_key == "broker_recommendation"
    assert item.group_label == "券商推荐"
    assert item.item_order == 20
    assert "research_report" not in workflow_dataset_keys


def test_idx_factor_pro_catalog_and_workflow_scope() -> None:
    item = resolve_default_dataset_catalog_item("idx_factor_pro")
    workflow_dataset_keys = {
        step.dataset_key
        for workflow in WORKFLOW_DEFINITION_REGISTRY.values()
        for step in workflow.steps
        if step.dataset_key is not None
    }

    assert item.group_key == "index_market_data"
    assert item.group_label == "A股指数行情"
    assert item.item_order == 45
    assert "idx_factor_pro" not in workflow_dataset_keys


def test_workflow_steps_reference_dataset_action_keys() -> None:
    dataset_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    for workflow in WORKFLOW_DEFINITION_REGISTRY.values():
        assert workflow.domain_key == WORKFLOW_DOMAIN_KEY
        assert workflow.domain_display_name == WORKFLOW_DOMAIN_DISPLAY_NAME
        assert workflow.group_order == WORKFLOW_GROUP_ORDER
        for step in workflow.steps:
            if step.action_key.startswith("maintenance."):
                assert step.action_key in MAINTENANCE_ACTION_REGISTRY
                continue
            definition, action = get_dataset_definition_by_action_key(step.action_key)
            assert action == "maintain"
            assert definition.dataset_key in dataset_keys


def test_dc_member_workflow_runs_after_dc_index() -> None:
    for workflow in WORKFLOW_DEFINITION_REGISTRY.values():
        dataset_keys = [step.dataset_key for step in workflow.steps if step.dataset_key is not None]
        if "dc_member" not in dataset_keys:
            continue

        assert "dc_index" in dataset_keys, f"{workflow.key} must prepare dc_index before dc_member"
        assert dataset_keys.index("dc_index") < dataset_keys.index("dc_member"), (
            f"{workflow.key} must run dc_index before dc_member"
        )


def test_ths_member_workflow_runs_after_ths_index() -> None:
    for workflow in WORKFLOW_DEFINITION_REGISTRY.values():
        dataset_keys = [step.dataset_key for step in workflow.steps if step.dataset_key is not None]
        if "ths_member" not in dataset_keys:
            continue

        assert "ths_index" in dataset_keys, f"{workflow.key} must prepare ths_index before ths_member"
        assert dataset_keys.index("ths_index") < dataset_keys.index("ths_member"), (
            f"{workflow.key} must run ths_index before ths_member"
        )


def test_workflow_time_contracts_match_step_requirements() -> None:
    reference_data = WORKFLOW_DEFINITION_REGISTRY["reference_data_refresh"]
    daily_market_close = WORKFLOW_DEFINITION_REGISTRY["daily_market_close_maintenance"]
    daily_moneyflow = WORKFLOW_DEFINITION_REGISTRY["daily_moneyflow_maintenance"]
    index_extension = WORKFLOW_DEFINITION_REGISTRY["index_extension_maintenance"]
    index_kline = WORKFLOW_DEFINITION_REGISTRY["index_kline_maintenance_pipeline"]

    assert [step.dataset_key for step in reference_data.steps] == [
        "stock_basic",
        "namechange",
        "st",
        "bse_mapping",
        "stock_company",
        "trade_cal",
        "etf_basic",
        "etf_index",
        "index_basic",
        "hk_basic",
    ]
    assert reference_data.workflow_profile == "point_incremental"

    assert [param.key for param in daily_market_close.parameters] == ["trade_date", "start_date", "end_date"]
    assert daily_market_close.workflow_profile == "point_incremental"
    assert [step.dataset_key for step in daily_market_close.steps] == [
        "daily",
        "stk_auction_o",
        "stk_auction_c",
        "adj_factor",
        "daily_basic",
        "bak_basic",
        "cyq_perf",
        "stk_factor_pro",
        "stk_limit",
        "stock_st",
        "limit_list_d",
        "suspend_d",
        "top_list",
        "block_trade",
        "fund_daily",
        "fund_adj",
        "ths_daily",
        "dc_index",
        "dc_member",
        "dc_daily",
        "ths_hot",
        "dc_hot",
        "limit_list_ths",
        "limit_step",
        "limit_cpt_list",
        "kpl_concept_cons",
        "anns_d",
        "irm_qa_sh",
        "irm_qa_sz",
    ]
    assert "cyq_chips" not in [step.dataset_key for step in daily_market_close.steps]

    assert [param.key for param in daily_moneyflow.parameters] == ["trade_date", "start_date", "end_date"]
    assert daily_moneyflow.workflow_profile == "point_incremental"

    assert [param.key for param in index_extension.parameters] == ["start_date", "end_date"]
    assert index_extension.workflow_profile == "range_rebuild"

    assert [param.key for param in index_kline.parameters] == ["start_date", "end_date"]
    assert index_kline.workflow_profile == "range_rebuild"


def test_workflow_catalog_does_not_use_legacy_execution_language() -> None:
    legacy_repair_term = "back" + "fill"
    for workflow in WORKFLOW_DEFINITION_REGISTRY.values():
        assert legacy_repair_term not in workflow.key
        assert "sync" not in workflow.key
        assert "同步" not in workflow.display_name
        assert "同步" not in workflow.description


def test_action_display_name_uses_dataset_action_language() -> None:
    assert get_action_display_name("dataset_action", "stock_basic.maintain") == "维护股票主数据"
    assert get_action_display_name("dataset_action", "daily.maintain") == "维护股票日线"


def test_dataset_action_must_be_known_action_key() -> None:
    assert get_catalog_target("dataset_action", "daily") is None
    assert get_action_display_name("dataset_action", "daily") is None
