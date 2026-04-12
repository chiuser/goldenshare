from __future__ import annotations

from typing import Any

from src.foundation.serving.builders.base import ServingBuildResult
from src.foundation.serving.builders.resolution_serving_builder import ResolutionServingBuilder


class SecurityServingBuildResult(ServingBuildResult):
    pass


class SecurityServingBuilder(ResolutionServingBuilder):
    dataset_key = "stock_basic"
    business_key_fields = ("ts_code",)

    def build_rows(self, **kwargs: Any) -> SecurityServingBuildResult:
        result = super().build_rows(**kwargs)
        return SecurityServingBuildResult(rows=result.rows, resolved_count=result.resolved_count)
