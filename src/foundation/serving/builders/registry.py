from __future__ import annotations

from src.foundation.serving.builders.base import ServingBuilder


class ServingBuilderRegistry:
    def __init__(self) -> None:
        self._builders: dict[str, ServingBuilder] = {}

    def register(self, builder: ServingBuilder) -> None:
        key = builder.dataset_key
        if key in self._builders:
            raise ValueError(f"Serving builder already registered: {key}")
        self._builders[key] = builder

    def get(self, dataset_key: str) -> ServingBuilder | None:
        return self._builders.get(dataset_key)
