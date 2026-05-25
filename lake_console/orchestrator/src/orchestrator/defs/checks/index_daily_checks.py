from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.index_daily import (
    INDEX_DAILY_RAW_COLUMN_TYPES,
    INDEX_DAILY_SILVER_COLUMN_TYPES,
    raw_tushare_index_daily_by_code,
    silver_index_daily,
)
from orchestrator.defs.assets.index_basic import silver_index_basic
from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_RAW_COLUMNS,
    INDEX_DAILY_SILVER_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_ts_codes
from orchestrator.defs.paths import (
    raw_index_daily_by_code_path,
    silver_index_basic_path,
    silver_index_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


def _selected_partition_keys(context: dg.AssetCheckExecutionContext) -> tuple[str, ...]:
    return tuple(sorted(set(context.partition_keys)))


def _column_names(connection, path: Path, *, hive_partitioning: bool = False) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _column_types(connection, path: Path, *, hive_partitioning: bool = False) -> dict[str, str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return {row[0]: str(row[1]).upper() for row in rows}


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(count_parquet_query(path, hive_partitioning=hive_partitioning)).fetchone()[
            0
        ]
    )


def _sample_dicts(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _warn_result(passed: bool, metadata: dict[str, Any]) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        severity=dg.AssetCheckSeverity.WARN,
        metadata=metadata,
    )


def _values_table_sql(values: Sequence[str], column_name: str) -> str:
    if not values:
        return f"(SELECT CAST(NULL AS VARCHAR) AS {column_name} WHERE FALSE)"
    rows = ", ".join(f"({duckdb_string(value)})" for value in values)
    return f"(VALUES {rows}) AS registered({column_name})"


def _required_columns_result(
    *,
    connection,
    path: Path,
    required_columns: tuple[str, ...],
    expected_types: dict[str, str],
) -> dict[str, Any]:
    columns = _column_names(connection, path)
    column_types = _column_types(connection, path)
    missing_columns = [column for column in required_columns if column not in columns]
    unexpected_columns = [column for column in columns if column not in required_columns]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": column_types.get(column),
        }
        for column, expected_type in expected_types.items()
        if column in column_types and column_types[column] != expected_type
    }
    return {
        "columns": columns,
        "column_types": column_types,
        "required_columns": list(required_columns),
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "type_mismatches": type_mismatches,
    }


def evaluate_raw_index_daily_by_code_file_exists(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    del duckdb
    missing_paths = [
        str(raw_index_daily_by_code_path(lake_root_path, partition_key))
        for partition_key in partition_keys
        if not raw_index_daily_by_code_path(lake_root_path, partition_key).exists()
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths,
        metadata={
            "partition_keys": list(partition_keys),
            "missing_paths": missing_paths,
        },
    )


def evaluate_raw_index_daily_by_code_row_count_positive(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    row_counts: dict[str, int] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = raw_index_daily_by_code_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            row_counts[partition_key] = _row_count(connection, path)

    zero_row_partitions = [
        partition_key for partition_key, row_count in row_counts.items() if row_count <= 0
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not zero_row_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "row_counts": row_counts,
            "missing_paths": missing_paths,
            "zero_row_partitions": zero_row_partitions,
        },
    )


def evaluate_raw_index_daily_by_code_required_columns_and_types(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    results: dict[str, Any] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = raw_index_daily_by_code_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            results[partition_key] = _required_columns_result(
                connection=connection,
                path=path,
                required_columns=INDEX_DAILY_RAW_COLUMNS,
                expected_types=INDEX_DAILY_RAW_COLUMN_TYPES,
            )

    failed_partitions = [
        partition_key
        for partition_key, result in results.items()
        if result["missing_columns"] or result["unexpected_columns"] or result["type_mismatches"]
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "results": results,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


def evaluate_raw_index_daily_by_code_partition_code_matches(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    mismatch_counts: dict[str, int] = {}
    mismatch_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = raw_index_daily_by_code_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            mismatch_rows_sql = f"""
            SELECT ts_code, trade_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR CAST(ts_code AS VARCHAR) != {duckdb_string(partition_key)}
            """
            mismatch_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({mismatch_rows_sql}) mismatch_rows"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {mismatch_rows_sql}
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            mismatch_samples[partition_key] = _sample_dicts(["ts_code", "trade_date"], rows)

    failed_partitions = [
        partition_key for partition_key, mismatch_count in mismatch_counts.items() if mismatch_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "mismatch_counts": mismatch_counts,
            "mismatch_samples": mismatch_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


def evaluate_raw_index_daily_by_code_unique_ts_code_trade_date(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    duplicate_counts: dict[str, int] = {}
    duplicate_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = raw_index_daily_by_code_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            duplicate_keys_sql = f"""
            SELECT ts_code, trade_date, count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY ts_code, trade_date
            HAVING count(*) > 1
            """
            duplicate_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {duplicate_keys_sql}
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            duplicate_samples[partition_key] = _sample_dicts(
                ["ts_code", "trade_date", "row_count"], rows
            )

    failed_partitions = [
        partition_key for partition_key, duplicate_count in duplicate_counts.items() if duplicate_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "duplicate_counts": duplicate_counts,
            "duplicate_samples": duplicate_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


def evaluate_silver_index_daily_row_count_positive(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    row_counts: dict[str, int] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            row_counts[partition_key] = _row_count(connection, path)

    zero_row_partitions = [
        partition_key for partition_key, row_count in row_counts.items() if row_count <= 0
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not zero_row_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "row_counts": row_counts,
            "missing_paths": missing_paths,
            "zero_row_partitions": zero_row_partitions,
        },
    )


def evaluate_silver_index_daily_required_columns_and_types(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    results: dict[str, Any] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            results[partition_key] = _required_columns_result(
                connection=connection,
                path=path,
                required_columns=INDEX_DAILY_SILVER_COLUMNS,
                expected_types=INDEX_DAILY_SILVER_COLUMN_TYPES,
            )

    failed_partitions = [
        partition_key
        for partition_key, result in results.items()
        if result["missing_columns"] or result["unexpected_columns"] or result["type_mismatches"]
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "results": results,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


def evaluate_silver_index_daily_partition_date_matches(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    mismatch_counts: dict[str, int] = {}
    mismatch_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            mismatch_rows_sql = f"""
            SELECT ts_code, trade_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE trade_date IS NULL
               OR CAST(trade_date AS DATE) != DATE {duckdb_string(partition_key)}
            """
            mismatch_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({mismatch_rows_sql}) mismatch_rows"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {mismatch_rows_sql}
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            mismatch_samples[partition_key] = _sample_dicts(["ts_code", "trade_date"], rows)

    failed_partitions = [
        partition_key for partition_key, mismatch_count in mismatch_counts.items() if mismatch_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "mismatch_counts": mismatch_counts,
            "mismatch_samples": mismatch_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


def evaluate_silver_index_daily_unique_ts_code_trade_date(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    duplicate_counts: dict[str, int] = {}
    duplicate_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            duplicate_keys_sql = f"""
            SELECT ts_code, trade_date, count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY ts_code, trade_date
            HAVING count(*) > 1
            """
            duplicate_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {duplicate_keys_sql}
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            duplicate_samples[partition_key] = _sample_dicts(
                ["ts_code", "trade_date", "row_count"], rows
            )

    failed_partitions = [
        partition_key for partition_key, duplicate_count in duplicate_counts.items() if duplicate_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "duplicate_counts": duplicate_counts,
            "duplicate_samples": duplicate_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


def evaluate_silver_index_daily_conflicting_duplicate_absent(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    conflict_counts: dict[str, int] = {}
    conflict_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            conflict_counts[partition_key] = int(
                connection.execute(
                    f"""
                    SELECT count(*) AS conflict_key_count
                    FROM (
                      SELECT ts_code, trade_date
                      FROM {read_parquet(path, hive_partitioning=False)}
                      GROUP BY ts_code, trade_date
                      HAVING count(*) > 1
                    ) conflict_keys
                    """
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT ts_code, trade_date, count(*) AS version_count
                FROM {read_parquet(path, hive_partitioning=False)}
                GROUP BY ts_code, trade_date
                HAVING count(*) > 1
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            conflict_samples[partition_key] = _sample_dicts(
                ["ts_code", "trade_date", "version_count"],
                rows,
            )

    failed_partitions = [
        partition_key for partition_key, conflict_count in conflict_counts.items() if conflict_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "conflict_counts": conflict_counts,
            "conflict_samples": conflict_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


def evaluate_silver_index_daily_price_sanity(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    invalid_counts: dict[str, int] = {}
    invalid_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            invalid_rows_sql = f"""
            SELECT ts_code, trade_date, open, high, low, close, pre_close
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE open < 0
               OR high < 0
               OR low < 0
               OR close < 0
               OR pre_close < 0
               OR high < low
               OR open > high
               OR open < low
               OR close > high
               OR close < low
            """
            invalid_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({invalid_rows_sql}) invalid_rows"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {invalid_rows_sql}
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            invalid_samples[partition_key] = _sample_dicts(
                ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close"],
                rows,
            )

    failed_partitions = [
        partition_key for partition_key, invalid_count in invalid_counts.items() if invalid_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "partition_keys": list(partition_keys),
            "invalid_counts": invalid_counts,
            "invalid_samples": invalid_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


def evaluate_silver_index_daily_registered_code_coverage(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
    registered_index_codes: Sequence[str],
) -> dg.AssetCheckResult:
    index_basic_path = silver_index_basic_path(lake_root_path)
    if not registered_index_codes:
        return _warn_result(
            False,
            {
                "registered_code_count": 0,
                "missing_registered_codes": True,
            },
        )
    if not index_basic_path.exists():
        return _warn_result(
            False,
            {
                "index_basic_path": str(index_basic_path),
                "missing_file": True,
            },
        )

    registered_codes = tuple(sorted(set(registered_index_codes)))
    registered_codes_sql = _values_table_sql(registered_codes, "ts_code")
    coverage_results: dict[str, Any] = {}
    missing_paths = []
    with duckdb.connect() as connection:
        registered_code_count = len(registered_codes)
        for partition_key in partition_keys:
            silver_path = silver_index_daily_path(lake_root_path, partition_key)
            if not silver_path.exists():
                missing_paths.append(str(silver_path))
                continue
            effective_codes_sql = f"""
            SELECT registered.ts_code
            FROM {registered_codes_sql}
            INNER JOIN {read_parquet(index_basic_path, hive_partitioning=False)} basic
              ON registered.ts_code = basic.ts_code
            WHERE (basic.list_date IS NULL OR basic.list_date <= DATE {duckdb_string(partition_key)})
              AND (basic.exp_date IS NULL OR basic.exp_date > DATE {duckdb_string(partition_key)})
            """
            missing_codes_sql = f"""
            SELECT effective.ts_code
            FROM ({effective_codes_sql}) effective
            LEFT JOIN {read_parquet(silver_path, hive_partitioning=False)} daily
              ON effective.ts_code = daily.ts_code
            WHERE daily.ts_code IS NULL
            """
            extra_codes_sql = f"""
            SELECT daily.ts_code
            FROM {read_parquet(silver_path, hive_partitioning=False)} daily
            LEFT JOIN ({effective_codes_sql}) effective
              ON daily.ts_code = effective.ts_code
            WHERE effective.ts_code IS NULL
            """
            effective_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({effective_codes_sql}) effective_codes"
                ).fetchone()[0]
            )
            missing_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({missing_codes_sql}) missing_codes"
                ).fetchone()[0]
            )
            extra_count = int(
                connection.execute(f"SELECT count(*) FROM ({extra_codes_sql}) extra_codes").fetchone()[
                    0
                ]
            )
            silver_row_count = _row_count(connection, silver_path)
            missing_rows = connection.execute(
                f"""
                {missing_codes_sql}
                ORDER BY ts_code
                LIMIT 20
                """
            ).fetchall()
            extra_rows = connection.execute(
                f"""
                {extra_codes_sql}
                ORDER BY ts_code
                LIMIT 20
                """
            ).fetchall()
            coverage_results[partition_key] = {
                "registered_code_count": registered_code_count,
                "effective_code_count": effective_count,
                "silver_row_count": silver_row_count,
                "missing_registered_count": missing_count,
                "extra_count": extra_count,
                "coverage_rate": (
                    round((effective_count - missing_count) * 100.0 / effective_count, 4)
                    if effective_count
                    else 0.0
                ),
                "missing_registered_samples": [row[0] for row in missing_rows],
                "extra_samples": [row[0] for row in extra_rows],
            }

    passed = not missing_paths and all(
        result["missing_registered_count"] == 0 and result["extra_count"] == 0
        for result in coverage_results.values()
    )
    return _warn_result(
        passed,
        {
            "partition_keys": list(partition_keys),
            "index_basic_path": str(index_basic_path),
            "registered_code_count": len(registered_codes),
            "coverage_results": coverage_results,
            "missing_paths": missing_paths,
        },
    )


@dg.asset_check(asset=raw_tushare_index_daily_by_code, blocking=True)
def raw_index_daily_by_code_file_exists(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_raw_index_daily_by_code_file_exists(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=raw_tushare_index_daily_by_code, blocking=True)
def raw_index_daily_by_code_row_count_positive(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_raw_index_daily_by_code_row_count_positive(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=raw_tushare_index_daily_by_code, blocking=True)
def raw_index_daily_by_code_required_columns_and_types(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_raw_index_daily_by_code_required_columns_and_types(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=raw_tushare_index_daily_by_code, blocking=True)
def raw_index_daily_by_code_partition_code_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_raw_index_daily_by_code_partition_code_matches(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=raw_tushare_index_daily_by_code, blocking=True)
def raw_index_daily_by_code_unique_ts_code_trade_date(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_raw_index_daily_by_code_unique_ts_code_trade_date(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=silver_index_daily, blocking=True)
def silver_index_daily_row_count_positive(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_silver_index_daily_row_count_positive(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=silver_index_daily, blocking=True)
def silver_index_daily_required_columns_and_types(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_silver_index_daily_required_columns_and_types(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=silver_index_daily, blocking=True)
def silver_index_daily_partition_date_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_silver_index_daily_partition_date_matches(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=silver_index_daily, blocking=True)
def silver_index_daily_unique_ts_code_trade_date(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_silver_index_daily_unique_ts_code_trade_date(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=silver_index_daily, blocking=True)
def silver_index_daily_conflicting_duplicate_absent(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_silver_index_daily_conflicting_duplicate_absent(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=silver_index_daily, blocking=True)
def silver_index_daily_price_sanity(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_silver_index_daily_price_sanity(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(
    asset=silver_index_daily,
    additional_deps=[silver_index_basic],
    blocking=False,
)
def silver_index_daily_registered_code_coverage(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    registered_index_codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )
    return evaluate_silver_index_daily_registered_code_coverage(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
        registered_index_codes,
    )
