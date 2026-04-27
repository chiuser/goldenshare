from __future__ import annotations

from src.foundation.models.table_model_registry import table_model_registry


# Dataset-specific observed-range filters for shared serving tables.
OBSERVED_DATE_FILTERS: dict[str, tuple[str, str]] = {
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
