from __future__ import annotations

from src.foundation.serving.targets import get_target_dao_attr


def test_serving_target_mapping_stock_basic() -> None:
    assert get_target_dao_attr("stock_basic") == "security"


def test_serving_target_mapping_equity_core_datasets() -> None:
    assert get_target_dao_attr("equity_daily_bar") == "equity_daily_bar"
    assert get_target_dao_attr("equity_adj_factor") == "equity_adj_factor"
    assert get_target_dao_attr("equity_daily_basic") == "equity_daily_basic"
