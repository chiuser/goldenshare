from __future__ import annotations


SERVING_TARGET_DAO_ATTR: dict[str, str] = {
    "stock_basic": "security",
    "equity_daily_bar": "equity_daily_bar",
    "equity_adj_factor": "equity_adj_factor",
    "equity_daily_basic": "equity_daily_basic",
    "moneyflow": "equity_moneyflow",
    "index_daily": "index_daily_serving",
    "index_weekly": "index_weekly_serving",
    "index_monthly": "index_monthly_serving",
    "stk_period_bar_week": "stk_period_bar",
    "stk_period_bar_month": "stk_period_bar",
    "stk_period_bar_adj_week": "stk_period_bar_adj",
    "stk_period_bar_adj_month": "stk_period_bar_adj",
}


def get_target_dao_attr(dataset_key: str) -> str | None:
    return SERVING_TARGET_DAO_ATTR.get(dataset_key)
