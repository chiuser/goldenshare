"""Translate Ops task intent into the existing named weekly ingestion contract."""
from src.foundation.datasets.stock_weekly_adj_contracts import DATASET_KEY


def dataset_action_trigger_source(dataset_key: str, trigger_source: str) -> str:
    """Keep Ops 'scheduled' in TaskRun; weekly ingestion expects 'schedule'."""
    if dataset_key == DATASET_KEY and trigger_source == "scheduled":
        return "schedule"
    return trigger_source
