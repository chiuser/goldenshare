from __future__ import annotations

from typing import Any, Protocol

from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.builders.security_serving_builder import SecurityServingBuildResult


class ServingBuilder(Protocol):
    dataset_key: str

    def build_rows(
        self,
        *,
        std_rows_by_source: dict[str, list[dict[str, Any]]],
        policy: ResolutionPolicy,
        active_sources: set[str] | None,
        target_columns: set[str],
    ) -> SecurityServingBuildResult: ...
