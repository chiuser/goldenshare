from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.index_basic import silver_index_basic
from orchestrator.defs.assets.market_major_indices import (
    MARKET_MAJOR_INDICES_DAILY_COLUMNS,
    MARKET_MAJOR_INDICES_DAILY_COLUMN_TYPES,
    gold_market_major_indices_daily,
)
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_ts_codes
from orchestrator.defs.paths import (
    gold_market_major_indices_daily_path,
    silver_index_basic_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.seeds.market.major_indices import (
    EXPECTED_MAJOR_INDICES_COUNT,
    MajorIndexSeedRow,
    active_major_indices_seed_rows,
    load_major_indices_seed,
)


def _selected_partition_keys(context: dg.AssetCheckExecutionContext) -> tuple[str, ...]:
    return tuple(sorted(set(context.partition_keys)))


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


def _row_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]
    )


def _sample_dicts(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            if hasattr(value, "isoformat"):
                sample[column] = value.isoformat()
            elif isinstance(value, Decimal):
                sample[column] = float(value)
            else:
                sample[column] = value
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


def _nullable_duckdb_string(value: str | None) -> str:
    return "NULL::VARCHAR" if value is None else duckdb_string(value)


def _daily_paths(
    lake_root_path: Path, partition_keys: tuple[str, ...]
) -> dict[str, Path]:
    return {
        partition_key: gold_market_major_indices_daily_path(
            lake_root_path, partition_key
        )
        for partition_key in partition_keys
    }


def _seed_rows_metadata() -> dict[str, Any]:
    rows = load_major_indices_seed()
    return {
        "seed_row_count": len(rows),
        "seed_codes": [row.ts_code for row in rows],
        "seed_samples": [
            {
                "rank": row.rank,
                "ts_code": row.ts_code,
                "display_name": row.display_name,
                "effective_start_date": row.effective_start_date.isoformat(),
                "effective_end_date": row.effective_end_date.isoformat()
                if row.effective_end_date
                else None,
            }
            for row in rows[:EXPECTED_MAJOR_INDICES_COUNT]
        ],
    }


def _seed_values_sql(seed_rows: Sequence[MajorIndexSeedRow]) -> str:
    values_sql = ", ".join(
        f"({row.rank}, {duckdb_string(row.ts_code)}, {_nullable_duckdb_string(row.display_name)})"
        for row in seed_rows
    )
    return f"(VALUES {values_sql}) AS seed(rank, ts_code, display_name)"


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_file_exists(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    paths = _daily_paths(lake_root.root(), _selected_partition_keys(context))
    missing_paths = [str(path) for path in paths.values() if not path.exists()]
    return dg.AssetCheckResult(
        passed=not missing_paths,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            extra_metadata={
                "input_file_paths": {
                    partition_key: str(path) for partition_key, path in paths.items()
                },
                "missing_file_paths": missing_paths,
            },
        ),
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_required_columns_and_types(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    paths = _daily_paths(lake_root.root(), _selected_partition_keys(context))
    missing_paths = []
    results: dict[str, Any] = {}

    with connect_configured_duckdb() as connection:
        for partition_key, path in paths.items():
            if not path.exists():
                missing_paths.append(str(path))
                continue
            columns = _column_names(connection, path)
            column_types = _column_types(connection, path)
            missing_columns = [
                column
                for column in MARKET_MAJOR_INDICES_DAILY_COLUMNS
                if column not in columns
            ]
            unexpected_columns = [
                column
                for column in columns
                if column not in MARKET_MAJOR_INDICES_DAILY_COLUMNS
            ]
            type_mismatches = {
                column: {
                    "expected": expected_type,
                    "actual": column_types.get(column),
                }
                for column, expected_type in MARKET_MAJOR_INDICES_DAILY_COLUMN_TYPES.items()
                if column in column_types and column_types[column] != expected_type
            }
            results[partition_key] = {
                "observed_columns": columns,
                "column_types": column_types,
                "missing_columns": missing_columns,
                "unexpected_columns": unexpected_columns,
                "type_mismatches": type_mismatches,
            }

    failed_partitions = [
        partition_key
        for partition_key, result in results.items()
        if result["missing_columns"]
        or result["unexpected_columns"]
        or result["type_mismatches"]
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "results": results,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
                "expected_columns": list(MARKET_MAJOR_INDICES_DAILY_COLUMNS),
            },
        ),
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_partition_date_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    mismatch_counts: dict[str, int] = {}
    mismatch_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []

    with connect_configured_duckdb() as connection:
        for partition_key, path in _daily_paths(
            lake_root.root(), _selected_partition_keys(context)
        ).items():
            if not path.exists():
                missing_paths.append(str(path))
                continue
            mismatch_rows_sql = f"""
            SELECT rank, ts_code, trade_date
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
                ORDER BY rank, ts_code
                LIMIT 10
                """
            ).fetchall()
            mismatch_samples[partition_key] = _sample_dicts(
                ["rank", "ts_code", "trade_date"],
                rows,
            )

    failed_partitions = [
        partition_key
        for partition_key, mismatch_count in mismatch_counts.items()
        if mismatch_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "mismatch_counts": mismatch_counts,
                "mismatch_samples": mismatch_samples,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_row_count_matches_seed(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    expected_row_counts: dict[str, int] = {}
    row_counts: dict[str, int] = {}
    missing_paths = []

    with connect_configured_duckdb() as connection:
        for partition_key, path in _daily_paths(
            lake_root.root(), _selected_partition_keys(context)
        ).items():
            expected_row_counts[partition_key] = len(
                active_major_indices_seed_rows(partition_key)
            )
            if not path.exists():
                missing_paths.append(str(path))
                continue
            row_counts[partition_key] = _row_count(connection, path)

    failed_partitions = [
        partition_key
        for partition_key, row_count in row_counts.items()
        if row_count != expected_row_counts[partition_key]
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "row_counts": row_counts,
                "expected_row_counts": expected_row_counts,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
                **_seed_rows_metadata(),
            },
        ),
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_seed_codes_present(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    active_seed_codes: dict[str, list[str]] = {}
    missing_counts: dict[str, int] = {}
    missing_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []

    with connect_configured_duckdb() as connection:
        for partition_key, path in _daily_paths(
            lake_root.root(), _selected_partition_keys(context)
        ).items():
            active_seed_rows = active_major_indices_seed_rows(partition_key)
            active_seed_codes[partition_key] = [row.ts_code for row in active_seed_rows]
            if not path.exists():
                missing_paths.append(str(path))
                continue
            if not active_seed_rows:
                missing_counts[partition_key] = 0
                missing_samples[partition_key] = []
                continue
            seed_sql = _seed_values_sql(active_seed_rows)
            missing_sql = f"""
            SELECT seed.rank, seed.ts_code, seed.display_name
            FROM {seed_sql}
            LEFT JOIN {read_parquet(path, hive_partitioning=False)} daily
              ON seed.ts_code = daily.ts_code
             AND daily.trade_date = DATE {duckdb_string(partition_key)}
            WHERE daily.ts_code IS NULL
            """
            missing_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({missing_sql}) missing_codes"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {missing_sql}
                ORDER BY rank, ts_code
                LIMIT 20
                """
            ).fetchall()
            missing_samples[partition_key] = _sample_dicts(
                ["rank", "ts_code", "display_name"],
                rows,
            )

    failed_partitions = [
        partition_key
        for partition_key, missing_count in missing_counts.items()
        if missing_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "active_seed_codes": active_seed_codes,
                "missing_counts": missing_counts,
                "missing_samples": missing_samples,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_unique_ts_code(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    duplicate_counts: dict[str, int] = {}
    duplicate_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []

    with connect_configured_duckdb() as connection:
        for partition_key, path in _daily_paths(
            lake_root.root(), _selected_partition_keys(context)
        ).items():
            if not path.exists():
                missing_paths.append(str(path))
                continue
            duplicate_sql = f"""
            SELECT ts_code, count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY ts_code
            HAVING count(*) > 1
            """
            duplicate_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({duplicate_sql}) duplicate_keys"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {duplicate_sql}
                ORDER BY ts_code
                LIMIT 10
                """
            ).fetchall()
            duplicate_samples[partition_key] = _sample_dicts(
                ["ts_code", "row_count"], rows
            )

    failed_partitions = [
        partition_key
        for partition_key, duplicate_count in duplicate_counts.items()
        if duplicate_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "duplicate_counts": duplicate_counts,
                "duplicate_samples": duplicate_samples,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_rank_matches_active_seed_order(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    results: dict[str, Any] = {}
    missing_seed_rows: dict[str, list[dict[str, Any]]] = {}
    unexpected_rows: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []

    with connect_configured_duckdb() as connection:
        for partition_key, path in _daily_paths(
            lake_root.root(), _selected_partition_keys(context)
        ).items():
            active_seed_rows = active_major_indices_seed_rows(partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            if active_seed_rows:
                seed_sql = _seed_values_sql(active_seed_rows)
                missing_sql = f"""
                SELECT seed.rank, seed.ts_code, seed.display_name
                FROM {seed_sql}
                LEFT JOIN {read_parquet(path, hive_partitioning=False)} daily
                  ON seed.rank = daily.rank
                 AND seed.ts_code = daily.ts_code
                WHERE daily.ts_code IS NULL
                """
                unexpected_sql = f"""
                SELECT daily.rank, daily.ts_code, daily.display_name
                FROM {read_parquet(path, hive_partitioning=False)} daily
                LEFT JOIN {seed_sql}
                  ON seed.rank = daily.rank
                 AND seed.ts_code = daily.ts_code
                WHERE seed.ts_code IS NULL
                """
                missing_seed_rows[partition_key] = _sample_dicts(
                    ["rank", "ts_code", "display_name"],
                    connection.execute(
                        f"{missing_sql} ORDER BY rank, ts_code LIMIT 20"
                    ).fetchall(),
                )
                unexpected_rows[partition_key] = _sample_dicts(
                    ["rank", "ts_code", "display_name"],
                    connection.execute(
                        f"{unexpected_sql} ORDER BY rank, ts_code LIMIT 20"
                    ).fetchall(),
                )
            else:
                missing_seed_rows[partition_key] = []
                unexpected_rows[partition_key] = []

            row = connection.execute(
                f"""
                SELECT
                  count(*) AS row_count,
                  count(DISTINCT rank) AS distinct_rank_count,
                  count(DISTINCT ts_code) AS distinct_code_count,
                  count(*) FILTER (WHERE rank IS NULL) AS null_rank_count
                FROM {read_parquet(path, hive_partitioning=False)}
                """
            ).fetchone()
            results[partition_key] = {
                "checked_row_count": int(row[0]),
                "distinct_rank_count": int(row[1]),
                "distinct_code_count": int(row[2]),
                "null_rank_count": int(row[3]),
                "active_seed_ranks": [row.rank for row in active_seed_rows],
            }

    failed_partitions = [
        partition_key
        for partition_key, result in results.items()
        if not (
            result["checked_row_count"] == len(result["active_seed_ranks"])
            and result["null_rank_count"] == 0
            and result["distinct_rank_count"] == result["checked_row_count"]
            and result["distinct_code_count"] == result["checked_row_count"]
            and not missing_seed_rows.get(partition_key)
            and not unexpected_rows.get(partition_key)
        )
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "results": results,
                "missing_seed_rows": missing_seed_rows,
                "unexpected_rows": unexpected_rows,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_price_sanity(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    invalid_counts: dict[str, int] = {}
    invalid_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []

    with connect_configured_duckdb() as connection:
        for partition_key, path in _daily_paths(
            lake_root.root(), _selected_partition_keys(context)
        ).items():
            if not path.exists():
                missing_paths.append(str(path))
                continue
            invalid_rows_sql = f"""
            SELECT rank, ts_code, trade_date, open, high, low, close, pre_close
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
                ORDER BY rank, ts_code
                LIMIT 10
                """
            ).fetchall()
            invalid_samples[partition_key] = _sample_dicts(
                [
                    "rank",
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                ],
                rows,
            )

    failed_partitions = [
        partition_key
        for partition_key, invalid_count in invalid_counts.items()
        if invalid_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "invalid_counts": invalid_counts,
                "invalid_samples": invalid_samples,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


@dg.asset_check(
    asset=gold_market_major_indices_daily,
    additional_deps=[silver_index_basic],
    blocking=True,
)
def gold_market_major_indices_seed_codes_exist_in_index_basic(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    index_basic_path = silver_index_basic_path(lake_root.root())
    if not index_basic_path.exists():
        return _missing_file_result(index_basic_path)

    seed_rows = load_major_indices_seed()
    values_sql = ", ".join(
        f"({row.rank}, {duckdb_string(row.ts_code)}, {_nullable_duckdb_string(row.display_name)})"
        for row in seed_rows
    )
    seed_sql = f"(VALUES {values_sql}) AS seed(rank, ts_code, display_name)"
    missing_sql = f"""
    SELECT seed.rank, seed.ts_code, seed.display_name
    FROM {seed_sql}
    LEFT JOIN {read_parquet(index_basic_path, hive_partitioning=False)} index_basic
      ON seed.ts_code = index_basic.ts_code
    WHERE index_basic.ts_code IS NULL
    """
    with connect_configured_duckdb() as connection:
        missing_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({missing_sql}) missing_codes"
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            {missing_sql}
            ORDER BY rank, ts_code
            LIMIT 20
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=missing_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.REFERENTIAL_INTEGRITY,
            extra_metadata={
                "index_basic_file_path": str(index_basic_path),
                "missing_count": missing_count,
                "missing_sample_rows": _sample_dicts(
                    ["rank", "ts_code", "display_name"], rows
                ),
                **_seed_rows_metadata(),
            },
        ),
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_seed_codes_exist_in_registered_index_ts_codes(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    seed_rows = load_major_indices_seed()
    registered_codes = set(
        context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name)
    )
    missing_rows = [
        (row.rank, row.ts_code, row.display_name)
        for row in seed_rows
        if row.ts_code not in registered_codes
    ]
    return dg.AssetCheckResult(
        passed=not missing_rows,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "dynamic_partitions_def": cn_a_index_ts_codes.name,
                "registered_code_count": len(registered_codes),
                "missing_count": len(missing_rows),
                "missing_sample_rows": _sample_dicts(
                    ["rank", "ts_code", "display_name"],
                    missing_rows[:20],
                ),
                **_seed_rows_metadata(),
            },
        ),
    )
