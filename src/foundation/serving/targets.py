from __future__ import annotations


SERVING_TARGET_DAO_ATTR: dict[str, str] = {
    "stock_basic": "security",
    "equity_daily_bar": "equity_daily_bar",
    "equity_adj_factor": "equity_adj_factor",
    "equity_daily_basic": "equity_daily_basic",
    "index_daily": "index_daily_serving",
    "index_weekly": "index_weekly_serving",
    "index_monthly": "index_monthly_serving",
}


def get_target_dao_attr(dataset_key: str) -> str | None:
    return SERVING_TARGET_DAO_ATTR.get(dataset_key)
