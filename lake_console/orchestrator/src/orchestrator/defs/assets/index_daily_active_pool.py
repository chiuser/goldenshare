import os
from pathlib import Path
from typing import Any, Literal

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.paths import silver_index_basic_path, silver_index_daily_active_pool_path
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeMetaPostgresResource,
    LakeRootResource,
)


LOCAL_METADATA_SOURCE_MODE = "local_metadata"
LOCAL_REPLACEMENT_SOURCE_MODE = "local_replacement"

INDEX_DAILY_ACTIVE_POOL_COLUMNS = ("ts_code", "display_name")
INDEX_DAILY_ACTIVE_POOL_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "display_name": "VARCHAR",
}


class IndexDailyActivePoolItem(dg.Config):
    ts_code: str
    display_name: str | None = None


class IndexDailyActivePoolConfig(dg.Config):
    source_mode: Literal[
        "local_metadata",
        "local_replacement",
    ] = LOCAL_METADATA_SOURCE_MODE
    items: list[IndexDailyActivePoolItem] | None = None


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


def replace_index_daily_active_pool_rows_from_config(
    *,
    lake_meta_postgres: LakeMetaPostgresResource,
    duckdb: DuckDBResource,
    lake_root: LakeRootResource,
    items: list[IndexDailyActivePoolItem] | None,
    run_id: str,
) -> dict[str, Any]:
    rows = _normalize_local_replacement_items(items)
    missing_codes = _missing_index_basic_codes(
        duckdb=duckdb,
        lake_root=lake_root,
        submitted_codes=[row["ts_code"] for row in rows],
    )
    if missing_codes:
        raise RuntimeError(
            "index_daily_active_pool local replacement contains codes missing from "
            f"silver_index_basic: {missing_codes[:20]}"
        )

    lake_meta_postgres.ensure_index_metadata_tables()
    with lake_meta_postgres.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("LOCK TABLE index_daily_active_pool IN EXCLUSIVE MODE")
            cursor.execute(
                """
                SELECT ts_code, display_name
                FROM index_daily_active_pool
                ORDER BY ts_code
                """
            )
            existing_rows = [
                {"ts_code": row[0], "display_name": row[1]}
                for row in cursor.fetchall()
            ]
            change_summary = _replace_index_daily_active_pool_rows_in_transaction(
                cursor=cursor,
                existing_rows=existing_rows,
                replacement_rows=rows,
                run_id=run_id,
            )
        connection.commit()

    return {
        "source_mode": LOCAL_REPLACEMENT_SOURCE_MODE,
        "submitted_row_count": len(rows),
        **change_summary,
    }


def _normalize_local_replacement_items(
    items: list[IndexDailyActivePoolItem] | None,
) -> list[dict[str, str | None]]:
    if not items:
        raise RuntimeError(
            "index_daily_active_pool local replacement requires a non-empty complete items list."
        )

    normalized_rows: list[dict[str, str | None]] = []
    seen_codes: set[str] = set()
    duplicate_codes: list[str] = []
    for item in items:
        ts_code = item.ts_code.strip()
        if not ts_code:
            raise RuntimeError("index_daily_active_pool local replacement contains empty ts_code.")
        if ts_code in seen_codes:
            duplicate_codes.append(ts_code)
            continue
        seen_codes.add(ts_code)
        display_name = item.display_name.strip() if item.display_name is not None else None
        normalized_rows.append(
            {
                "ts_code": ts_code,
                "display_name": display_name or None,
            }
        )

    if duplicate_codes:
        raise RuntimeError(
            "index_daily_active_pool local replacement contains duplicate ts_code values: "
            f"{sorted(set(duplicate_codes))[:20]}"
        )
    return normalized_rows


def _missing_index_basic_codes(
    *,
    duckdb: DuckDBResource,
    lake_root: LakeRootResource,
    submitted_codes: list[str],
) -> list[str]:
    index_basic_path = silver_index_basic_path(lake_root.root())
    if not index_basic_path.exists():
        raise FileNotFoundError(
            "Missing silver_index_basic file; cannot validate index_daily_active_pool replacement: "
            f"{index_basic_path}"
        )

    with duckdb.connect() as connection:
        connection.execute("CREATE TEMP TABLE submitted_codes (ts_code VARCHAR)")
        connection.executemany(
            "INSERT INTO submitted_codes VALUES (?)",
            [(code,) for code in submitted_codes],
        )
        rows = connection.execute(
            f"""
            SELECT submitted_codes.ts_code
            FROM submitted_codes
            LEFT JOIN {read_parquet(index_basic_path, hive_partitioning=False)} index_basic
              ON submitted_codes.ts_code = index_basic.ts_code
            WHERE index_basic.ts_code IS NULL
            ORDER BY submitted_codes.ts_code
            """
        ).fetchall()
    return [row[0] for row in rows]


def _replace_index_daily_active_pool_rows_in_transaction(
    *,
    cursor,
    existing_rows: list[dict[str, Any]],
    replacement_rows: list[dict[str, str | None]],
    run_id: str,
) -> dict[str, Any]:
    existing_by_code = {row["ts_code"]: row for row in existing_rows}
    replacement_by_code = {row["ts_code"]: row for row in replacement_rows}

    added_codes = sorted(set(replacement_by_code) - set(existing_by_code))
    removed_codes = sorted(set(existing_by_code) - set(replacement_by_code))
    updated_codes = sorted(
        code
        for code in set(existing_by_code) & set(replacement_by_code)
        if existing_by_code[code].get("display_name")
        != replacement_by_code[code].get("display_name")
    )
    unchanged_count = len(set(existing_by_code) & set(replacement_by_code)) - len(updated_codes)

    history_records = []
    for code in added_codes:
        history_records.append(
            (
                code,
                None,
                _json_payload(replacement_by_code[code]),
                run_id,
            )
        )
    for code in removed_codes:
        history_records.append(
            (
                code,
                _json_payload(existing_by_code[code]),
                None,
                run_id,
            )
        )
    for code in updated_codes:
        history_records.append(
            (
                code,
                _json_payload(existing_by_code[code]),
                _json_payload(replacement_by_code[code]),
                run_id,
            )
        )

    if history_records:
        cursor.executemany(
            """
            INSERT INTO index_daily_active_pool_history (
              ts_code,
              before_payload,
              after_payload,
              dagster_run_id
            )
            VALUES (%s, %s::jsonb, %s::jsonb, %s)
            """,
            history_records,
        )
        cursor.execute("DELETE FROM index_daily_active_pool")
        cursor.executemany(
            """
            INSERT INTO index_daily_active_pool (ts_code, display_name)
            VALUES (%s, %s)
            """,
            [
                (row["ts_code"], row["display_name"])
                for row in sorted(replacement_rows, key=lambda value: value["ts_code"])
            ],
        )

    return {
        "added_count": len(added_codes),
        "removed_count": len(removed_codes),
        "updated_count": len(updated_codes),
        "unchanged_count": unchanged_count,
        "history_count": len(history_records),
        "added_sample_ts_codes": added_codes[:20],
        "removed_sample_ts_codes": removed_codes[:20],
        "updated_sample_ts_codes": updated_codes[:20],
    }


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
    config: IndexDailyActivePoolConfig,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    operation_metadata: dict[str, Any] = {"source_mode": config.source_mode}
    if config.source_mode == LOCAL_REPLACEMENT_SOURCE_MODE:
        operation_metadata = replace_index_daily_active_pool_rows_from_config(
            lake_meta_postgres=lake_meta_postgres,
            duckdb=duckdb,
            lake_root=lake_root,
            items=config.items,
            run_id=context.run_id,
        )
    elif config.items is not None:
        raise RuntimeError("index_daily_active_pool local_metadata does not accept items config.")

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
            **operation_metadata,
        }
    )
