import os
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
)
from orchestrator.defs.paths import silver_index_daily_active_pool_path
from orchestrator.defs.resources import DuckDBResource, LakeMetaPostgresResource, LakeRootResource


INDEX_DAILY_ACTIVE_POOL_COLUMNS = ("ts_code", "display_name")
INDEX_DAILY_ACTIVE_POOL_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "display_name": "VARCHAR",
}


def load_index_daily_active_pool_rows(
    lake_meta_postgres: LakeMetaPostgresResource,
) -> list[dict[str, Any]]:
    lake_meta_postgres.ensure_index_metadata_tables()
    with lake_meta_postgres.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ts_code, display_name
                FROM index_daily_active_pool
                ORDER BY ts_code
                """
            )
            rows = cursor.fetchall()
    return [
        {
            "ts_code": row[0],
            "display_name": row[1],
        }
        for row in rows
    ]


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(describe_parquet_query(path, hive_partitioning=False)).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path) -> int:
    return int(
        connection.execute(count_parquet_query(path, hive_partitioning=False)).fetchone()[0]
    )


def _replace_rows_to_parquet(
    duckdb: DuckDBResource,
    rows: list[dict[str, Any]],
    target_path: Path,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    pending_parquet_path = target_path.with_name(f"{target_path.name}.tmp")
    if pending_parquet_path.exists():
        pending_parquet_path.unlink()

    with duckdb.connect() as connection:
        column_defs = ", ".join(
            f"{_quote_identifier(column)} {INDEX_DAILY_ACTIVE_POOL_COLUMN_TYPES[column]}"
            for column in INDEX_DAILY_ACTIVE_POOL_COLUMNS
        )
        connection.execute(f"CREATE TEMP TABLE active_pool_rows ({column_defs})")
        placeholders = ", ".join("?" for _ in INDEX_DAILY_ACTIVE_POOL_COLUMNS)
        values = [[row.get(column) for column in INDEX_DAILY_ACTIVE_POOL_COLUMNS] for row in rows]
        connection.executemany(f"INSERT INTO active_pool_rows VALUES ({placeholders})", values)
        select_sql = ", ".join(
            f"CAST({_quote_identifier(column)} AS {INDEX_DAILY_ACTIVE_POOL_COLUMN_TYPES[column]}) "
            f"AS {_quote_identifier(column)}"
            for column in INDEX_DAILY_ACTIVE_POOL_COLUMNS
        )
        connection.execute(
            copy_query_to_parquet(f"SELECT {select_sql} FROM active_pool_rows", pending_parquet_path)
        )

    os.replace(pending_parquet_path, target_path)


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) + chr(34))}"'


@dg.asset(
    name="silver_index_daily_active_pool",
    group_name="index",
    description="指数日线有效指数池，决定哪些指数进入指数日线标准表。",
)
def silver_index_daily_active_pool(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    lake_meta_postgres: LakeMetaPostgresResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    rows = load_index_daily_active_pool_rows(lake_meta_postgres)
    if not rows:
        raise RuntimeError(
            "index_daily_active_pool is empty; initialize or maintain local metadata before "
            "materializing silver_index_daily_active_pool."
        )

    target_path = silver_index_daily_active_pool_path(lake_root.root())
    _replace_rows_to_parquet(duckdb, rows, target_path)

    with duckdb.connect() as connection:
        columns = _column_names(connection, target_path)
        row_count = _row_count(connection, target_path)

    return dg.MaterializeResult(
        metadata={
            "path": str(target_path),
            "row_count": row_count,
            "columns": columns,
            "layer": "silver",
            "data_contract": "index_daily_active_pool",
            "source_table": "goldenshare_lake_meta.index_daily_active_pool",
        }
    )
