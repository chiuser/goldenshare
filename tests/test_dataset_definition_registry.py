from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions
from src.foundation.services.sync_v2.registry import list_sync_v2_contracts


def test_dataset_definition_registry_covers_sync_v2_contracts() -> None:
    definition_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    contract_keys = {contract.dataset_key for contract in list_sync_v2_contracts()}

    assert definition_keys == contract_keys


def test_dataset_definition_projects_core_dataset_facts() -> None:
    definition = get_dataset_definition("dc_hot")

    assert definition.identity.display_name == "东方财富热榜"
    assert definition.source.api_name == "dc_hot"
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.storage.target_table == "core_serving.dc_hot"
    assert definition.capabilities.get_action("maintain") is not None
    assert definition.planning.enum_fanout_defaults["hot_type"] == ("人气榜", "飙升榜")
