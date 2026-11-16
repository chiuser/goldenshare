"""Translate Ops task intent into the existing named weekly ingestion contract."""
from src.foundation.datasets.registry import get_dataset_definition


def dataset_action_trigger_source(dataset_key: str, trigger_source: str) -> str:
    """Keep Ops 'scheduled' in TaskRun; weekly ingestion expects 'schedule'."""
    if trigger_source != 'scheduled':
        return trigger_source
    definition = get_dataset_definition(dataset_key)
    if trigger_source == 'scheduled' and (definition.planning.weekly_adj_policy is not None or definition.planning.stock_period_adj_policy is not None):
        return "schedule"
    return trigger_source
