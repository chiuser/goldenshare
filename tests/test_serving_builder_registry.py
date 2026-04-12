from __future__ import annotations

import pytest

from src.foundation.serving.builders.registry import ServingBuilderRegistry


class _DummyBuilder:
    dataset_key = "dummy"

    def build_rows(self, **kwargs):  # pragma: no cover - protocol smoke only
        return kwargs


def test_serving_builder_registry_register_and_get() -> None:
    registry = ServingBuilderRegistry()
    builder = _DummyBuilder()
    registry.register(builder)
    assert registry.get("dummy") is builder


def test_serving_builder_registry_rejects_duplicate_dataset() -> None:
    registry = ServingBuilderRegistry()
    registry.register(_DummyBuilder())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_DummyBuilder())
