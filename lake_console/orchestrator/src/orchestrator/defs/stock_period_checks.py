"""Current partition checks using standard materialization metadata only."""

from pathlib import Path

from orchestrator.defs.run_contracts.metadata import (
    DAGSTER_ROW_COUNT_METADATA_KEY,
    DAGSTER_URI_METADATA_KEY,
)


def verify_period_materialization(record, partition, path, *, rows=None):
    """Never follow proof references or freeze a historical file's contents."""
    if record is None:
        raise ValueError("period_materialization_missing")
    materialization = record.asset_materialization
    metadata = materialization.metadata
    uri = getattr(metadata.get(DAGSTER_URI_METADATA_KEY), "value", None)
    recorded_rows = getattr(metadata.get(DAGSTER_ROW_COUNT_METADATA_KEY), "value", None)
    if (
        materialization.partition != partition
        or uri != str(Path(path))
        or type(recorded_rows) is not int
        or recorded_rows < 0
        or (rows is not None and recorded_rows != rows)
    ):
        raise ValueError("period_materialization_partition_path_or_rows_invalid")
    return recorded_rows
