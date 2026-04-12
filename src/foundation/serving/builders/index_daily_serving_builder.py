from __future__ import annotations

from src.foundation.serving.builders.resolution_serving_builder import ResolutionServingBuilder


class IndexDailyServingBuilder(ResolutionServingBuilder):
    dataset_key = "index_daily"
    business_key_fields = ("ts_code", "trade_date")
