import os
import re
from pathlib import Path
from typing import Any

from orchestrator.defs.bootstrap.dataset_spec import BootstrapDatasetSpec
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
)
from orchestrator.defs.resources import DuckDBResource


TRADE_DATE_PARTITION_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bootstrap_partition_to_raw(
    spec: BootstrapDatasetSpec,
    partition_key: str,
    duckdb_resource: DuckDBResource,
) -> dict[str, Any]:
    if spec.partition_type != "trade_date":
        raise ValueError("bootstrap_partition_to_raw requires partition_type='trade_date'.")
    if not TRADE_DATE_PARTITION_PATTERN.match(partition_key):
        raise ValueError(f"Invalid trade_date partition key: {partition_key}")
    return _bootstrap_to_raw(spec, duckdb_resource, partition_key=partition_key)


def bootstrap_full_file_to_raw(
    spec: BootstrapDatasetSpec,
    duckdb_resource: DuckDBResource,
) -> dict[str, Any]:
    if spec.partition_type != "full":
        raise ValueError("bootstrap_full_file_to_raw requires partition_type='full'.")
    return _bootstrap_to_raw(spec, duckdb_resource, partition_key=None)


def _bootstrap_to_raw(
    spec: BootstrapDatasetSpec,
    duckdb_resource: DuckDBResource,
    *,
    partition_key: str | None,
) -> dict[str, Any]:
    source_path = spec.source_path(partition_key)
    target_path = spec.target_path(partition_key)
    tmp_path = _tmp_path(target_path)
    select_sql = _render_select_sql(spec, source_path, target_path, partition_key)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        with duckdb_resource.connect() as connection:
            connection.execute(copy_query_to_parquet(select_sql, tmp_path))
            row_count = _row_count(connection, tmp_path)
            columns = tuple(_column_names(connection, tmp_path))
            _validate_written_raw(spec, row_count, columns)
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return {
        "path": str(target_path),
        "row_count": row_count,
        "columns": list(columns),
        "source_method": spec.source_method_metadata,
        "bootstrap_spec": spec.dataset_key,
        "partition_key": partition_key,
        "empty_policy": spec.empty_policy,
    }


def _render_select_sql(
    spec: BootstrapDatasetSpec,
    source_path: Path,
    target_path: Path,
    partition_key: str | None,
) -> str:
    return spec.select_sql_template.format(
        old_path=duckdb_string(source_path),
        target_path=duckdb_string(target_path),
        partition_key=partition_key or "",
    )


def _validate_written_raw(
    spec: BootstrapDatasetSpec,
    row_count: int,
    columns: tuple[str, ...],
) -> None:
    if spec.empty_policy == "require_positive" and row_count <= 0:
        raise ValueError(f"Bootstrap produced no rows for required dataset: {spec.dataset_key}")
    if columns != spec.target_raw_fields:
        raise ValueError(
            "Bootstrap output columns do not match target_raw_fields for "
            f"{spec.dataset_key}: expected {spec.target_raw_fields}, got {columns}"
        )


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(describe_parquet_query(path, hive_partitioning=False)).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path) -> int:
    return int(connection.execute(count_parquet_query(path, hive_partitioning=False)).fetchone()[0])


def _tmp_path(target_path: Path) -> Path:
    return target_path.with_name(f"{target_path.name}.tmp")
