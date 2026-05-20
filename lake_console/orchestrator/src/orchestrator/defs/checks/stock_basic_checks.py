from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    STOCK_BASIC_RAW_REQUIRED_COLUMNS,
    STOCK_BASIC_SILVER_REQUIRED_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import raw_stock_basic_path, silver_stock_basic_path
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


def _list_status_distribution(connection, path: Path) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT list_status, count(*) AS row_count
        FROM {read_parquet(path, hive_partitioning=False)}
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


@dg.asset_check(asset="raw_tushare_stock_basic", blocking=True)
def raw_stock_basic_file_exists(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    path = raw_stock_basic_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata={
            "path": str(path),
            "exists": path.exists(),
        },
    )


@dg.asset_check(asset="raw_tushare_stock_basic", blocking=True)
def raw_stock_basic_row_count_positive(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_stock_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata={
            "path": str(path),
            "row_count": int(row_count),
        },
    )


@dg.asset_check(asset="raw_tushare_stock_basic", blocking=True)
def raw_stock_basic_required_columns(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_stock_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)

    missing_columns = [column for column in STOCK_BASIC_RAW_REQUIRED_COLUMNS if column not in columns]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata={
            "path": str(path),
            "columns": columns,
            "required_columns": list(STOCK_BASIC_RAW_REQUIRED_COLUMNS),
            "missing_columns": missing_columns,
        },
    )


@dg.asset_check(asset="raw_tushare_stock_basic", blocking=True)
def raw_stock_basic_ts_code_present(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_stock_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        missing_count = connection.execute(
            f"""
            SELECT count(*) AS missing_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL OR trim(ts_code) = ''
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, symbol, name, list_status
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL OR trim(ts_code) = ''
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=missing_count == 0,
        metadata={
            "path": str(path),
            "missing_ts_code_count": int(missing_count),
            "missing_ts_code_sample_rows": _sample_dicts(
                ["ts_code", "symbol", "name", "list_status"], rows
            ),
        },
    )


@dg.asset_check(asset="silver_stock_basic", blocking=True)
def silver_stock_basic_unique_ts_code(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    duplicate_keys_sql = f"""
    SELECT ts_code, count(*) AS row_count
    FROM {read_parquet(path, hive_partitioning=False)}
    GROUP BY ts_code
    HAVING count(*) > 1
    """
    with duckdb.connect() as connection:
        duplicate_key_count = connection.execute(
            f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            {duplicate_keys_sql}
            ORDER BY ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=duplicate_key_count == 0,
        metadata={
            "path": str(path),
            "duplicate_key_count": int(duplicate_key_count),
            "duplicate_sample_keys": _sample_dicts(["ts_code", "row_count"], rows),
        },
    )


@dg.asset_check(asset="silver_stock_basic", blocking=True)
def silver_stock_basic_required_columns_non_null(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    required_non_null_columns = ("ts_code", "symbol", "name", "list_date")
    with duckdb.connect() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)
        missing_columns = [
            column for column in STOCK_BASIC_SILVER_REQUIRED_COLUMNS if column not in columns
        ]
        if missing_columns:
            return dg.AssetCheckResult(
                passed=False,
                metadata={
                    "path": str(path),
                    "columns": columns,
                    "required_columns": list(STOCK_BASIC_SILVER_REQUIRED_COLUMNS),
                    "missing_columns": missing_columns,
                },
            )

        null_count = connection.execute(
            f"""
            SELECT count(*) AS null_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR trim(ts_code) = ''
               OR symbol IS NULL
               OR trim(symbol) = ''
               OR name IS NULL
               OR trim(name) = ''
               OR list_date IS NULL
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, symbol, name, list_date, list_status
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR trim(ts_code) = ''
               OR symbol IS NULL
               OR trim(symbol) = ''
               OR name IS NULL
               OR trim(name) = ''
               OR list_date IS NULL
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=null_count == 0,
        metadata={
            "path": str(path),
            "required_non_null_columns": list(required_non_null_columns),
            "null_row_count": int(null_count),
            "null_sample_rows": _sample_dicts(
                ["ts_code", "symbol", "name", "list_date", "list_status"], rows
            ),
        },
    )


@dg.asset_check(asset="silver_stock_basic", blocking=True)
def silver_stock_basic_lifecycle_dates_valid(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        invalid_count = connection.execute(
            f"""
            SELECT count(*) AS invalid_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE list_date IS NOT NULL
              AND delist_date IS NOT NULL
              AND delist_date < list_date
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, list_status, list_date, delist_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE list_date IS NOT NULL
              AND delist_date IS NOT NULL
              AND delist_date < list_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=invalid_count == 0,
        metadata={
            "path": str(path),
            "invalid_lifecycle_date_count": int(invalid_count),
            "invalid_lifecycle_date_sample_rows": _sample_dicts(
                ["ts_code", "list_status", "list_date", "delist_date"], rows
            ),
        },
    )


@dg.asset_check(asset="silver_stock_basic", blocking=True)
def silver_stock_basic_has_listed_records(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with duckdb.connect() as connection:
        listed_count = connection.execute(
            f"""
            SELECT count(*) AS listed_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE list_status = 'L'
            """
        ).fetchone()[0]
        distribution = _list_status_distribution(connection, path)

    return dg.AssetCheckResult(
        passed=listed_count > 0,
        metadata={
            "path": str(path),
            "listed_count": int(listed_count),
            "list_status_distribution": distribution,
        },
    )


@dg.asset_check(asset="silver_stock_basic", blocking=True)
def silver_stock_basic_current_listed_only(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    allowed_values = duckdb_string("L")
    with duckdb.connect() as connection:
        non_listed_count = connection.execute(
            f"""
            SELECT count(*) AS non_listed_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE list_status IS NULL
               OR list_status NOT IN ({allowed_values})
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT list_status, count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE list_status IS NULL
               OR list_status NOT IN ({allowed_values})
            GROUP BY list_status
            ORDER BY list_status
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=non_listed_count == 0,
        metadata={
            "path": str(path),
            "required_list_status_values": ["L"],
            "non_listed_row_count": int(non_listed_count),
            "non_listed_sample_values": _sample_dicts(
                ["list_status", "row_count"], rows
            ),
        },
    )
