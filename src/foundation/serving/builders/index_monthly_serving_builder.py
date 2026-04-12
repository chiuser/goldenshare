from __future__ import annotations

from src.foundation.serving.builders.resolution_serving_builder import ResolutionServingBuilder


class IndexMonthlyServingBuilder(ResolutionServingBuilder):
    dataset_key = "index_monthly"
    business_key_fields = ("ts_code", "trade_date")
