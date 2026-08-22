from __future__ import annotations

from src.ops.action_catalog import list_workflow_definitions


def test_etf_share_size_is_not_added_to_existing_workflows() -> None:
    workflow_dataset_keys = {
        step.dataset_key
        for workflow in list_workflow_definitions()
        for step in workflow.steps
        if step.dataset_key is not None
    }

    assert "etf_share_size" not in workflow_dataset_keys
