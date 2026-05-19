from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import raw_trade_calendar_path, silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


def _column_names(connection, path: Path, *, hive_partitioning: bool = False) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _sample_dicts(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _missing_file_result(path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata={
            "path": str(path),
            "missing_file": True,
        },
    )


@dg.asset_check(asset="raw_tushare_trade_calendar", blocking=True)
def raw_trade_calendar_file_exists(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    path = raw_trade_calendar_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata={
            "path": str(path),
            "exists": path.exists(),
        },
    )


@dg.asset_check(asset="raw_tushare_trade_calendar", blocking=True)
def raw_trade_calendar_required_columns(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_trade_calendar_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)

    missing_columns = [
        column for column in TRADE_CALENDAR_RAW_REQUIRED_COLUMNS if column not in columns
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata={
            "path": str(path),
            "columns": columns,
            "required_columns": list(TRADE_CALENDAR_RAW_REQUIRED_COLUMNS),
            "missing_columns": missing_columns,
        },
    )


@dg.asset_check(asset="raw_tushare_trade_calendar", blocking=True)
def raw_trade_calendar_contains_required_exchange(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_trade_calendar_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        row_count = connection.execute(
            f"""
            SELECT count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exchange = 'SSE'
            """
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata={
            "path": str(path),
            "required_exchange": "SSE",
            "row_count": int(row_count),
        },
    )


@dg.asset_check(asset="silver_trade_calendar", blocking=True)
def silver_trade_calendar_unique_exchange_trade_date(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_trade_calendar_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT exchange, trade_date, count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY exchange, trade_date
            HAVING count(*) > 1
            ORDER BY exchange, trade_date
            LIMIT 10
            """
        ).fetchall()

    duplicate_count = len(rows)
    return dg.AssetCheckResult(
        passed=duplicate_count == 0,
        metadata={
            "path": str(path),
            "duplicate_key_count": duplicate_count,
            "duplicate_sample_keys": _sample_dicts(
                ["exchange", "trade_date", "row_count"], rows
            ),
        },
    )


@dg.asset_check(asset="silver_trade_calendar", blocking=True)
def silver_trade_calendar_required_columns_non_null(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_trade_calendar_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        null_count = connection.execute(
            f"""
            SELECT count(*) AS null_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exchange IS NULL
               OR trade_date IS NULL
               OR is_open IS NULL
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT exchange, trade_date, is_open
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exchange IS NULL
               OR trade_date IS NULL
               OR is_open IS NULL
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=null_count == 0,
        metadata={
            "path": str(path),
            "null_row_count": int(null_count),
            "null_sample_rows": _sample_dicts(["exchange", "trade_date", "is_open"], rows),
        },
    )


@dg.asset_check(asset="silver_trade_calendar", blocking=True)
def silver_trade_calendar_has_open_days_in_poc_range(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_trade_calendar_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        open_day_count = connection.execute(
            f"""
            SELECT count(*) AS open_day_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exchange = 'SSE'
              AND is_open = true
              AND trade_date BETWEEN DATE '2026-04-01' AND DATE '2026-04-30'
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT exchange, trade_date, is_open
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exchange = 'SSE'
              AND is_open = true
              AND trade_date BETWEEN DATE '2026-04-01' AND DATE '2026-04-30'
            ORDER BY trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=open_day_count > 0,
        metadata={
            "path": str(path),
            "exchange": "SSE",
            "start_date": "2026-04-01",
            "end_date": "2026-04-30",
            "open_day_count": int(open_day_count),
            "sample_open_days": _sample_dicts(["exchange", "trade_date", "is_open"], rows),
        },
    )
