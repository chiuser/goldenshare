from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions
from src.ops.action_catalog import list_maintenance_actions, list_workflow_definitions
from src.ops.services.schedule_automation_capability_resolver import (
    FRESHNESS_LATEST_OPEN_CONDITION,
    REMOTE_SOURCE_PROBE_CONDITIONS,
    ScheduleAutomationCapabilityResolver,
)


def _schedulable_targets() -> list[tuple[str, str]]:
    targets = [
        ("dataset_action", definition.action_key("maintain"))
        for definition in list_dataset_definitions()
        if (action := definition.capabilities.get_action("maintain")) is not None and action.schedule_enabled
    ]
    targets.extend(("maintenance_action", action.key) for action in list_maintenance_actions() if action.schedule_enabled)
    targets.extend(("workflow", workflow.key) for workflow in list_workflow_definitions() if workflow.schedule_enabled)
    return targets


def test_every_schedulable_target_has_a_capability() -> None:
    resolver = ScheduleAutomationCapabilityResolver()
    targets = _schedulable_targets()

    assert len(targets) == 86
    assert all(resolver.resolve(target_type=target_type, target_key=target_key) is not None for target_type, target_key in targets)
    assert resolver.resolve(target_type="workflow", target_key="index_extension_maintenance") is None


def test_workflow_and_maintenance_capabilities_are_schedule_only() -> None:
    resolver = ScheduleAutomationCapabilityResolver()

    for workflow in list_workflow_definitions():
        capability = resolver.resolve(target_type="workflow", target_key=workflow.key)
        if not workflow.schedule_enabled:
            assert capability is None
            continue
        assert capability is not None
        assert [option.mode for option in capability.trigger_options] == ["schedule"]
        assert capability.probe_conditions == ()

    for action in list_maintenance_actions():
        capability = resolver.resolve(target_type="maintenance_action", target_key=action.key)
        if not action.schedule_enabled:
            assert capability is None
            continue
        assert capability is not None
        assert [option.mode for option in capability.trigger_options] == ["schedule"]
        assert capability.probe_conditions == ()


def test_remote_probe_capabilities_are_bound_to_their_exact_dataset_actions() -> None:
    resolver = ScheduleAutomationCapabilityResolver()
    expected = {
        "stk_mins.maintain": "remote_stk_mins_ready",
        "index_daily.maintain": "remote_index_daily_ready",
        "index_mins.maintain": "remote_index_mins_ready",
        "kpl_list.maintain": "remote_kpl_list_ready",
        "idx_factor_pro.maintain": "remote_idx_factor_pro_ready",
        "margin.maintain": "remote_margin_ready",
        "margin_detail.maintain": "remote_margin_detail_ready",
    }

    assert set(expected.values()) == REMOTE_SOURCE_PROBE_CONDITIONS
    for action_key, condition_kind in expected.items():
        capability = resolver.resolve(target_type="dataset_action", target_key=action_key)
        assert capability is not None
        assert "schedule" not in [option.mode for option in capability.trigger_options]
        assert [condition.kind for condition in capability.probe_conditions] == [condition_kind]
        condition = capability.probe_conditions[0]
        definition = get_dataset_definition(action_key.removesuffix(".maintain"))
        assert condition.probe.source == "system_default"
        assert resolver.system_source_for(condition_kind=condition_kind, dataset_key=definition.dataset_key) == definition.source.source_key_default


def test_index_daily_probe_is_available_only_for_its_direct_automatic_target() -> None:
    resolver = ScheduleAutomationCapabilityResolver()

    direct = resolver.resolve(target_type="dataset_action", target_key="index_daily.maintain")
    workflow = resolver.resolve(target_type="workflow", target_key="daily_market_close_maintenance")

    assert direct is not None
    assert [condition.kind for condition in direct.probe_conditions] == ["remote_index_daily_ready"]
    assert workflow is not None
    assert workflow.probe_conditions == ()
    assert [option.mode for option in workflow.trigger_options] == ["schedule"]


def test_continuous_dataset_keeps_generic_freshness_probe_capability() -> None:
    capability = ScheduleAutomationCapabilityResolver().resolve(target_type="dataset_action", target_key="daily.maintain")

    assert capability is not None
    assert [option.mode for option in capability.trigger_options] == ["schedule", "probe", "schedule_probe_fallback"]
    assert [condition.kind for condition in capability.probe_conditions] == [FRESHNESS_LATEST_OPEN_CONDITION]
