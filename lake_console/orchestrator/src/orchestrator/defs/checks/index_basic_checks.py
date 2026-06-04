from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.index_basic import (
    raw_tushare_index_basic,
    silver_index_basic,
)
from orchestrator.defs.duckdb_sql import (
    INDEX_BASIC_RAW_COLUMNS,
    INDEX_BASIC_SILVER_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import raw_index_basic_path, silver_index_basic_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_INDEX_BASIC_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.metadata import READY_FOR_TRADE_DATE_METADATA_KEY


INDEX_BASIC_SILVER_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_INDEX_BASIC_SCHEMA
}


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return [row[0] for row in rows]


def _column_types(connection, path: Path) -> dict[str, str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return {row[0]: str(row[1]).upper() for row in rows}


def _sample_dicts(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
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
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            extra_metadata={
                "file_path": str(path),
                "missing_file": True,
            },
        ),
    )


def _latest_ready_for_trade_date(instance: dg.DagsterInstance) -> str | None:
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=dg.AssetKey("silver_index_basic")),
        limit=1,
    ).records
    if not records:
        return None

    materialization = records[0].asset_materialization
    if materialization is None:
        return None
    metadata_value = materialization.metadata.get(READY_FOR_TRADE_DATE_METADATA_KEY)
    if metadata_value is None:
        return None
    value = getattr(metadata_value, "value", metadata_value)
    return str(value) if value else None


@dg.asset_check(asset=raw_tushare_index_basic, blocking=True)
def raw_index_basic_file_exists(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            extra_metadata={
                "file_path": str(path),
                "exists": path.exists(),
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_index_basic, blocking=True)
def raw_index_basic_row_count_positive(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = int(
            connection.execute(
                count_parquet_query(path, hive_partitioning=False)
            ).fetchone()[0]
        )

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "checked_row_count": row_count,
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_index_basic, blocking=True)
def raw_index_basic_required_columns(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path)

    missing_columns = [
        column for column in INDEX_BASIC_RAW_COLUMNS if column not in columns
    ]
    unexpected_columns = [
        column for column in columns if column not in INDEX_BASIC_RAW_COLUMNS
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns and not unexpected_columns,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "file_path": str(path),
                "observed_columns": columns,
                "required_columns": list(INDEX_BASIC_RAW_COLUMNS),
                "missing_columns": missing_columns,
                "unexpected_columns": unexpected_columns,
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_index_basic, blocking=True)
def raw_index_basic_unique_ts_code(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    duplicate_keys_sql = f"""
    SELECT ts_code, count(*) AS row_count
    FROM {read_parquet(path, hive_partitioning=False)}
    WHERE ts_code IS NOT NULL AND trim(ts_code) != ''
    GROUP BY ts_code
    HAVING count(*) > 1
    """
    with connect_configured_duckdb() as connection:
        missing_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS missing_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE ts_code IS NULL OR trim(ts_code) = ''
                """
            ).fetchone()[0]
        )
        duplicate_key_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
            ).fetchone()[0]
        )
        duplicate_rows = connection.execute(
            f"""
            {duplicate_keys_sql}
            ORDER BY ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=missing_count == 0 and duplicate_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "file_path": str(path),
                "missing_ts_code_count": missing_count,
                "duplicate_key_count": duplicate_key_count,
                "duplicate_sample_keys": _sample_dicts(
                    ["ts_code", "row_count"], duplicate_rows
                ),
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_index_basic, blocking=True)
def raw_index_basic_date_strings_parseable(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    invalid_date_rows_sql = f"""
    SELECT ts_code, 'base_date' AS field_name, base_date AS field_value
    FROM {read_parquet(path, hive_partitioning=False)}
    WHERE base_date IS NOT NULL
      AND trim(CAST(base_date AS VARCHAR)) != ''
      AND try_strptime(trim(CAST(base_date AS VARCHAR)), '%Y%m%d') IS NULL
    UNION ALL
    SELECT ts_code, 'list_date' AS field_name, list_date AS field_value
    FROM {read_parquet(path, hive_partitioning=False)}
    WHERE list_date IS NOT NULL
      AND trim(CAST(list_date AS VARCHAR)) != ''
      AND try_strptime(trim(CAST(list_date AS VARCHAR)), '%Y%m%d') IS NULL
    UNION ALL
    SELECT ts_code, 'exp_date' AS field_name, exp_date AS field_value
    FROM {read_parquet(path, hive_partitioning=False)}
    WHERE exp_date IS NOT NULL
      AND trim(CAST(exp_date AS VARCHAR)) != ''
      AND try_strptime(trim(CAST(exp_date AS VARCHAR)), '%Y%m%d') IS NULL
    """
    with connect_configured_duckdb() as connection:
        invalid_date_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({invalid_date_rows_sql}) invalid_dates"
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            {invalid_date_rows_sql}
            ORDER BY ts_code, field_name
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=invalid_date_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.REFERENTIAL_INTEGRITY,
            extra_metadata={
                "file_path": str(path),
                "invalid_date_count": invalid_date_count,
                "invalid_date_sample_rows": _sample_dicts(
                    ["ts_code", "field_name", "field_value"], rows
                ),
            },
        ),
    )


@dg.asset_check(asset=silver_index_basic, blocking=True)
def silver_index_basic_file_exists(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            extra_metadata={
                "file_path": str(path),
                "exists": path.exists(),
            },
        ),
    )


@dg.asset_check(asset=silver_index_basic, blocking=True)
def silver_index_basic_required_columns_and_types(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path)
        column_types = _column_types(connection, path)

    missing_columns = [
        column for column in INDEX_BASIC_SILVER_COLUMNS if column not in columns
    ]
    unexpected_columns = [
        column for column in columns if column not in INDEX_BASIC_SILVER_COLUMNS
    ]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": column_types.get(column),
        }
        for column, expected_type in INDEX_BASIC_SILVER_COLUMN_TYPES.items()
        if column in column_types and column_types[column] != expected_type
    }
    return dg.AssetCheckResult(
        passed=not missing_columns and not unexpected_columns and not type_mismatches,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "file_path": str(path),
                "observed_columns": columns,
                "column_types": column_types,
                "required_columns": list(INDEX_BASIC_SILVER_COLUMNS),
                "missing_columns": missing_columns,
                "unexpected_columns": unexpected_columns,
                "type_mismatches": type_mismatches,
            },
        ),
    )


@dg.asset_check(asset=silver_index_basic, blocking=True)
def silver_index_basic_row_count_positive(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = int(
            connection.execute(
                count_parquet_query(path, hive_partitioning=False)
            ).fetchone()[0]
        )

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "checked_row_count": row_count,
            },
        ),
    )


@dg.asset_check(asset=silver_index_basic, blocking=True)
def silver_index_basic_unique_ts_code(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    duplicate_keys_sql = f"""
    SELECT ts_code, count(*) AS row_count
    FROM {read_parquet(path, hive_partitioning=False)}
    WHERE ts_code IS NOT NULL AND trim(ts_code) != ''
    GROUP BY ts_code
    HAVING count(*) > 1
    """
    with connect_configured_duckdb() as connection:
        missing_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS missing_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE ts_code IS NULL OR trim(ts_code) = ''
                """
            ).fetchone()[0]
        )
        duplicate_key_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
            ).fetchone()[0]
        )
        duplicate_rows = connection.execute(
            f"""
            {duplicate_keys_sql}
            ORDER BY ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=missing_count == 0 and duplicate_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "file_path": str(path),
                "missing_ts_code_count": missing_count,
                "duplicate_key_count": duplicate_key_count,
                "duplicate_sample_keys": _sample_dicts(
                    ["ts_code", "row_count"], duplicate_rows
                ),
            },
        ),
    )


@dg.asset_check(asset=silver_index_basic, blocking=True)
def silver_index_basic_required_fields_non_null(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    required_non_null_columns = ("ts_code", "name", "market")
    with connect_configured_duckdb() as connection:
        null_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS null_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE ts_code IS NULL
                   OR trim(ts_code) = ''
                   OR name IS NULL
                   OR trim(name) = ''
                   OR market IS NULL
                   OR trim(market) = ''
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT ts_code, name, market
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR trim(ts_code) = ''
               OR name IS NULL
               OR trim(name) = ''
               OR market IS NULL
               OR trim(market) = ''
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=null_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "required_non_null_columns": list(required_non_null_columns),
                "null_row_count": null_count,
                "null_sample_rows": _sample_dicts(["ts_code", "name", "market"], rows),
            },
        ),
    )


@dg.asset_check(asset=silver_index_basic, blocking=True)
def silver_index_basic_no_terminated_indexes(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_index_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)

    ready_for_trade_date = _latest_ready_for_trade_date(context.instance)
    if not ready_for_trade_date:
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                extra_metadata={
                    "file_path": str(path),
                    "missing_ready_for_trade_date_metadata": True,
                },
            ),
        )

    with connect_configured_duckdb() as connection:
        ready_date = f"DATE {duckdb_string(ready_for_trade_date)}"
        terminated_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS terminated_count
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE exp_date IS NOT NULL
                  AND exp_date <= {ready_date}
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT ts_code, name, exp_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exp_date IS NOT NULL
              AND exp_date <= {ready_date}
            ORDER BY exp_date, ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=terminated_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(path),
                "ready_for_trade_date": ready_for_trade_date,
                "terminated_count": terminated_count,
                "terminated_sample_rows": _sample_dicts(
                    ["ts_code", "name", "exp_date"], rows
                ),
            },
        ),
    )
