from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition, get_dataset_definition_by_action_key, list_dataset_definitions
from src.ops.action_catalog import (
    MAINTENANCE_ACTION_REGISTRY,
    WORKFLOW_DEFINITION_REGISTRY,
    get_action_display_name,
    get_catalog_target,
)


def test_maintenance_action_registry_keeps_only_explicit_actions() -> None:
    assert set(MAINTENANCE_ACTION_REGISTRY) == {
        "maintenance.rebuild_dm",
        "maintenance.rebuild_index_kline_serving",
    }
    assert {action.domain_key for action in MAINTENANCE_ACTION_REGISTRY.values()} == {"maintenance"}


def test_dataset_actions_are_resolved_from_dataset_definitions() -> None:
    definition = get_dataset_definition("daily")

    target = get_catalog_target("dataset_action", "daily.maintain")

    assert target == definition
    assert get_action_display_name("dataset_action", "daily.maintain") == f"维护{definition.display_name}"
    assert definition.capabilities.get_action("maintain") is not None
    assert definition.storage.target_table == "core_serving.equity_daily_bar"


def test_workflow_steps_reference_dataset_action_keys() -> None:
    dataset_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    for workflow in WORKFLOW_DEFINITION_REGISTRY.values():
        for step in workflow.steps:
            if step.action_key.startswith("maintenance."):
                assert step.action_key in MAINTENANCE_ACTION_REGISTRY
                continue
            definition, action = get_dataset_definition_by_action_key(step.action_key)
            assert action == "maintain"
            assert definition.dataset_key in dataset_keys


def test_workflow_catalog_does_not_use_legacy_execution_language() -> None:
    legacy_repair_term = "back" + "fill"
    for workflow in WORKFLOW_DEFINITION_REGISTRY.values():
        assert legacy_repair_term not in workflow.key
        assert "sync" not in workflow.key
        assert "同步" not in workflow.display_name
        assert "同步" not in workflow.description


def test_action_display_name_uses_dataset_action_language() -> None:
    assert get_action_display_name("dataset_action", "stock_basic.maintain") == "维护股票主数据"
    assert get_action_display_name("dataset_action", "daily.maintain") == "维护股票日线"


def test_dataset_action_must_be_known_action_key() -> None:
    assert get_catalog_target("dataset_action", "daily") is None
    assert get_action_display_name("dataset_action", "daily") is None
