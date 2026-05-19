import os
from pathlib import Path

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    silver_trade_calendar_select,
)
from orchestrator.defs.paths import raw_trade_calendar_path, silver_trade_calendar_path
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


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


@dg.asset(
    name="raw_tushare_trade_calendar",
    group_name="calendar",
    description="Tushare trade_cal raw file registered under the new raw lake path.",
)
def raw_tushare_trade_calendar(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    path = raw_trade_calendar_path(lake_root.root())
    if not path.exists():
        raise FileNotFoundError(f"Missing raw trade calendar file: {path}")

    with duckdb.connect() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)
        row_count = _row_count(connection, path, hive_partitioning=False)

    return dg.MaterializeResult(
        metadata={
            "path": str(path),
            "row_count": row_count,
            "columns": columns,
            "layer": "raw",
            "source_api": "trade_cal",
            "data_contract": "source_mirror",
            "raw_contract": "cal_date/pretrade_date YYYYMMDD string, is_open 0/1 integer",
        }
    )


@dg.asset(
    name="silver_trade_calendar",
    deps=["raw_tushare_trade_calendar"],
    group_name="calendar",
    description="Standardized A-share trading calendar derived from Tushare trade_cal raw data.",
)
def silver_trade_calendar(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    raw_path = raw_trade_calendar_path(lake_root.root())
    target_path = silver_trade_calendar_path(lake_root.root())
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw trade calendar file: {raw_path}")

    with duckdb.connect() as connection:
        _replace_parquet_from_query(
            connection,
            silver_trade_calendar_select(raw_path),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)

    return dg.MaterializeResult(
        metadata={
            "path": str(target_path),
            "row_count": row_count,
            "columns": columns,
            "layer": "silver",
            "data_contract": "standardized_trade_calendar",
        }
    )
