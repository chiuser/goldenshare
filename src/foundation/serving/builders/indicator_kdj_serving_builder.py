from __future__ import annotations

from src.foundation.serving.builders.resolution_serving_builder import ResolutionServingBuilder


class IndicatorKdjServingBuilder(ResolutionServingBuilder):
    dataset_key = "indicator_kdj"
    business_key_fields = ("ts_code", "trade_date", "adjustment", "version")
