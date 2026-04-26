from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions
from src.foundation.ingestion.runtime_registry import DATASET_RUNTIME_REGISTRY, build_dataset_maintain_service


def test_runtime_registry_contains_all_dataset_definitions() -> None:
    definition_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    assert set(DATASET_RUNTIME_REGISTRY) == definition_keys
    assert "stock_basic" in DATASET_RUNTIME_REGISTRY
    assert "dc_member" in DATASET_RUNTIME_REGISTRY
    assert "stk_factor_pro" in DATASET_RUNTIME_REGISTRY


def test_build_dataset_maintain_service_uses_definition_identity(mocker) -> None:
    session = mocker.Mock()
    service = build_dataset_maintain_service("trade_cal", session)

    assert service.dataset_key == "trade_cal"
    assert service.definition == get_dataset_definition("trade_cal")
