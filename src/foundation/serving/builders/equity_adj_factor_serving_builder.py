from __future__ import annotations

from src.foundation.serving.builders.resolution_serving_builder import ResolutionServingBuilder


class EquityAdjFactorServingBuilder(ResolutionServingBuilder):
    dataset_key = "equity_adj_factor"
    business_key_fields = ("ts_code", "trade_date")
