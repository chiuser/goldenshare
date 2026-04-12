from __future__ import annotations

from src.foundation.serving.builders.resolution_serving_builder import ResolutionServingBuilder


class StkPeriodBarMonthServingBuilder(ResolutionServingBuilder):
    dataset_key = "stk_period_bar_month"
    business_key_fields = ("ts_code", "trade_date", "freq")
