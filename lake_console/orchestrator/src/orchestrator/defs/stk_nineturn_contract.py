"""Shared schema and quality semantics for stock nine-turn lake assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from orchestrator.defs.duckdb_sql import (
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STK_NINETURN_SCHEMA,
    SILVER_STOCK_NINETURN_DAILY_SCHEMA,
)


RAW_STK_NINETURN_COLUMNS = tuple(
    column.name for column in RAW_TUSHARE_STK_NINETURN_SCHEMA
)
RAW_STK_NINETURN_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_STK_NINETURN_SCHEMA
}
SILVER_STOCK_NINETURN_DAILY_COLUMNS = tuple(
    column.name for column in SILVER_STOCK_NINETURN_DAILY_SCHEMA
)
SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_STOCK_NINETURN_DAILY_SCHEMA
}

RAW_STK_NINETURN_EXPECTED_SCHEMA = tuple(
    (column.name, column.type) for column in RAW_TUSHARE_STK_NINETURN_SCHEMA
)


@dataclass(frozen=True, slots=True)
class StkNineturnPathPlan:
    trade_date: str
    path: Path
    file_exists: bool


@dataclass(frozen=True, slots=True)
class StkNineturnPartitionMetrics:
    trade_date: str
    row_count: int
    null_key_count: int
    duplicate_key_count: int
    partition_date_mismatch_count: int
    non_daily_freq_count: int
    invalid_price_count: int
    negative_volume_amount_count: int
    invalid_count_count: int
    simultaneous_direction_count: int
    invalid_marker_count: int
    marker_count_mismatch_count: int
    simultaneous_marker_count: int
    unmapped_source_code_count: int = 0
    canonical_duplicate_key_count: int = 0
    market_value_conflict_key_count: int = 0
    count_signal_conflict_key_count: int = 0


RAW_STK_NINETURN_CONTENT_RULE_NAMES = (
    "key_columns_non_null",
    "unique_ts_code_trade_date",
    "partition_date_matches",
    "freq_is_daily",
    "ohlc_domain_valid",
    "volume_amount_non_negative",
    "counts_are_non_negative_integers",
    "directions_not_simultaneously_positive",
    "markers_in_allowed_domain",
    "marker_requires_count_at_least_nine",
    "markers_not_simultaneously_present",
)


def build_stk_nineturn_path_plan(
    *,
    trade_date: str,
    path: Path,
) -> StkNineturnPathPlan:
    return StkNineturnPathPlan(
        trade_date=trade_date,
        path=path,
        file_exists=path.exists(),
    )


def describe_stk_nineturn_parquet_schema(
    connection,
    path: Path,
) -> tuple[tuple[str, str], ...]:
    rows = connection.execute(describe_parquet_query(path)).fetchall()
    return tuple((str(row[0]), str(row[1])) for row in rows)


def load_raw_stk_nineturn_metrics(
    connection,
    *,
    path_plans: Sequence[StkNineturnPathPlan],
) -> Mapping[str, StkNineturnPartitionMetrics]:
    existing_plans = tuple(
        plan for plan in path_plans if plan.file_exists and plan.path.exists()
    )
    if not existing_plans:
        return {}

    path_plan_values = ", ".join(
        f"({duckdb_string(plan.trade_date)}, {duckdb_string(plan.path)})"
        for plan in existing_plans
    )
    parquet_paths = ", ".join(duckdb_string(plan.path) for plan in existing_plans)
    query_result = connection.execute(
        f"""
        WITH path_plan(expected_trade_date, file_path) AS (
          VALUES {path_plan_values}
        ),
        raw_rows AS (
          SELECT
            path_plan.expected_trade_date,
            raw.ts_code,
            raw.trade_date,
            raw.freq,
            raw.open,
            raw.high,
            raw.low,
            raw.close,
            raw.vol,
            raw.amount,
            raw.up_count,
            raw.down_count,
            raw.nine_up_turn,
            raw.nine_down_turn
          FROM read_parquet(
            [{parquet_paths}],
            hive_partitioning=false,
            union_by_name=true,
            filename=true
          ) AS raw
          JOIN path_plan
            ON raw.filename = path_plan.file_path
        ),
        duplicate_keys AS (
          SELECT expected_trade_date AS trade_date, count(*) AS duplicate_key_count
          FROM (
            SELECT expected_trade_date, ts_code, trade_date
            FROM raw_rows
            GROUP BY expected_trade_date, ts_code, trade_date
            HAVING count(*) > 1
          ) AS duplicate_groups
          GROUP BY expected_trade_date
        ),
        metrics AS (
          SELECT
            expected_trade_date AS trade_date,
            count(*) AS row_count,
            count(*) FILTER (
              WHERE ts_code IS NULL OR trim(ts_code) = ''
                 OR trade_date IS NULL
                 OR freq IS NULL OR trim(freq) = ''
            ) AS null_key_count,
            count(*) FILTER (
              WHERE trade_date IS NULL
                 OR trade_date != CAST(expected_trade_date AS DATE)
            ) AS partition_date_mismatch_count,
            count(*) FILTER (
              WHERE freq IS NULL OR trim(freq) != 'daily'
            ) AS non_daily_freq_count,
            count(*) FILTER (
              WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                 OR open < 0 OR high < 0 OR low < 0 OR close < 0
                 OR high < greatest(open, close, low)
                 OR low > least(open, close, high)
            ) AS invalid_price_count,
            count(*) FILTER (
              WHERE vol IS NULL OR amount IS NULL OR vol < 0 OR amount < 0
            ) AS negative_volume_amount_count,
            count(*) FILTER (
              WHERE up_count IS NULL OR down_count IS NULL
                 OR up_count < 0 OR down_count < 0
                 OR up_count != trunc(up_count)
                 OR down_count != trunc(down_count)
            ) AS invalid_count_count,
            count(*) FILTER (
              WHERE up_count > 0 AND down_count > 0
            ) AS simultaneous_direction_count,
            count(*) FILTER (
              WHERE (nine_up_turn IS NOT NULL AND trim(nine_up_turn) != '+9')
                 OR (nine_down_turn IS NOT NULL AND trim(nine_down_turn) != '-9')
            ) AS invalid_marker_count,
            count(*) FILTER (
              WHERE (trim(nine_up_turn) = '+9' AND up_count < 9)
                 OR (trim(nine_down_turn) = '-9' AND down_count < 9)
            ) AS marker_count_mismatch_count,
            count(*) FILTER (
              WHERE nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL
            ) AS simultaneous_marker_count
          FROM raw_rows
          GROUP BY expected_trade_date
        )
        SELECT
          metrics.*,
          coalesce(duplicate_keys.duplicate_key_count, 0) AS duplicate_key_count
        FROM metrics
        LEFT JOIN duplicate_keys USING (trade_date)
        ORDER BY trade_date
        """
    )
    column_names = tuple(description[0] for description in query_result.description)
    metrics_by_trade_date: dict[str, StkNineturnPartitionMetrics] = {}
    for row in query_result.fetchall():
        values = dict(zip(column_names, row, strict=True))
        trade_date = str(values["trade_date"])
        metrics_by_trade_date[trade_date] = StkNineturnPartitionMetrics(
            trade_date=trade_date,
            row_count=int(values["row_count"]),
            null_key_count=int(values["null_key_count"]),
            duplicate_key_count=int(values["duplicate_key_count"]),
            partition_date_mismatch_count=int(
                values["partition_date_mismatch_count"]
            ),
            non_daily_freq_count=int(values["non_daily_freq_count"]),
            invalid_price_count=int(values["invalid_price_count"]),
            negative_volume_amount_count=int(
                values["negative_volume_amount_count"]
            ),
            invalid_count_count=int(values["invalid_count_count"]),
            simultaneous_direction_count=int(
                values["simultaneous_direction_count"]
            ),
            invalid_marker_count=int(values["invalid_marker_count"]),
            marker_count_mismatch_count=int(values["marker_count_mismatch_count"]),
            simultaneous_marker_count=int(values["simultaneous_marker_count"]),
        )
    return metrics_by_trade_date


def raw_stk_nineturn_failed_rule_names(
    metrics: StkNineturnPartitionMetrics,
) -> tuple[str, ...]:
    failed_rules = []
    if metrics.null_key_count:
        failed_rules.append("key_columns_non_null")
    if metrics.duplicate_key_count:
        failed_rules.append("unique_ts_code_trade_date")
    if metrics.partition_date_mismatch_count:
        failed_rules.append("partition_date_matches")
    if metrics.non_daily_freq_count:
        failed_rules.append("freq_is_daily")
    if metrics.invalid_price_count:
        failed_rules.append("ohlc_domain_valid")
    if metrics.negative_volume_amount_count:
        failed_rules.append("volume_amount_non_negative")
    if metrics.invalid_count_count:
        failed_rules.append("counts_are_non_negative_integers")
    if metrics.simultaneous_direction_count:
        failed_rules.append("directions_not_simultaneously_positive")
    if metrics.invalid_marker_count:
        failed_rules.append("markers_in_allowed_domain")
    if metrics.marker_count_mismatch_count:
        failed_rules.append("marker_requires_count_at_least_nine")
    if metrics.simultaneous_marker_count:
        failed_rules.append("markers_not_simultaneously_present")
    return tuple(failed_rules)


def raw_stk_nineturn_failed_row_count(
    metrics: StkNineturnPartitionMetrics,
) -> int:
    return sum(
        (
            metrics.null_key_count,
            metrics.duplicate_key_count,
            metrics.partition_date_mismatch_count,
            metrics.non_daily_freq_count,
            metrics.invalid_price_count,
            metrics.negative_volume_amount_count,
            metrics.invalid_count_count,
            metrics.simultaneous_direction_count,
            metrics.invalid_marker_count,
            metrics.marker_count_mismatch_count,
            metrics.simultaneous_marker_count,
        )
    )


def load_raw_stk_nineturn_failure_samples(
    connection,
    *,
    path: Path,
    expected_trade_date: str,
    limit: int = 10,
) -> tuple[dict[str, object], ...]:
    if limit <= 0:
        raise ValueError("limit must be positive.")
    rows = connection.execute(
        f"""
        WITH annotated AS (
          SELECT
            *,
            count(*) OVER (PARTITION BY ts_code, trade_date) AS key_count
          FROM {read_parquet(path, hive_partitioning=False)}
        )
        SELECT
          ts_code,
          CAST(trade_date AS VARCHAR) AS trade_date,
          freq,
          up_count,
          down_count,
          nine_up_turn,
          nine_down_turn,
          key_count
        FROM annotated
        WHERE key_count > 1
           OR ts_code IS NULL OR trim(ts_code) = ''
           OR trade_date IS NULL
           OR trade_date != CAST({duckdb_string(expected_trade_date)} AS DATE)
           OR freq IS NULL OR trim(freq) != 'daily'
           OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
           OR open < 0 OR high < 0 OR low < 0 OR close < 0
           OR high < greatest(open, close, low)
           OR low > least(open, close, high)
           OR vol IS NULL OR amount IS NULL OR vol < 0 OR amount < 0
           OR up_count IS NULL OR down_count IS NULL
           OR up_count < 0 OR down_count < 0
           OR up_count != trunc(up_count) OR down_count != trunc(down_count)
           OR (up_count > 0 AND down_count > 0)
           OR (nine_up_turn IS NOT NULL AND trim(nine_up_turn) != '+9')
           OR (nine_down_turn IS NOT NULL AND trim(nine_down_turn) != '-9')
           OR (trim(nine_up_turn) = '+9' AND up_count < 9)
           OR (trim(nine_down_turn) = '-9' AND down_count < 9)
           OR (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)
        ORDER BY ts_code NULLS FIRST
        LIMIT {limit}
        """
    ).fetchall()
    columns = (
        "ts_code",
        "trade_date",
        "freq",
        "up_count",
        "down_count",
        "nine_up_turn",
        "nine_down_turn",
        "key_count",
    )
    return tuple(dict(zip(columns, row, strict=True)) for row in rows)
