from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions
from src.ops.specs.registry import JOB_SPEC_REGISTRY, WORKFLOW_SPEC_REGISTRY, get_ops_spec, get_ops_spec_display_name


def test_job_spec_registry_keeps_only_maintenance_jobs() -> None:
    assert set(JOB_SPEC_REGISTRY) == {
        "maintenance.rebuild_dm",
        "maintenance.rebuild_index_kline_serving",
    }
    assert {spec.executor_kind for spec in JOB_SPEC_REGISTRY.values()} == {"maintenance"}


def test_dataset_action_specs_are_projected_from_dataset_definitions() -> None:
    definition = get_dataset_definition("daily")

    spec = get_ops_spec("dataset_action", "daily.maintain")

    assert spec == definition
    assert get_ops_spec_display_name("dataset_action", "daily.maintain") == f"维护{definition.display_name}"
    assert definition.capabilities.get_action("maintain") is not None
    assert definition.storage.target_table == "core_serving.equity_daily_bar"


def test_workflow_steps_reference_dataset_action_keys() -> None:
    dataset_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    for workflow in WORKFLOW_SPEC_REGISTRY.values():
        for step in workflow.steps:
            if step.job_key.startswith("maintenance."):
                assert step.job_key in JOB_SPEC_REGISTRY
                continue
            assert step.job_key.endswith(".maintain")
            assert step.job_key.removesuffix(".maintain") in dataset_keys


def test_ops_spec_display_name_uses_dataset_action_language() -> None:
    assert get_ops_spec_display_name("dataset_action", "stock_basic.maintain") == "维护股票主数据"
    assert get_ops_spec_display_name("dataset_action", "daily.maintain") == "维护股票日线"
