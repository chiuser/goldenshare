from __future__ import annotations

from src.foundation.models.table_model_registry import table_model_registry


# Dataset-specific source and frequency filters for observed date ranges.
OBSERVED_DATE_FILTERS: dict[str, tuple[str, str]] = {
    "index_weekly": ("api_name", "index_weekly"),
    "index_monthly": ("api_name", "index_monthly"),
    "stk_period_bar_week": ("freq", "week"),
    "stk_period_bar_month": ("freq", "month"),
    "stk_period_bar_adj_week": ("freq", "week"),
    "stk_period_bar_adj_month": ("freq", "month"),
}

OBSERVED_DATE_AUTHORITATIVE_KEYS = {
    "stk_period_bar_week",
    "stk_period_bar_month",
    "stk_period_bar_adj_week",
    "stk_period_bar_adj_month",
}

OBSERVED_DATE_MODEL_REGISTRY: dict[str, type] = table_model_registry()
