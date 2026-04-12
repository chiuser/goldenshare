from __future__ import annotations

from src.foundation.serving.targets import get_target_dao_attr


def test_serving_target_mapping_stock_basic() -> None:
    assert get_target_dao_attr("stock_basic") == "security"


def test_serving_target_mapping_equity_core_datasets() -> None:
    assert get_target_dao_attr("equity_daily_bar") == "equity_daily_bar"
    assert get_target_dao_attr("equity_adj_factor") == "equity_adj_factor"
    assert get_target_dao_attr("equity_daily_basic") == "equity_daily_basic"
    assert get_target_dao_attr("indicator_macd") == "indicator_macd"
    assert get_target_dao_attr("indicator_kdj") == "indicator_kdj"
    assert get_target_dao_attr("indicator_rsi") == "indicator_rsi"


def test_serving_target_mapping_index_core_datasets() -> None:
    assert get_target_dao_attr("index_daily") == "index_daily_serving"
    assert get_target_dao_attr("index_weekly") == "index_weekly_serving"
    assert get_target_dao_attr("index_monthly") == "index_monthly_serving"


def test_serving_target_mapping_stk_period_datasets() -> None:
    assert get_target_dao_attr("stk_period_bar_week") == "stk_period_bar"
    assert get_target_dao_attr("stk_period_bar_month") == "stk_period_bar"
    assert get_target_dao_attr("stk_period_bar_adj_week") == "stk_period_bar_adj"
    assert get_target_dao_attr("stk_period_bar_adj_month") == "stk_period_bar_adj"
