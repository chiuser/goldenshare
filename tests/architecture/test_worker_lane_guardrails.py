from src.ops.action_catalog import list_workflow_definitions


def test_minute_datasets_are_not_embedded_in_workflows() -> None:
    minute_keys = {"stk_mins", "index_mins"}

    for workflow in list_workflow_definitions():
        assert {
            step.dataset_key
            for step in workflow.steps
            if step.dataset_key is not None
        }.isdisjoint(minute_keys), workflow.key
