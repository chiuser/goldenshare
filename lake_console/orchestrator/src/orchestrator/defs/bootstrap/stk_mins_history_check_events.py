from __future__ import annotations

import dagster as dg


def count_succeeded_asset_check_executions(
    instance: dg.DagsterInstance,
    check_key: dg.AssetCheckKey,
) -> int:
    """Count succeeded executions in the existing bounded history query."""
    records = instance.event_log_storage.get_asset_check_execution_history(
        check_key,
        limit=50000,
    )
    return sum(1 for record in records if record.status.value == "SUCCEEDED")
