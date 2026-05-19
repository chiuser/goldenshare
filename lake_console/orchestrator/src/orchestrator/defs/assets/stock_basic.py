import os
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    STOCK_BASIC_RAW_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
    silver_stock_basic_select,
)
from orchestrator.defs.paths import raw_stock_basic_path, silver_stock_basic_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


def _column_names(connection, path: Path, *, hive_partitioning: bool = False) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(count_parquet_query(path, hive_partitioning=hive_partitioning)).fetchone()[
            0
        ]
    )


def _list_status_distribution(
    connection,
    path: Path,
    *,
    hive_partitioning: bool = False,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT list_status, count(*) AS row_count
        FROM {read_parquet(path, hive_partitioning=hive_partitioning)}
        GROUP BY list_status
        ORDER BY list_status
        """
    ).fetchall()
    return [
        {
            "list_status": row[0],
            "row_count": int(row[1]),
        }
        for row in rows
    ]


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


@dg.asset(
    name="raw_tushare_stock_basic",
    group_name="basic",
    description="Tushare stock_basic raw file registered under the new raw lake path.",
)
def raw_tushare_stock_basic(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    path = raw_stock_basic_path(lake_root.root())
    if not path.exists():
        raise FileNotFoundError(f"Missing raw stock basic file: {path}")

    with duckdb.connect() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)
        row_count = _row_count(connection, path, hive_partitioning=False)
        list_status_distribution = _list_status_distribution(
            connection,
            path,
            hive_partitioning=False,
        )

    return dg.MaterializeResult(
        metadata={
            "path": str(path),
            "row_count": row_count,
            "columns": columns,
            "layer": "raw",
            "source_api": "stock_basic",
            "data_contract": "source_mirror",
            "raw_contract": "Tushare stock_basic explicit fields; date fields remain YYYYMMDD strings.",
            "expected_source_columns": list(STOCK_BASIC_RAW_COLUMNS),
            "list_status_distribution": list_status_distribution,
        }
    )


@dg.asset(
    name="silver_stock_basic",
    deps=["raw_tushare_stock_basic"],
    group_name="basic",
    description="Standardized stock basic lifecycle data derived from Tushare stock_basic raw data.",
)
def silver_stock_basic(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    raw_path = raw_stock_basic_path(lake_root.root())
    target_path = silver_stock_basic_path(lake_root.root())
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw stock basic file: {raw_path}")

    with duckdb.connect() as connection:
        _replace_parquet_from_query(
            connection,
            silver_stock_basic_select(raw_path),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)
        list_status_distribution = _list_status_distribution(
            connection,
            target_path,
            hive_partitioning=False,
        )

    return dg.MaterializeResult(
        metadata={
            "path": str(target_path),
            "row_count": row_count,
            "columns": columns,
            "layer": "silver",
            "data_contract": "standardized_stock_basic_lifecycle",
            "list_status_distribution": list_status_distribution,
        }
    )
