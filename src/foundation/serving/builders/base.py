from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.foundation.resolution.types import ResolutionPolicy


@dataclass(frozen=True)
class ServingBuildResult:
    rows: list[dict[str, Any]]
    resolved_count: int


class ServingBuilder(Protocol):
    dataset_key: str

    def build_rows(
        self,
        *,
        std_rows_by_source: dict[str, list[dict[str, Any]]],
        policy: ResolutionPolicy,
        active_sources: set[str] | None,
        target_columns: set[str],
    ) -> ServingBuildResult: ...
