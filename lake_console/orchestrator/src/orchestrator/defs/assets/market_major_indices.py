import os
from pathlib import Path
from typing import Any, Literal

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
)
from orchestrator.defs.paths import gold_market_major_indices_path
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeMetaPostgresResource,
    LakeRootResource,
    ProdStrategyConfigFileResource,
)


LOCAL_METADATA_SOURCE_MODE = "local_metadata"
PROD_INITIALIZATION_SOURCE_MODE = "prod_initialization"

MARKET_MAJOR_INDICES_COLUMNS = ("rank", "ts_code", "display_name")
MARKET_MAJOR_INDICES_COLUMN_TYPES = {
    "rank": "INTEGER",
    "ts_code": "VARCHAR",
    "display_name": "VARCHAR",
}


class MarketMajorIndicesConfig(dg.Config):
    source_mode: Literal["local_metadata", "prod_initialization"] = LOCAL_METADATA_SOURCE_MODE


def load_market_major_indices_rows(
    lake_meta_postgres: LakeMetaPostgresResource,
) -> list[dict[str, Any]]:
    lake_meta_postgres.ensure_index_metadata_tables()
    with lake_meta_postgres.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rank, ts_code, display_name
                FROM market_major_indices
                ORDER BY rank
                """
            )
            rows = cursor.fetchall()
    return [
        {
            "rank": row[0],
            "ts_code": row[1],
            "display_name": row[2],
        }
        for row in rows
    ]


def initialize_market_major_indices_from_prod(
    *,
    lake_meta_postgres: LakeMetaPostgresResource,
    prod_strategy_config_file: ProdStrategyConfigFileResource,
    run_id: str,
) -> dict[str, Any]:
    lake_meta_postgres.ensure_index_metadata_tables()
    _ensure_market_major_indices_is_empty(lake_meta_postgres)
    strategy_config = prod_strategy_config_file.read_major_indices_definition()
    rows = _parse_market_major_indices_rows(strategy_config.payload)
    _replace_market_major_indices_rows(
        lake_meta_postgres=lake_meta_postgres,
        rows=rows,
        run_id=run_id,
    )
    return {
        "source_mode": PROD_INITIALIZATION_SOURCE_MODE,
        "remote_source": strategy_config.metadata["remote_source"],
        "source_content_sha256": strategy_config.metadata["content_sha256"],
        "initialized_row_count": len(rows),
        "history_count": 1,
    }


def _ensure_market_major_indices_is_empty(
    lake_meta_postgres: LakeMetaPostgresResource,
) -> None:
    with lake_meta_postgres.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM market_major_indices")
            row_count = int(cursor.fetchone()[0])
    if row_count > 0:
        raise RuntimeError(
            "market_major_indices already has local rows; initialization is one-time only. "
            "Use market_major_indices_update_job for local maintenance."
        )


def _parse_market_major_indices_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("moduleKey") != "majorIndices":
        raise RuntimeError("Prod major indices strategy config moduleKey is not majorIndices.")
    if payload.get("market") != "CN_A":
        raise RuntimeError("Prod major indices strategy config market is not CN_A.")

    index_codes = payload.get("payload", {}).get("indexCodes")
    if not isinstance(index_codes, list):
        raise RuntimeError("Prod major indices strategy config payload.indexCodes must be a list.")

    codes = [str(item).strip() for item in index_codes]
    if len(codes) != 10:
        raise RuntimeError("Prod major indices strategy config must contain exactly 10 index codes.")
    if any(not code for code in codes):
        raise RuntimeError("Prod major indices strategy config contains empty index code.")
    if len(set(codes)) != len(codes):
        raise RuntimeError("Prod major indices strategy config contains duplicate index codes.")

    return [
        {
            "rank": index + 1,
            "ts_code": code,
            "display_name": None,
        }
        for index, code in enumerate(codes)
    ]


def _replace_market_major_indices_rows(
    *,
    lake_meta_postgres: LakeMetaPostgresResource,
    rows: list[dict[str, Any]],
    run_id: str,
) -> None:
    with lake_meta_postgres.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("LOCK TABLE market_major_indices IN EXCLUSIVE MODE")
            cursor.execute("SELECT count(*) FROM market_major_indices")
            existing_row_count = int(cursor.fetchone()[0])
            if existing_row_count > 0:
                raise RuntimeError(
                    "market_major_indices changed before initialization completed; "
                    "initialization aborted."
                )

            cursor.executemany(
                """
                INSERT INTO market_major_indices (rank, ts_code, display_name)
                VALUES (%s, %s, %s)
                """,
                [(row["rank"], row["ts_code"], row["display_name"]) for row in rows],
            )
            cursor.execute(
                """
                INSERT INTO market_major_indices_change_history (
                  before_payload,
                  after_payload,
                  dagster_run_id
                )
                VALUES (NULL, %s::jsonb, %s)
                """,
                (
                    _json_payload({"items": rows}),
                    run_id,
                ),
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
            f"{_quote_identifier(column)} {MARKET_MAJOR_INDICES_COLUMN_TYPES[column]}"
            for column in MARKET_MAJOR_INDICES_COLUMNS
        )
        connection.execute(f"CREATE TEMP TABLE major_indices_rows ({column_defs})")
        placeholders = ", ".join("?" for _ in MARKET_MAJOR_INDICES_COLUMNS)
        values = [[row.get(column) for column in MARKET_MAJOR_INDICES_COLUMNS] for row in rows]
        connection.executemany(f"INSERT INTO major_indices_rows VALUES ({placeholders})", values)
        select_sql = ", ".join(
            f"CAST({_quote_identifier(column)} AS {MARKET_MAJOR_INDICES_COLUMN_TYPES[column]}) "
            f"AS {_quote_identifier(column)}"
            for column in MARKET_MAJOR_INDICES_COLUMNS
        )
        connection.execute(
            copy_query_to_parquet(f"SELECT {select_sql} FROM major_indices_rows", pending_parquet_path)
        )

    os.replace(pending_parquet_path, target_path)


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) + chr(34))}"'


@dg.asset(
    name="gold_market_major_indices",
    group_name="market",
    description="首页主要指数名单，定义展示的指数和顺序。",
)
def gold_market_major_indices(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    lake_meta_postgres: LakeMetaPostgresResource,
    prod_strategy_config_file: ProdStrategyConfigFileResource,
    config: MarketMajorIndicesConfig,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    initialization_metadata: dict[str, Any] = {"source_mode": config.source_mode}
    if config.source_mode == PROD_INITIALIZATION_SOURCE_MODE:
        initialization_metadata = initialize_market_major_indices_from_prod(
            lake_meta_postgres=lake_meta_postgres,
            prod_strategy_config_file=prod_strategy_config_file,
            run_id=context.run_id,
        )

    rows = load_market_major_indices_rows(lake_meta_postgres)
    if not rows:
        raise RuntimeError(
            "market_major_indices is empty; initialize or maintain local metadata before "
            "materializing gold_market_major_indices."
        )

    target_path = gold_market_major_indices_path(lake_root.root())
    _replace_rows_to_parquet(duckdb, rows, target_path)

    with duckdb.connect() as connection:
        columns = _column_names(connection, target_path)
        row_count = _row_count(connection, target_path)

    return dg.MaterializeResult(
        metadata={
            "path": str(target_path),
            "row_count": row_count,
            "columns": columns,
            "layer": "gold",
            "data_contract": "market_major_indices",
            "source_table": "goldenshare_lake_meta.market_major_indices",
            **initialization_metadata,
        }
    )
