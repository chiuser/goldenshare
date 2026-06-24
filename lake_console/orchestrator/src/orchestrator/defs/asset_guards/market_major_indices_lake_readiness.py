"""Lake-fact readiness checks for market major indices sensor hot paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_SAMPLE_LIMIT,
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.assets.index_daily import INDEX_DAILY_SILVER_COLUMN_TYPES
from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_SILVER_COLUMNS,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    gold_market_major_indices_daily_path,
    raw_index_daily_path,
    silver_index_basic_path,
    silver_index_daily_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
    SILVER_INDEX_BASIC_SCHEMA,
)
from orchestrator.seeds.market.major_indices import (
    MajorIndexSeedRow,
    active_major_indices_seed_rows,
    load_major_indices_seed,
)


GOLD_MARKET_MAJOR_INDICES_LAKE_CHECK_NAMES = (
    "gold_market_major_indices_daily_file_exists",
    "gold_market_major_indices_daily_required_columns_and_types",
    "gold_market_major_indices_daily_partition_date_matches",
    "gold_market_major_indices_daily_row_count_matches_seed",
    "gold_market_major_indices_daily_seed_codes_present",
    "gold_market_major_indices_daily_unique_ts_code",
    "gold_market_major_indices_daily_rank_matches_active_seed_order",
    "gold_market_major_indices_daily_price_sanity",
    "gold_market_major_indices_seed_codes_exist_in_index_basic",
    "gold_market_major_indices_seed_codes_exist_in_registered_index_ts_codes",
)
SILVER_INDEX_DAILY_LAKE_CHECK_NAMES = (
    "silver_index_daily_conflicting_duplicate_absent",
    "silver_index_daily_partition_date_matches",
    "silver_index_daily_price_sanity",
    "silver_index_daily_registered_code_coverage",
    "silver_index_daily_required_columns_and_types",
    "silver_index_daily_row_count_positive",
    "silver_index_daily_unique_ts_code_trade_date",
)
SILVER_INDEX_BASIC_LAKE_CHECK_NAMES = (
    "silver_index_basic_file_exists",
    "silver_index_basic_required_columns_and_types",
    "silver_index_basic_row_count_positive",
    "silver_index_basic_unique_ts_code",
    "silver_index_basic_required_fields_non_null",
    "silver_index_basic_no_terminated_indexes",
)


_GOLD_REQUIRED_COLUMNS = tuple(
    column.name for column in GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA
)
_GOLD_COLUMN_TYPES = {
    column.name: column.type for column in GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA
}
_SILVER_INDEX_BASIC_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_INDEX_BASIC_SCHEMA
)
_SILVER_INDEX_BASIC_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_INDEX_BASIC_SCHEMA
}


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _read_parquet_paths(paths: Sequence[Path], *, union_by_name: bool = True) -> str:
    path_values = ", ".join(duckdb_string(path) for path in paths)
    union_clause = ", union_by_name=true" if union_by_name else ""
    return f"read_parquet([{path_values}], hive_partitioning=false{union_clause})"


def _missing_file_status(
    *,
    trade_date: str,
    check_name: str,
    file_path: Path,
    reason: str,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason=reason,
        missing_check_names=(check_name,),
        missing_file_paths=(str(file_path),),
        summary={"file_path": str(file_path)},
    )


def _failed_status(
    *,
    trade_date: str,
    reason: str,
    failed_check_names: Sequence[str],
    summary: Mapping[str, object],
    missing_file_paths: Sequence[str] = (),
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason=reason,
        failed_check_names=tuple(failed_check_names),
        missing_file_paths=tuple(missing_file_paths),
        summary=dict(summary),
    )


def _ready_status(
    *,
    trade_date: str,
    summary: Mapping[str, object],
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason="ready",
        summary=dict(summary),
    )


def _scan_error_status(
    *,
    trade_date: str,
    materialized: bool,
    error: Exception,
    file_path: Path | None = None,
) -> ContinuityDateReadiness:
    missing_paths = () if file_path is None or materialized else (str(file_path),)
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=materialized,
        checks_passed=False,
        reason="scan_error",
        failed_check_names=("lake_readiness_scan_error",),
        missing_file_paths=missing_paths,
        summary={
            "scan_error_code": type(error).__name__,
            "scan_error": str(error),
        },
    )


def _schema_failures(
    connection,
    path: Path,
    *,
    required_columns: Sequence[str],
    expected_types: Mapping[str, str],
) -> dict[str, object]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    columns = [str(row[0]) for row in rows]
    column_types = {str(row[0]): str(row[1]).upper() for row in rows}
    missing_columns = [column for column in required_columns if column not in columns]
    unexpected_columns = [
        column for column in columns if column not in set(required_columns)
    ]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": column_types.get(column),
        }
        for column, expected_type in expected_types.items()
        if column in column_types and column_types[column] != expected_type
    }
    return {
        "observed_columns": columns,
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "type_mismatches": type_mismatches,
    }


def _seed_values_sql(
    seed_rows: Sequence[MajorIndexSeedRow],
    *,
    include_partition: str | None = None,
) -> str:
    if include_partition is None:
        values_sql = ", ".join(
            f"({row.rank}, {duckdb_string(row.ts_code)}, {duckdb_string(row.display_name)})"
            for row in seed_rows
        )
        return f"(VALUES {values_sql}) AS seed(rank, ts_code, display_name)"

    values_sql = ", ".join(
        f"({duckdb_string(include_partition)}, {row.rank}, {duckdb_string(row.ts_code)}, {duckdb_string(row.display_name)})"
        for row in seed_rows
    )
    return (
        f"(VALUES {values_sql}) "
        "AS seed(partition_key, rank, ts_code, display_name)"
    )


def _active_seed_values_sql(expected_trade_dates: Sequence[str]) -> str:
    rows = [
        (trade_date, seed_row)
        for trade_date in expected_trade_dates
        for seed_row in active_major_indices_seed_rows(trade_date)
    ]
    if not rows:
        return (
            "SELECT CAST(NULL AS VARCHAR) AS partition_key, "
            "CAST(NULL AS INTEGER) AS rank, "
            "CAST(NULL AS VARCHAR) AS ts_code, "
            "CAST(NULL AS VARCHAR) AS display_name WHERE FALSE"
        )
    values_sql = ", ".join(
        f"({duckdb_string(trade_date)}, {seed_row.rank}, {duckdb_string(seed_row.ts_code)}, {duckdb_string(seed_row.display_name)})"
        for trade_date, seed_row in rows
    )
    return (
        f"(VALUES {values_sql}) "
        "AS seed(partition_key, rank, ts_code, display_name)"
    )


def _missing_seed_codes_in_index_basic(
    connection,
    *,
    index_basic_path: Path,
    seed_rows: Sequence[MajorIndexSeedRow],
    sample_limit: int,
) -> tuple[int, tuple[str, ...]]:
    seed_sql = _seed_values_sql(seed_rows)
    missing_sql = f"""
    SELECT seed.ts_code
    FROM {seed_sql}
    LEFT JOIN {read_parquet(index_basic_path, hive_partitioning=False)} index_basic
      ON seed.ts_code = index_basic.ts_code
    WHERE index_basic.ts_code IS NULL
    """
    missing_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({missing_sql}) missing_codes"
        ).fetchone()[0]
    )
    rows = connection.execute(
        f"{missing_sql} ORDER BY ts_code LIMIT {int(sample_limit)}"
    ).fetchall()
    return missing_count, tuple(str(row[0]) for row in rows)


def _gold_metric_rows(
    connection,
    *,
    paths: Sequence[Path],
    expected_trade_dates: Sequence[str],
) -> dict[str, dict[str, int]]:
    if not paths:
        return {}
    seed_sql = _active_seed_values_sql(expected_trade_dates)
    rows = connection.execute(
        f"""
        WITH daily AS (
          SELECT
            regexp_extract(
              filename,
              'trade_date=([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})',
              1
            ) AS partition_key,
            *
          FROM {_read_parquet_paths(paths, union_by_name=True)}
        ),
        seed AS (
          SELECT * FROM {seed_sql}
        ),
        stats AS (
          SELECT
            partition_key,
            count(*) AS row_count,
            count(DISTINCT ts_code) AS distinct_code_count,
            count(DISTINCT rank) AS distinct_rank_count,
            count(*) FILTER (
              WHERE trade_date IS NULL
                 OR CAST(trade_date AS DATE) != CAST(partition_key AS DATE)
            ) AS date_mismatch_count,
            count(*) FILTER (
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
            ) AS price_failed_count
          FROM daily
          GROUP BY partition_key
        ),
        seed_count AS (
          SELECT partition_key, count(*) AS seed_row_count
          FROM seed
          GROUP BY partition_key
        ),
        duplicate_codes AS (
          SELECT partition_key, count(*) AS duplicate_code_count
          FROM (
            SELECT partition_key, ts_code
            FROM daily
            GROUP BY partition_key, ts_code
            HAVING count(*) > 1
          ) duplicate_keys
          GROUP BY partition_key
        ),
        seed_missing AS (
          SELECT seed.partition_key, count(*) AS missing_seed_count
          FROM seed
          LEFT JOIN daily
            ON seed.partition_key = daily.partition_key
           AND seed.ts_code = daily.ts_code
          WHERE daily.ts_code IS NULL
          GROUP BY seed.partition_key
        ),
        rank_mismatch AS (
          SELECT seed.partition_key, count(*) AS rank_mismatch_count
          FROM seed
          LEFT JOIN daily
            ON seed.partition_key = daily.partition_key
           AND seed.rank = daily.rank
           AND seed.ts_code = daily.ts_code
          WHERE daily.ts_code IS NULL
          GROUP BY seed.partition_key
        )
        SELECT
          stats.partition_key,
          stats.row_count,
          coalesce(seed_count.seed_row_count, 0) AS seed_row_count,
          stats.date_mismatch_count,
          coalesce(duplicate_codes.duplicate_code_count, 0) AS duplicate_code_count,
          coalesce(seed_missing.missing_seed_count, 0) AS missing_seed_count,
          coalesce(rank_mismatch.rank_mismatch_count, 0) AS rank_mismatch_count,
          stats.price_failed_count
        FROM stats
        LEFT JOIN seed_count USING (partition_key)
        LEFT JOIN duplicate_codes USING (partition_key)
        LEFT JOIN seed_missing USING (partition_key)
        LEFT JOIN rank_mismatch USING (partition_key)
        """
    ).fetchall()
    return {
        str(row[0]): {
            "row_count": int(row[1]),
            "seed_row_count": int(row[2]),
            "date_mismatch_count": int(row[3]),
            "duplicate_code_count": int(row[4]),
            "missing_seed_count": int(row[5]),
            "rank_mismatch_count": int(row[6]),
            "price_failed_count": int(row[7]),
        }
        for row in rows
    }


def batch_market_major_indices_lake_readiness(
    *,
    connection,
    lake_root_path: Path,
    expected_trade_dates: Sequence[str],
    registered_index_codes: Sequence[str],
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> ContinuityBatchReadiness:
    started_at = perf_counter()
    expected_trade_dates = tuple(str(value) for value in expected_trade_dates)
    paths_by_date = {
        trade_date: gold_market_major_indices_daily_path(lake_root_path, trade_date)
        for trade_date in expected_trade_dates
    }
    existing_paths_by_date = {
        trade_date: path for trade_date, path in paths_by_date.items() if path.exists()
    }
    statuses: dict[str, ContinuityDateReadiness] = {}
    schema_failures_by_date: dict[str, dict[str, object]] = {}
    schema_ok_paths: list[Path] = []

    try:
        seed_rows = load_major_indices_seed()
        registered_code_set = set(registered_index_codes)
        missing_registered_seed_codes = tuple(
            row.ts_code for row in seed_rows if row.ts_code not in registered_code_set
        )
        index_basic_path = silver_index_basic_path(lake_root_path)
        index_basic_missing = not index_basic_path.exists()
        missing_index_basic_seed_count = 0
        missing_index_basic_seed_samples: tuple[str, ...] = ()
        if not index_basic_missing:
            (
                missing_index_basic_seed_count,
                missing_index_basic_seed_samples,
            ) = _missing_seed_codes_in_index_basic(
                connection,
                index_basic_path=index_basic_path,
                seed_rows=seed_rows,
                sample_limit=sample_limit,
            )

        for trade_date, path in paths_by_date.items():
            if not path.exists():
                statuses[trade_date] = _missing_file_status(
                    trade_date=trade_date,
                    check_name="gold_market_major_indices_daily_file_exists",
                    file_path=path,
                    reason="missing_gold_file",
                )
                continue
            schema_result = _schema_failures(
                connection,
                path,
                required_columns=_GOLD_REQUIRED_COLUMNS,
                expected_types=_GOLD_COLUMN_TYPES,
            )
            if (
                schema_result["missing_columns"]
                or schema_result["unexpected_columns"]
                or schema_result["type_mismatches"]
            ):
                schema_failures_by_date[trade_date] = schema_result
            else:
                schema_ok_paths.append(path)

        metric_rows = _gold_metric_rows(
            connection,
            paths=schema_ok_paths,
            expected_trade_dates=expected_trade_dates,
        )
        for trade_date, path in existing_paths_by_date.items():
            failed_check_names: list[str] = []
            missing_paths: list[str] = []
            summary: dict[str, object] = {
                "file_path": str(path),
                "active_seed_code_count": len(
                    active_major_indices_seed_rows(trade_date)
                ),
                "registered_code_count": len(registered_code_set),
            }
            if trade_date in schema_failures_by_date:
                failed_check_names.append(
                    "gold_market_major_indices_daily_required_columns_and_types"
                )
                summary["schema"] = schema_failures_by_date[trade_date]

            metrics = metric_rows.get(trade_date)
            if metrics is None and trade_date not in schema_failures_by_date:
                failed_check_names.append("lake_readiness_scan_error")
                summary["missing_metric_row"] = True
            if metrics is not None:
                summary.update(metrics)
                if metrics["row_count"] != metrics["seed_row_count"]:
                    failed_check_names.append(
                        "gold_market_major_indices_daily_row_count_matches_seed"
                    )
                if metrics["date_mismatch_count"]:
                    failed_check_names.append(
                        "gold_market_major_indices_daily_partition_date_matches"
                    )
                if metrics["duplicate_code_count"]:
                    failed_check_names.append(
                        "gold_market_major_indices_daily_unique_ts_code"
                    )
                if metrics["missing_seed_count"]:
                    failed_check_names.append(
                        "gold_market_major_indices_daily_seed_codes_present"
                    )
                if metrics["rank_mismatch_count"]:
                    failed_check_names.append(
                        "gold_market_major_indices_daily_rank_matches_active_seed_order"
                    )
                if metrics["price_failed_count"]:
                    failed_check_names.append(
                        "gold_market_major_indices_daily_price_sanity"
                    )

            if index_basic_missing:
                failed_check_names.append(
                    "gold_market_major_indices_seed_codes_exist_in_index_basic"
                )
                missing_paths.append(str(index_basic_path))
                summary["missing_index_basic_file"] = True
            elif missing_index_basic_seed_count:
                failed_check_names.append(
                    "gold_market_major_indices_seed_codes_exist_in_index_basic"
                )
                summary["missing_index_basic_seed_count"] = (
                    missing_index_basic_seed_count
                )
                summary["missing_index_basic_seed_samples"] = list(
                    missing_index_basic_seed_samples
                )
            if missing_registered_seed_codes:
                failed_check_names.append(
                    "gold_market_major_indices_seed_codes_exist_in_registered_index_ts_codes"
                )
                summary["missing_registered_seed_code_count"] = len(
                    missing_registered_seed_codes
                )
                summary["missing_registered_seed_code_samples"] = list(
                    missing_registered_seed_codes[:sample_limit]
                )

            if failed_check_names:
                statuses[trade_date] = _failed_status(
                    trade_date=trade_date,
                    reason="blocking_checks_failed",
                    failed_check_names=tuple(dict.fromkeys(failed_check_names)),
                    missing_file_paths=tuple(missing_paths),
                    summary=summary,
                )
            else:
                statuses[trade_date] = _ready_status(
                    trade_date=trade_date,
                    summary=summary,
                )
    except Exception as error:
        statuses = {
            trade_date: _scan_error_status(
                trade_date=trade_date,
                materialized=paths_by_date[trade_date].exists(),
                error=error,
                file_path=paths_by_date[trade_date],
            )
            for trade_date in expected_trade_dates
        }

    return ContinuityBatchReadiness(
        expected_trade_dates=expected_trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=_elapsed_ms(started_at),
        scanned_file_count=len(existing_paths_by_date),
    )


def _silver_daily_metric_row(
    connection,
    *,
    silver_path: Path,
    raw_path: Path,
    trade_date: str,
) -> dict[str, int]:
    raw_present_sql = f"""
        SELECT DISTINCT ts_code
        FROM {read_parquet(raw_path, hive_partitioning=False)}
        WHERE CAST(trade_date AS VARCHAR) = {duckdb_string(trade_date.replace("-", ""))}
        """
    row = connection.execute(
        f"""
        WITH silver AS (
          SELECT * FROM {read_parquet(silver_path, hive_partitioning=False)}
        ),
        raw_present AS (
          {raw_present_sql}
        )
        SELECT
          (SELECT count(*) FROM silver) AS row_count,
          (SELECT count(*) FROM silver WHERE trade_date IS NULL
             OR CAST(trade_date AS DATE) != DATE {duckdb_string(trade_date)}
          ) AS date_mismatch_count,
          (SELECT count(*) FROM (
             SELECT ts_code, trade_date
             FROM silver
             GROUP BY ts_code, trade_date
             HAVING count(*) > 1
          ) duplicate_keys) AS duplicate_key_count,
          (SELECT count(*) FROM silver
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
          ) AS price_failed_count,
          (SELECT count(*)
           FROM raw_present
           LEFT JOIN silver USING (ts_code)
           WHERE silver.ts_code IS NULL
          ) AS missing_raw_present_count,
          (SELECT count(*)
           FROM silver
           LEFT JOIN raw_present USING (ts_code)
           WHERE raw_present.ts_code IS NULL
          ) AS extra_count
        """
    ).fetchone()
    return {
        "row_count": int(row[0]),
        "date_mismatch_count": int(row[1]),
        "duplicate_key_count": int(row[2]),
        "price_failed_count": int(row[3]),
        "missing_raw_present_count": int(row[4]),
        "extra_count": int(row[5]),
    }


def silver_index_daily_lake_readiness_for_trade_date(
    *,
    connection,
    lake_root_path: Path,
    trade_date: str,
    registered_index_codes: Sequence[str],
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> ContinuityDateReadiness:
    del sample_limit
    silver_path = silver_index_daily_path(lake_root_path, trade_date)
    if not silver_path.exists():
        return _missing_file_status(
            trade_date=trade_date,
            check_name="silver_index_daily_row_count_positive",
            file_path=silver_path,
            reason="missing_silver_index_daily_file",
        )

    try:
        failed_check_names: list[str] = []
        schema_result = _schema_failures(
            connection,
            silver_path,
            required_columns=INDEX_DAILY_SILVER_COLUMNS,
            expected_types=INDEX_DAILY_SILVER_COLUMN_TYPES,
        )
        if (
            schema_result["missing_columns"]
            or schema_result["unexpected_columns"]
            or schema_result["type_mismatches"]
        ):
            failed_check_names.append("silver_index_daily_required_columns_and_types")

        registered_codes = tuple(sorted(set(registered_index_codes)))
        raw_path = raw_index_daily_path(lake_root_path, trade_date)
        if not raw_path.exists():
            return _missing_file_status(
                trade_date=trade_date,
                check_name="silver_index_daily_registered_code_coverage",
                file_path=raw_path,
                reason="missing_raw_index_daily_file",
            )
        metrics = _silver_daily_metric_row(
            connection,
            silver_path=silver_path,
            raw_path=raw_path,
            trade_date=trade_date,
        )
        if metrics["row_count"] <= 0:
            failed_check_names.append("silver_index_daily_row_count_positive")
        if metrics["date_mismatch_count"]:
            failed_check_names.append("silver_index_daily_partition_date_matches")
        if metrics["duplicate_key_count"]:
            failed_check_names.extend(
                [
                    "silver_index_daily_unique_ts_code_trade_date",
                    "silver_index_daily_conflicting_duplicate_absent",
                ]
            )
        if metrics["price_failed_count"]:
            failed_check_names.append("silver_index_daily_price_sanity")
        if (
            not registered_codes
            or metrics["missing_raw_present_count"]
            or metrics["extra_count"]
        ):
            failed_check_names.append("silver_index_daily_registered_code_coverage")

        summary: dict[str, object] = {
            "file_path": str(silver_path),
            "raw_file_path": str(raw_path),
            "registered_code_count": len(registered_codes),
            **metrics,
        }
        if (
            schema_result["missing_columns"]
            or schema_result["unexpected_columns"]
            or schema_result["type_mismatches"]
        ):
            summary["schema"] = schema_result

        if failed_check_names:
            return _failed_status(
                trade_date=trade_date,
                reason="blocking_checks_failed",
                failed_check_names=tuple(dict.fromkeys(failed_check_names)),
                summary=summary,
            )
        return _ready_status(trade_date=trade_date, summary=summary)
    except Exception as error:
        return _scan_error_status(
            trade_date=trade_date,
            materialized=True,
            error=error,
            file_path=silver_path,
        )


def silver_index_basic_lake_readiness(
    *,
    connection,
    lake_root_path: Path,
    ready_for_trade_date: str,
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> ContinuityDateReadiness:
    del sample_limit
    path = silver_index_basic_path(lake_root_path)
    if not path.exists():
        return _missing_file_status(
            trade_date=ready_for_trade_date,
            check_name="silver_index_basic_file_exists",
            file_path=path,
            reason="missing_silver_index_basic_file",
        )

    try:
        failed_check_names: list[str] = []
        schema_result = _schema_failures(
            connection,
            path,
            required_columns=_SILVER_INDEX_BASIC_REQUIRED_COLUMNS,
            expected_types=_SILVER_INDEX_BASIC_COLUMN_TYPES,
        )
        if (
            schema_result["missing_columns"]
            or schema_result["unexpected_columns"]
            or schema_result["type_mismatches"]
        ):
            failed_check_names.append("silver_index_basic_required_columns_and_types")

        row = connection.execute(
            f"""
            SELECT
              count(*) AS row_count,
              count(*) FILTER (
                WHERE ts_code IS NULL OR trim(ts_code) = ''
              ) AS missing_ts_code_count,
              (
                SELECT count(*)
                FROM (
                  SELECT ts_code
                  FROM {read_parquet(path, hive_partitioning=False)}
                  WHERE ts_code IS NOT NULL AND trim(ts_code) != ''
                  GROUP BY ts_code
                  HAVING count(*) > 1
                ) duplicate_keys
              ) AS duplicate_key_count,
              count(*) FILTER (
                WHERE ts_code IS NULL
                   OR trim(ts_code) = ''
                   OR name IS NULL
                   OR trim(name) = ''
                   OR market IS NULL
                   OR trim(market) = ''
              ) AS null_required_count,
              count(*) FILTER (
                WHERE exp_date IS NOT NULL
                  AND exp_date <= DATE {duckdb_string(ready_for_trade_date)}
              ) AS terminated_count
            FROM {read_parquet(path, hive_partitioning=False)}
            """
        ).fetchone()
        metrics = {
            "row_count": int(row[0]),
            "missing_ts_code_count": int(row[1]),
            "duplicate_key_count": int(row[2]),
            "null_required_count": int(row[3]),
            "terminated_count": int(row[4]),
        }
        if metrics["row_count"] <= 0:
            failed_check_names.append("silver_index_basic_row_count_positive")
        if metrics["missing_ts_code_count"] or metrics["duplicate_key_count"]:
            failed_check_names.append("silver_index_basic_unique_ts_code")
        if metrics["null_required_count"]:
            failed_check_names.append("silver_index_basic_required_fields_non_null")
        if metrics["terminated_count"]:
            failed_check_names.append("silver_index_basic_no_terminated_indexes")

        summary: dict[str, object] = {
            "file_path": str(path),
            "ready_for_trade_date": ready_for_trade_date,
            **metrics,
        }
        if (
            schema_result["missing_columns"]
            or schema_result["unexpected_columns"]
            or schema_result["type_mismatches"]
        ):
            summary["schema"] = schema_result

        if failed_check_names:
            return _failed_status(
                trade_date=ready_for_trade_date,
                reason="blocking_checks_failed",
                failed_check_names=tuple(dict.fromkeys(failed_check_names)),
                summary=summary,
            )
        return _ready_status(trade_date=ready_for_trade_date, summary=summary)
    except Exception as error:
        return _scan_error_status(
            trade_date=ready_for_trade_date,
            materialized=True,
            error=error,
            file_path=path,
        )
