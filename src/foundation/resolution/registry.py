from __future__ import annotations

from src.foundation.resolution.resolvers.base import DatasetResolver


class ResolutionRegistry:
    def __init__(self) -> None:
        self._resolvers: dict[str, DatasetResolver] = {}

    def register(self, resolver: DatasetResolver) -> None:
        key = resolver.dataset_key
        if key in self._resolvers:
            raise ValueError(f"Resolver already registered for dataset: {key}")
        self._resolvers[key] = resolver

    def get(self, dataset_key: str) -> DatasetResolver | None:
        return self._resolvers.get(dataset_key)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._resolvers))
