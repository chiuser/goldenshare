from __future__ import annotations

from src.foundation.serving.builders.resolution_serving_builder import ResolutionServingBuilder


class IndicatorMacdServingBuilder(ResolutionServingBuilder):
    dataset_key = "indicator_macd"
    business_key_fields = ("ts_code", "trade_date", "adjustment", "version")
