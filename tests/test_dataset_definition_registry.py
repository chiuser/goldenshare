from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions
from src.foundation.ingestion.runtime_registry import DATASET_RUNTIME_REGISTRY


def test_dataset_definition_registry_is_not_runtime_contract_projection() -> None:
    import inspect

    import src.foundation.datasets.registry as registry

    assert not hasattr(registry, "_from_contract")
    assert "services.sync" not in inspect.getsource(registry)


def test_dataset_definition_registry_covers_runtime_registry() -> None:
    definition_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    runtime_keys = set(DATASET_RUNTIME_REGISTRY)

    assert definition_keys == runtime_keys
    assert len(definition_keys) == 57


def test_dataset_definition_projects_core_dataset_facts() -> None:
    definition = get_dataset_definition("dc_hot")

    assert definition.identity.display_name == "东方财富热榜"
    assert definition.source.api_name == "dc_hot"
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.storage.target_table == "core_serving.dc_hot"
    assert definition.capabilities.get_action("maintain") is not None
    assert definition.planning.enum_fanout_defaults["hot_type"] == ("人气榜", "飙升榜")


def test_dataset_definition_owns_dc_board_type_filter() -> None:
    definition = get_dataset_definition("dc_member")
    idx_type = next(field for field in definition.input_model.filters if field.name == "idx_type")

    assert idx_type.display_name == "板块类型"
    assert idx_type.field_type == "list"
    assert idx_type.multi_value is True
    assert idx_type.enum_values == ("行业板块", "概念板块", "地域板块")


def test_dataset_definition_identity_does_not_keep_legacy_job_aliases() -> None:
    for definition in list_dataset_definitions():
        assert not any(alias.startswith(("sync_", "backfill_")) for alias in definition.identity.aliases)


def test_dataset_definition_owns_dataset_card_grouping() -> None:
    moneyflow = get_dataset_definition("moneyflow")
    biying_moneyflow = get_dataset_definition("biying_moneyflow")
    biying_equity_daily = get_dataset_definition("biying_equity_daily")

    assert moneyflow.card_key == "moneyflow"
    assert moneyflow.card_priority == 100
    assert biying_moneyflow.card_key == "moneyflow"
    assert biying_moneyflow.card_priority == 200
    assert biying_equity_daily.card_key == "biying_equity_daily"
