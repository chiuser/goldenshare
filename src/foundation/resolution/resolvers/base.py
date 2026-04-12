from __future__ import annotations

from typing import Protocol

from src.foundation.resolution.types import ResolutionInput, ResolutionOutput, ResolutionPolicy


class DatasetResolver(Protocol):
    dataset_key: str

    def resolve(self, resolution_input: ResolutionInput, policy: ResolutionPolicy) -> ResolutionOutput: ...
