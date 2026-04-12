from __future__ import annotations

from src.foundation.serving.builders.resolution_serving_builder import ResolutionServingBuilder


class EquityDailyBasicServingBuilder(ResolutionServingBuilder):
    dataset_key = "equity_daily_basic"
    business_key_fields = ("ts_code", "trade_date")
