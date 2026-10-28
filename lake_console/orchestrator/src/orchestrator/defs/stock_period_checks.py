"""Current partition checks using standard materialization metadata only."""

from pathlib import Path

from orchestrator.defs.run_contracts.metadata import (
    DAGSTER_ROW_COUNT_METADATA_KEY,
    DAGSTER_URI_METADATA_KEY,
)


def verify_period_materialization_metadata(
    record, partition, path, *, version, rows=None, asset_key=None
):
    """Compare explicit metadata facts; a preimage never stats the current file."""
    if record is None:
        raise ValueError("period_materialization_missing")
    materialization = record.asset_materialization
    metadata = materialization.metadata
    uri = getattr(metadata.get(DAGSTER_URI_METADATA_KEY), "value", None)
    recorded_rows = getattr(metadata.get(DAGSTER_ROW_COUNT_METADATA_KEY), "value", None)
    if (
        materialization.partition != partition
        or (asset_key is not None and materialization.asset_key != asset_key)
        or uri != str(Path(path))
        or type(recorded_rows) is not int
        or recorded_rows < 0
        or (rows is not None and (type(rows) is not int or rows < 0))
        or (rows is not None and recorded_rows != rows)
    ):
        raise ValueError("period_materialization_partition_path_or_rows_invalid")
    actual_version = getattr(metadata.get("goldenshare/period_file_version"), "value", None)
    def valid_version(values):
        return (
            type(values) is list and len(values) == 5
            and all(type(value) is int and value >= 0 for value in values)
        )

    if not valid_version(version) or not valid_version(actual_version) or actual_version != version:
        raise ValueError("period_materialization_file_version_invalid")
    return recorded_rows


def verify_period_materialization(record, partition, path, *, rows=None):
    """Never follow proof references or freeze a historical file's contents."""
    metadata = record.asset_materialization.metadata if record is not None else {}
    # Preserve validation before stat for malformed/missing materializations.
    verify_period_materialization_metadata(
        record, partition, path, rows=rows,
        version=getattr(metadata.get("goldenshare/period_file_version"), "value", None),
    )
    from orchestrator.defs.io.stock_period_raw import file_version

    return verify_period_materialization_metadata(
        record, partition, path, rows=rows, version=file_version(path)
    )
