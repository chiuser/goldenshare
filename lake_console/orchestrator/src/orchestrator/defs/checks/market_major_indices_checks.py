from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

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
from orchestrator.seeds.market.major_indices import (
    EXPECTED_MAJOR_INDICES_COUNT,
    load_major_indices_seed,
)


def _selected_partition_keys(context: dg.AssetCheckExecutionContext) -> tuple[str, ...]:
    return tuple(sorted(set(context.partition_keys)))


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(describe_parquet_query(path, hive_partitioning=False)).fetchall()
    return [row[0] for row in rows]


def _column_types(connection, path: Path) -> dict[str, str]:
    rows = connection.execute(describe_parquet_query(path, hive_partitioning=False)).fetchall()
    return {row[0]: str(row[1]).upper() for row in rows}


def _row_count(connection, path: Path) -> int:
    return int(
        connection.execute(count_parquet_query(path, hive_partitioning=False)).fetchone()[0]
    )


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


def _nullable_duckdb_string(value: str | None) -> str:
    return "NULL::VARCHAR" if value is None else duckdb_string(value)


def _daily_paths(lake_root_path: Path, partition_keys: tuple[str, ...]) -> dict[str, Path]:
    return {
        partition_key: gold_market_major_indices_daily_path(lake_root_path, partition_key)
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
            }
            for row in rows[:EXPECTED_MAJOR_INDICES_COUNT]
        ],
    }


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_file_exists(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    paths = _daily_paths(lake_root.root(), _selected_partition_keys(context))
    missing_paths = [str(path) for path in paths.values() if not path.exists()]
    return dg.AssetCheckResult(
        passed=not missing_paths,
        metadata={
            "paths": {partition_key: str(path) for partition_key, path in paths.items()},
            "missing_paths": missing_paths,
        },
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

    with duckdb.connect() as connection:
        for partition_key, path in paths.items():
            if not path.exists():
                missing_paths.append(str(path))
                continue
            columns = _column_names(connection, path)
            column_types = _column_types(connection, path)
            missing_columns = [
                column for column in MARKET_MAJOR_INDICES_DAILY_COLUMNS if column not in columns
            ]
            unexpected_columns = [
                column for column in columns if column not in MARKET_MAJOR_INDICES_DAILY_COLUMNS
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
                "columns": columns,
                "column_types": column_types,
                "missing_columns": missing_columns,
                "unexpected_columns": unexpected_columns,
                "type_mismatches": type_mismatches,
            }

    failed_partitions = [
        partition_key
        for partition_key, result in results.items()
        if result["missing_columns"] or result["unexpected_columns"] or result["type_mismatches"]
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "results": results,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
            "expected_columns": list(MARKET_MAJOR_INDICES_DAILY_COLUMNS),
        },
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

    with duckdb.connect() as connection:
        for partition_key, path in _daily_paths(lake_root.root(), _selected_partition_keys(context)).items():
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
        partition_key for partition_key, mismatch_count in mismatch_counts.items() if mismatch_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "mismatch_counts": mismatch_counts,
            "mismatch_samples": mismatch_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_row_count_matches_seed(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    seed_rows = load_major_indices_seed()
    expected_row_count = len(seed_rows)
    row_counts: dict[str, int] = {}
    missing_paths = []

    with duckdb.connect() as connection:
        for partition_key, path in _daily_paths(lake_root.root(), _selected_partition_keys(context)).items():
            if not path.exists():
                missing_paths.append(str(path))
                continue
            row_counts[partition_key] = _row_count(connection, path)

    failed_partitions = [
        partition_key
        for partition_key, row_count in row_counts.items()
        if row_count != expected_row_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "row_counts": row_counts,
            "expected_row_count": expected_row_count,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
            **_seed_rows_metadata(),
        },
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_seed_codes_present(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    seed_rows = load_major_indices_seed()
    seed_codes = tuple(row.ts_code for row in seed_rows)
    missing_counts: dict[str, int] = {}
    missing_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []

    values_sql = ", ".join(
        f"({row.rank}, {duckdb_string(row.ts_code)}, {_nullable_duckdb_string(row.display_name)})"
        for row in seed_rows
    )
    seed_sql = f"(VALUES {values_sql}) AS seed(rank, ts_code, display_name)"
    with duckdb.connect() as connection:
        for partition_key, path in _daily_paths(lake_root.root(), _selected_partition_keys(context)).items():
            if not path.exists():
                missing_paths.append(str(path))
                continue
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
        partition_key for partition_key, missing_count in missing_counts.items() if missing_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "seed_codes": list(seed_codes),
            "missing_counts": missing_counts,
            "missing_samples": missing_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
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

    with duckdb.connect() as connection:
        for partition_key, path in _daily_paths(lake_root.root(), _selected_partition_keys(context)).items():
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
            duplicate_samples[partition_key] = _sample_dicts(["ts_code", "row_count"], rows)

    failed_partitions = [
        partition_key for partition_key, duplicate_count in duplicate_counts.items() if duplicate_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "duplicate_counts": duplicate_counts,
            "duplicate_samples": duplicate_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_daily_rank_continuous(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    results: dict[str, Any] = {}
    missing_paths = []

    with duckdb.connect() as connection:
        for partition_key, path in _daily_paths(lake_root.root(), _selected_partition_keys(context)).items():
            if not path.exists():
                missing_paths.append(str(path))
                continue
            row = connection.execute(
                f"""
                SELECT
                  count(*) AS row_count,
                  count(DISTINCT rank) AS distinct_rank_count,
                  min(rank) AS min_rank,
                  max(rank) AS max_rank,
                  count(*) FILTER (WHERE rank IS NULL) AS null_rank_count
                FROM {read_parquet(path, hive_partitioning=False)}
                """
            ).fetchone()
            results[partition_key] = {
                "row_count": int(row[0]),
                "distinct_rank_count": int(row[1]),
                "min_rank": row[2],
                "max_rank": row[3],
                "null_rank_count": int(row[4]),
            }

    failed_partitions = [
        partition_key
        for partition_key, result in results.items()
        if not (
            result["row_count"] > 0
            and result["null_rank_count"] == 0
            and result["distinct_rank_count"] == result["row_count"]
            and result["min_rank"] == 1
            and result["max_rank"] == result["row_count"]
        )
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "results": results,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
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

    with duckdb.connect() as connection:
        for partition_key, path in _daily_paths(lake_root.root(), _selected_partition_keys(context)).items():
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
                ["rank", "ts_code", "trade_date", "open", "high", "low", "close", "pre_close"],
                rows,
            )

    failed_partitions = [
        partition_key for partition_key, invalid_count in invalid_counts.items() if invalid_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata={
            "invalid_counts": invalid_counts,
            "invalid_samples": invalid_samples,
            "missing_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
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
    with duckdb.connect() as connection:
        missing_count = int(
            connection.execute(f"SELECT count(*) FROM ({missing_sql}) missing_codes").fetchone()[0]
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
        metadata={
            "index_basic_path": str(index_basic_path),
            "missing_count": missing_count,
            "missing_sample_rows": _sample_dicts(["rank", "ts_code", "display_name"], rows),
            **_seed_rows_metadata(),
        },
    )


@dg.asset_check(asset=gold_market_major_indices_daily, blocking=True)
def gold_market_major_indices_seed_codes_exist_in_registered_index_ts_codes(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    seed_rows = load_major_indices_seed()
    registered_codes = set(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    missing_rows = [
        (row.rank, row.ts_code, row.display_name)
        for row in seed_rows
        if row.ts_code not in registered_codes
    ]
    return dg.AssetCheckResult(
        passed=not missing_rows,
        metadata={
            "dynamic_partitions_def": cn_a_index_ts_codes.name,
            "registered_code_count": len(registered_codes),
            "missing_count": len(missing_rows),
            "missing_sample_rows": _sample_dicts(
                ["rank", "ts_code", "display_name"],
                missing_rows[:20],
            ),
            **_seed_rows_metadata(),
        },
    )
