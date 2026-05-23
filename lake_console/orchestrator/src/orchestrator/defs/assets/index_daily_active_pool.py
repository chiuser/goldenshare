import os
from pathlib import Path
from typing import Any, Literal

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
)
from orchestrator.defs.paths import silver_index_daily_active_pool_path
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeMetaPostgresResource,
    LakeRootResource,
    ProdReadOnlyPostgresResource,
)


LOCAL_METADATA_SOURCE_MODE = "local_metadata"
PROD_INITIALIZATION_SOURCE_MODE = "prod_initialization"

INDEX_DAILY_ACTIVE_POOL_COLUMNS = ("ts_code", "display_name")
INDEX_DAILY_ACTIVE_POOL_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "display_name": "VARCHAR",
}


class IndexDailyActivePoolConfig(dg.Config):
    source_mode: Literal["local_metadata", "prod_initialization"] = LOCAL_METADATA_SOURCE_MODE


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


def initialize_index_daily_active_pool_from_prod(
    *,
    lake_meta_postgres: LakeMetaPostgresResource,
    prod_read_only_postgres: ProdReadOnlyPostgresResource,
    run_id: str,
) -> dict[str, Any]:
    lake_meta_postgres.ensure_index_metadata_tables()
    _ensure_index_daily_active_pool_is_empty(lake_meta_postgres)
    rows = _load_prod_index_daily_active_pool_rows(prod_read_only_postgres)
    _replace_index_daily_active_pool_rows(
        lake_meta_postgres=lake_meta_postgres,
        rows=rows,
        run_id=run_id,
    )
    return {
        "source_mode": PROD_INITIALIZATION_SOURCE_MODE,
        "remote_source": "prod_postgres.ops.index_series_active",
        "remote_resource": "index_daily",
        "initialized_row_count": len(rows),
        "history_count": len(rows),
    }


def _ensure_index_daily_active_pool_is_empty(
    lake_meta_postgres: LakeMetaPostgresResource,
) -> None:
    with lake_meta_postgres.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM index_daily_active_pool")
            row_count = int(cursor.fetchone()[0])
    if row_count > 0:
        raise RuntimeError(
            "index_daily_active_pool already has local rows; initialization is one-time only. "
            "Use index_daily_active_pool_update_job for local maintenance."
        )


def _load_prod_index_daily_active_pool_rows(
    prod_read_only_postgres: ProdReadOnlyPostgresResource,
) -> list[dict[str, Any]]:
    with prod_read_only_postgres.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ts_code
                FROM ops.index_series_active
                WHERE resource = 'index_daily'
                ORDER BY ts_code
                """
            )
            rows = cursor.fetchall()

    active_pool_rows = [{"ts_code": row[0], "display_name": None} for row in rows]
    _validate_index_daily_active_pool_rows(active_pool_rows)
    return active_pool_rows


def _validate_index_daily_active_pool_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError("Prod index_daily active pool returned 0 rows; initialization aborted.")

    codes = [str(row["ts_code"]).strip() for row in rows]
    if any(not code for code in codes):
        raise RuntimeError("Prod index_daily active pool contains empty ts_code.")
    duplicate_codes = sorted({code for code in codes if codes.count(code) > 1})
    if duplicate_codes:
        raise RuntimeError(
            f"Prod index_daily active pool contains duplicate ts_code values: {duplicate_codes[:10]}"
        )


def _replace_index_daily_active_pool_rows(
    *,
    lake_meta_postgres: LakeMetaPostgresResource,
    rows: list[dict[str, Any]],
    run_id: str,
) -> None:
    with lake_meta_postgres.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("LOCK TABLE index_daily_active_pool IN EXCLUSIVE MODE")
            cursor.execute("SELECT count(*) FROM index_daily_active_pool")
            existing_row_count = int(cursor.fetchone()[0])
            if existing_row_count > 0:
                raise RuntimeError(
                    "index_daily_active_pool changed before initialization completed; "
                    "initialization aborted."
                )

            cursor.executemany(
                """
                INSERT INTO index_daily_active_pool (ts_code, display_name)
                VALUES (%s, %s)
                """,
                [(row["ts_code"], row["display_name"]) for row in rows],
            )
            cursor.executemany(
                """
                INSERT INTO index_daily_active_pool_history (
                  ts_code,
                  before_payload,
                  after_payload,
                  dagster_run_id
                )
                VALUES (%s, NULL, %s::jsonb, %s)
                """,
                [
                    (
                        row["ts_code"],
                        _json_payload(
                            {
                                "ts_code": row["ts_code"],
                                "display_name": row["display_name"],
                            }
                        ),
                        run_id,
                    )
                    for row in rows
                ],
            )
        connection.commit()


def _json_payload(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=True, sort_keys=True)


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
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    lake_meta_postgres: LakeMetaPostgresResource,
    prod_read_only_postgres: ProdReadOnlyPostgresResource,
    config: IndexDailyActivePoolConfig,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    initialization_metadata: dict[str, Any] = {"source_mode": config.source_mode}
    if config.source_mode == PROD_INITIALIZATION_SOURCE_MODE:
        initialization_metadata = initialize_index_daily_active_pool_from_prod(
            lake_meta_postgres=lake_meta_postgres,
            prod_read_only_postgres=prod_read_only_postgres,
            run_id=context.run_id,
        )

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
            **initialization_metadata,
        }
    )
