"""Shared schema and quality semantics for stock nine-turn lake assets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from uuid import uuid4

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_identity_map_path,
    silver_stock_nineturn_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
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
SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA = tuple(
    (column.name, column.type) for column in SILVER_STOCK_NINETURN_DAILY_SCHEMA
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
    source_row_count: int = 0
    mapped_row_count: int = 0
    expected_output_row_count: int = 0
    alias_duplicate_key_count: int = 0
    unresolved_count_signal_conflict_key_count: int = 0
    canonical_selection_mismatch_count: int = 0


@dataclass(frozen=True, slots=True)
class SilverStockNineturnMappingAudit:
    source_row_count: int
    mapped_row_count: int
    expected_output_row_count: int
    alias_duplicate_key_count: int
    count_signal_conflict_key_count: int
    unresolved_count_signal_conflict_key_count: int
    market_value_conflict_key_count: int
    unmapped_source_code_count: int


@dataclass(frozen=True, slots=True)
class SilverStockNineturnDailyWriteResult:
    target_path: Path
    row_count: int
    source_row_count: int
    mapped_row_count: int
    alias_duplicate_key_count: int
    count_signal_conflict_key_count: int
    market_value_conflict_key_count: int
    unmapped_source_code_count: int
    observed_columns: tuple[str, ...]


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


def _silver_mapping_ctes(
    *,
    raw_relation: str,
    identity_relation: str,
    expected_trade_date_sql: str,
) -> str:
    return f"""
    raw_normalized AS (
      SELECT
        trim(ts_code) AS source_ts_code,
        CAST(trade_date AS DATE) AS trade_date,
        trim(freq) AS freq,
        CAST(open AS DOUBLE) AS open,
        CAST(high AS DOUBLE) AS high,
        CAST(low AS DOUBLE) AS low,
        CAST(close AS DOUBLE) AS close,
        CAST(vol AS DOUBLE) AS vol,
        CAST(amount AS DOUBLE) AS amount,
        CAST(up_count AS DOUBLE) AS up_count,
        CAST(down_count AS DOUBLE) AS down_count,
        nullif(trim(nine_up_turn), '') AS nine_up_turn,
        nullif(trim(nine_down_turn), '') AS nine_down_turn
      FROM {raw_relation}
      WHERE trade_date = CAST({expected_trade_date_sql} AS DATE)
    ),
    mapped AS (
      SELECT
        identity.latest_ts_code,
        raw_normalized.*
      FROM raw_normalized
      LEFT JOIN {identity_relation} AS identity
        ON raw_normalized.source_ts_code = identity.source_ts_code
       AND raw_normalized.trade_date >= identity.valid_from
       AND (
         identity.valid_to IS NULL
         OR raw_normalized.trade_date < identity.valid_to
       )
    ),
    canonical_groups AS (
      SELECT
        latest_ts_code,
        trade_date,
        count(*) AS source_count,
        bool_or(source_ts_code = latest_ts_code) AS has_canonical_source,
        (
          min(open) IS DISTINCT FROM max(open)
          OR min(high) IS DISTINCT FROM max(high)
          OR min(low) IS DISTINCT FROM max(low)
          OR min(close) IS DISTINCT FROM max(close)
          OR min(vol) IS DISTINCT FROM max(vol)
          OR min(amount) IS DISTINCT FROM max(amount)
        ) AS market_value_conflict,
        (
          min(up_count) IS DISTINCT FROM max(up_count)
          OR min(down_count) IS DISTINCT FROM max(down_count)
          OR count(DISTINCT coalesce(nine_up_turn, '__NULL__')) > 1
          OR count(DISTINCT coalesce(nine_down_turn, '__NULL__')) > 1
        ) AS count_signal_conflict
      FROM mapped
      WHERE latest_ts_code IS NOT NULL
      GROUP BY latest_ts_code, trade_date
    ),
    ranked AS (
      SELECT
        *,
        row_number() OVER (
          PARTITION BY latest_ts_code, trade_date
          ORDER BY
            CASE WHEN source_ts_code = latest_ts_code THEN 0 ELSE 1 END,
            source_ts_code
        ) AS source_rank
      FROM mapped
      WHERE latest_ts_code IS NOT NULL
    )
    """


def build_silver_stock_nineturn_daily_select_sql(
    *,
    raw_path: Path,
    identity_map_path: Path,
    trade_date: str,
) -> str:
    mapping_ctes = _silver_mapping_ctes(
        raw_relation=read_parquet(raw_path, hive_partitioning=False),
        identity_relation=read_parquet(identity_map_path, hive_partitioning=False),
        expected_trade_date_sql=duckdb_string(trade_date),
    )
    cast_columns = {
        "ts_code": "latest_ts_code",
        "trade_date": "trade_date",
        "freq": "freq",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "vol": "vol",
        "amount": "amount",
        "up_count": "up_count",
        "down_count": "down_count",
        "nine_up_turn": "nine_up_turn",
        "nine_down_turn": "nine_down_turn",
    }
    projections = ",\n      ".join(
        f"CAST({cast_columns[column]} AS "
        f"{SILVER_STOCK_NINETURN_DAILY_COLUMN_TYPES[column]}) AS {column}"
        for column in SILVER_STOCK_NINETURN_DAILY_COLUMNS
    )
    return f"""
    WITH {mapping_ctes}
    SELECT
      {projections}
    FROM ranked
    WHERE source_rank = 1
    ORDER BY ts_code
    """


def load_silver_stock_nineturn_mapping_audit(
    connection,
    *,
    raw_path: Path,
    identity_map_path: Path,
    trade_date: str,
) -> SilverStockNineturnMappingAudit:
    mapping_ctes = _silver_mapping_ctes(
        raw_relation=read_parquet(raw_path, hive_partitioning=False),
        identity_relation=read_parquet(identity_map_path, hive_partitioning=False),
        expected_trade_date_sql=duckdb_string(trade_date),
    )
    row = connection.execute(
        f"""
        WITH {mapping_ctes}
        SELECT
          (SELECT count(*) FROM raw_normalized) AS source_row_count,
          (SELECT count(*) FROM mapped WHERE latest_ts_code IS NOT NULL)
            AS mapped_row_count,
          (SELECT count(*) FROM canonical_groups) AS expected_output_row_count,
          (SELECT count(*) FROM canonical_groups WHERE source_count > 1)
            AS alias_duplicate_key_count,
          (SELECT count(*) FROM canonical_groups WHERE count_signal_conflict)
            AS count_signal_conflict_key_count,
          (
            SELECT count(*)
            FROM canonical_groups
            WHERE count_signal_conflict AND NOT has_canonical_source
          ) AS unresolved_count_signal_conflict_key_count,
          (SELECT count(*) FROM canonical_groups WHERE market_value_conflict)
            AS market_value_conflict_key_count,
          (SELECT count(*) FROM mapped WHERE latest_ts_code IS NULL)
            AS unmapped_source_code_count
        """
    ).fetchone()
    return SilverStockNineturnMappingAudit(
        source_row_count=int(row[0]),
        mapped_row_count=int(row[1]),
        expected_output_row_count=int(row[2]),
        alias_duplicate_key_count=int(row[3]),
        count_signal_conflict_key_count=int(row[4]),
        unresolved_count_signal_conflict_key_count=int(row[5]),
        market_value_conflict_key_count=int(row[6]),
        unmapped_source_code_count=int(row[7]),
    )


def load_silver_stock_nineturn_mapping_failure_samples(
    connection,
    *,
    raw_path: Path,
    identity_map_path: Path,
    trade_date: str,
    limit: int = 10,
) -> tuple[dict[str, object], ...]:
    if limit <= 0:
        raise ValueError("limit must be positive.")
    mapping_ctes = _silver_mapping_ctes(
        raw_relation=read_parquet(raw_path, hive_partitioning=False),
        identity_relation=read_parquet(identity_map_path, hive_partitioning=False),
        expected_trade_date_sql=duckdb_string(trade_date),
    )
    rows = connection.execute(
        f"""
        WITH {mapping_ctes},
        unmapped_samples AS (
          SELECT
            source_ts_code,
            CAST(NULL AS VARCHAR) AS latest_ts_code,
            'unmapped_source_code' AS issue
          FROM mapped
          WHERE latest_ts_code IS NULL
        ),
        conflict_samples AS (
          SELECT
            CAST(NULL AS VARCHAR) AS source_ts_code,
            latest_ts_code,
            CASE
              WHEN market_value_conflict THEN 'market_value_conflict'
              ELSE 'count_signal_conflict_without_canonical_source'
            END AS issue
          FROM canonical_groups
          WHERE market_value_conflict
             OR (count_signal_conflict AND NOT has_canonical_source)
        )
        SELECT source_ts_code, latest_ts_code, issue
        FROM (
          SELECT * FROM unmapped_samples
          UNION ALL
          SELECT * FROM conflict_samples
        )
        ORDER BY issue, source_ts_code, latest_ts_code
        LIMIT {limit}
        """
    ).fetchall()
    columns = ("source_ts_code", "latest_ts_code", "issue")
    return tuple(dict(zip(columns, row, strict=True)) for row in rows)


def _paired_existing_path_plans(
    *,
    raw_path_plans: Sequence[StkNineturnPathPlan],
    silver_path_plans: Sequence[StkNineturnPathPlan],
) -> tuple[tuple[str, Path, Path], ...]:
    raw_by_date = {plan.trade_date: plan for plan in raw_path_plans}
    silver_by_date = {plan.trade_date: plan for plan in silver_path_plans}
    return tuple(
        (trade_date, raw_plan.path, silver_by_date[trade_date].path)
        for trade_date, raw_plan in sorted(raw_by_date.items())
        if trade_date in silver_by_date
        and raw_plan.file_exists
        and raw_plan.path.exists()
        and silver_by_date[trade_date].file_exists
        and silver_by_date[trade_date].path.exists()
    )


def load_silver_stock_nineturn_daily_metrics(
    connection,
    *,
    raw_path_plans: Sequence[StkNineturnPathPlan],
    silver_path_plans: Sequence[StkNineturnPathPlan],
    identity_map_path: Path,
) -> Mapping[str, StkNineturnPartitionMetrics]:
    paired_plans = _paired_existing_path_plans(
        raw_path_plans=raw_path_plans,
        silver_path_plans=silver_path_plans,
    )
    if not paired_plans:
        return {}
    if not identity_map_path.exists():
        raise FileNotFoundError(f"Missing silver stock identity map: {identity_map_path}")

    plan_values = ", ".join(
        f"({duckdb_string(trade_date)}, {duckdb_string(raw_path)}, "
        f"{duckdb_string(silver_path)})"
        for trade_date, raw_path, silver_path in paired_plans
    )
    raw_paths = ", ".join(
        duckdb_string(raw_path) for _trade_date, raw_path, _silver_path in paired_plans
    )
    silver_paths = ", ".join(
        duckdb_string(silver_path)
        for _trade_date, _raw_path, silver_path in paired_plans
    )
    result = connection.execute(
        f"""
        WITH path_plan(expected_trade_date, raw_file_path, silver_file_path) AS (
          VALUES {plan_values}
        ),
        raw_rows AS (
          SELECT
            plan.expected_trade_date,
            trim(raw.ts_code) AS source_ts_code,
            CAST(raw.trade_date AS DATE) AS trade_date,
            trim(raw.freq) AS freq,
            CAST(raw.open AS DOUBLE) AS open,
            CAST(raw.high AS DOUBLE) AS high,
            CAST(raw.low AS DOUBLE) AS low,
            CAST(raw.close AS DOUBLE) AS close,
            CAST(raw.vol AS DOUBLE) AS vol,
            CAST(raw.amount AS DOUBLE) AS amount,
            CAST(raw.up_count AS DOUBLE) AS up_count,
            CAST(raw.down_count AS DOUBLE) AS down_count,
            nullif(trim(raw.nine_up_turn), '') AS nine_up_turn,
            nullif(trim(raw.nine_down_turn), '') AS nine_down_turn
          FROM read_parquet(
            [{raw_paths}],
            hive_partitioning=false,
            union_by_name=true,
            filename=true
          ) AS raw
          JOIN path_plan AS plan ON raw.filename = plan.raw_file_path
        ),
        silver_rows AS (
          SELECT
            plan.expected_trade_date,
            silver.ts_code,
            CAST(silver.trade_date AS DATE) AS trade_date,
            silver.freq,
            silver.open,
            silver.high,
            silver.low,
            silver.close,
            silver.vol,
            silver.amount,
            silver.up_count,
            silver.down_count,
            silver.nine_up_turn,
            silver.nine_down_turn
          FROM read_parquet(
            [{silver_paths}],
            hive_partitioning=false,
            union_by_name=true,
            filename=true
          ) AS silver
          JOIN path_plan AS plan ON silver.filename = plan.silver_file_path
        ),
        mapped AS (
          SELECT identity.latest_ts_code, raw_rows.*
          FROM raw_rows
          LEFT JOIN {read_parquet(identity_map_path, hive_partitioning=False)} AS identity
            ON raw_rows.source_ts_code = identity.source_ts_code
           AND raw_rows.trade_date >= identity.valid_from
           AND (
             identity.valid_to IS NULL
             OR raw_rows.trade_date < identity.valid_to
           )
        ),
        canonical_groups AS (
          SELECT
            expected_trade_date,
            latest_ts_code,
            trade_date,
            count(*) AS source_count,
            bool_or(source_ts_code = latest_ts_code) AS has_canonical_source,
            (
              min(open) IS DISTINCT FROM max(open)
              OR min(high) IS DISTINCT FROM max(high)
              OR min(low) IS DISTINCT FROM max(low)
              OR min(close) IS DISTINCT FROM max(close)
              OR min(vol) IS DISTINCT FROM max(vol)
              OR min(amount) IS DISTINCT FROM max(amount)
            ) AS market_value_conflict,
            (
              min(up_count) IS DISTINCT FROM max(up_count)
              OR min(down_count) IS DISTINCT FROM max(down_count)
              OR count(DISTINCT coalesce(nine_up_turn, '__NULL__')) > 1
              OR count(DISTINCT coalesce(nine_down_turn, '__NULL__')) > 1
            ) AS count_signal_conflict
          FROM mapped
          WHERE latest_ts_code IS NOT NULL
          GROUP BY expected_trade_date, latest_ts_code, trade_date
        ),
        ranked AS (
          SELECT
            *,
            row_number() OVER (
              PARTITION BY expected_trade_date, latest_ts_code, trade_date
              ORDER BY
                CASE WHEN source_ts_code = latest_ts_code THEN 0 ELSE 1 END,
                source_ts_code
            ) AS source_rank
          FROM mapped
          WHERE latest_ts_code IS NOT NULL
        ),
        expected_rows AS (
          SELECT
            expected_trade_date,
            latest_ts_code AS ts_code,
            trade_date,
            freq,
            open,
            high,
            low,
            close,
            vol,
            amount,
            CAST(up_count AS INTEGER) AS up_count,
            CAST(down_count AS INTEGER) AS down_count,
            nine_up_turn,
            nine_down_turn
          FROM ranked
          WHERE source_rank = 1
        ),
        source_metrics AS (
          SELECT
            expected_trade_date,
            count(*) AS source_row_count,
            count(*) FILTER (WHERE latest_ts_code IS NOT NULL) AS mapped_row_count,
            count(*) FILTER (WHERE latest_ts_code IS NULL)
              AS unmapped_source_code_count
          FROM mapped
          GROUP BY expected_trade_date
        ),
        canonical_metrics AS (
          SELECT
            expected_trade_date,
            count(*) AS expected_output_row_count,
            count(*) FILTER (WHERE source_count > 1) AS alias_duplicate_key_count,
            count(*) FILTER (WHERE market_value_conflict)
              AS market_value_conflict_key_count,
            count(*) FILTER (WHERE count_signal_conflict)
              AS count_signal_conflict_key_count,
            count(*) FILTER (
              WHERE count_signal_conflict AND NOT has_canonical_source
            ) AS unresolved_count_signal_conflict_key_count
          FROM canonical_groups
          GROUP BY expected_trade_date
        ),
        silver_duplicate_groups AS (
          SELECT expected_trade_date, count(*) AS duplicate_key_count
          FROM (
            SELECT expected_trade_date, ts_code, trade_date
            FROM silver_rows
            GROUP BY expected_trade_date, ts_code, trade_date
            HAVING count(*) > 1
          ) AS groups
          GROUP BY expected_trade_date
        ),
        silver_metrics AS (
          SELECT
            expected_trade_date,
            count(*) AS row_count,
            count(*) FILTER (
              WHERE ts_code IS NULL OR trim(ts_code) = ''
                 OR trade_date IS NULL OR freq IS NULL OR trim(freq) = ''
            ) AS null_key_count,
            count(*) FILTER (
              WHERE trade_date IS NULL
                 OR trade_date != CAST(expected_trade_date AS DATE)
            ) AS partition_date_mismatch_count,
            count(*) FILTER (WHERE freq IS NULL OR trim(freq) != 'daily')
              AS non_daily_freq_count,
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
            ) AS invalid_count_count,
            count(*) FILTER (WHERE up_count > 0 AND down_count > 0)
              AS simultaneous_direction_count,
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
          FROM silver_rows
          GROUP BY expected_trade_date
        ),
        selection_mismatches AS (
          SELECT
            coalesce(expected.expected_trade_date, actual.expected_trade_date)
              AS expected_trade_date,
            count(*) FILTER (
              WHERE expected.ts_code IS NULL OR actual.ts_code IS NULL
                 OR expected.freq IS DISTINCT FROM actual.freq
                 OR expected.open IS DISTINCT FROM actual.open
                 OR expected.high IS DISTINCT FROM actual.high
                 OR expected.low IS DISTINCT FROM actual.low
                 OR expected.close IS DISTINCT FROM actual.close
                 OR expected.vol IS DISTINCT FROM actual.vol
                 OR expected.amount IS DISTINCT FROM actual.amount
                 OR expected.up_count IS DISTINCT FROM actual.up_count
                 OR expected.down_count IS DISTINCT FROM actual.down_count
                 OR expected.nine_up_turn IS DISTINCT FROM actual.nine_up_turn
                 OR expected.nine_down_turn IS DISTINCT FROM actual.nine_down_turn
            ) AS canonical_selection_mismatch_count
          FROM expected_rows AS expected
          FULL OUTER JOIN silver_rows AS actual
            ON expected.expected_trade_date = actual.expected_trade_date
           AND expected.ts_code = actual.ts_code
           AND expected.trade_date = actual.trade_date
          GROUP BY coalesce(expected.expected_trade_date, actual.expected_trade_date)
        )
        SELECT
          plan.expected_trade_date AS trade_date,
          coalesce(silver.row_count, 0) AS row_count,
          coalesce(silver.null_key_count, 0) AS null_key_count,
          coalesce(duplicates.duplicate_key_count, 0) AS duplicate_key_count,
          coalesce(silver.partition_date_mismatch_count, 0)
            AS partition_date_mismatch_count,
          coalesce(silver.non_daily_freq_count, 0) AS non_daily_freq_count,
          coalesce(silver.invalid_price_count, 0) AS invalid_price_count,
          coalesce(silver.negative_volume_amount_count, 0)
            AS negative_volume_amount_count,
          coalesce(silver.invalid_count_count, 0) AS invalid_count_count,
          coalesce(silver.simultaneous_direction_count, 0)
            AS simultaneous_direction_count,
          coalesce(silver.invalid_marker_count, 0) AS invalid_marker_count,
          coalesce(silver.marker_count_mismatch_count, 0)
            AS marker_count_mismatch_count,
          coalesce(silver.simultaneous_marker_count, 0)
            AS simultaneous_marker_count,
          coalesce(source.unmapped_source_code_count, 0)
            AS unmapped_source_code_count,
          coalesce(duplicates.duplicate_key_count, 0)
            AS canonical_duplicate_key_count,
          coalesce(canonical.market_value_conflict_key_count, 0)
            AS market_value_conflict_key_count,
          coalesce(canonical.count_signal_conflict_key_count, 0)
            AS count_signal_conflict_key_count,
          coalesce(source.source_row_count, 0) AS source_row_count,
          coalesce(source.mapped_row_count, 0) AS mapped_row_count,
          coalesce(canonical.expected_output_row_count, 0)
            AS expected_output_row_count,
          coalesce(canonical.alias_duplicate_key_count, 0)
            AS alias_duplicate_key_count,
          coalesce(canonical.unresolved_count_signal_conflict_key_count, 0)
            AS unresolved_count_signal_conflict_key_count,
          coalesce(mismatch.canonical_selection_mismatch_count, 0)
            AS canonical_selection_mismatch_count
        FROM path_plan AS plan
        LEFT JOIN silver_metrics AS silver USING (expected_trade_date)
        LEFT JOIN source_metrics AS source USING (expected_trade_date)
        LEFT JOIN canonical_metrics AS canonical USING (expected_trade_date)
        LEFT JOIN silver_duplicate_groups AS duplicates USING (expected_trade_date)
        LEFT JOIN selection_mismatches AS mismatch USING (expected_trade_date)
        ORDER BY trade_date
        """
    )
    column_names = tuple(description[0] for description in result.description)
    metrics_by_date: dict[str, StkNineturnPartitionMetrics] = {}
    for row in result.fetchall():
        values = dict(zip(column_names, row, strict=True))
        trade_date = str(values["trade_date"])
        metric_values = {
            key: int(value)
            for key, value in values.items()
            if key != "trade_date"
        }
        metrics_by_date[trade_date] = StkNineturnPartitionMetrics(
            trade_date=trade_date,
            **metric_values,
        )
    return metrics_by_date


def silver_stock_nineturn_daily_failed_rule_names(
    metrics: StkNineturnPartitionMetrics,
) -> tuple[str, ...]:
    failed_rules = list(raw_stk_nineturn_failed_rule_names(metrics))
    if metrics.unmapped_source_code_count:
        failed_rules.append("identity_mapping_complete")
    if metrics.mapped_row_count != metrics.source_row_count:
        failed_rules.append("identity_mapping_exactly_once")
    if metrics.row_count != metrics.expected_output_row_count:
        failed_rules.append("row_count_matches_canonical_expectation")
    if metrics.canonical_duplicate_key_count:
        failed_rules.append("canonical_key_unique")
    if metrics.market_value_conflict_key_count:
        failed_rules.append("market_values_conflict_free")
    if metrics.unresolved_count_signal_conflict_key_count:
        failed_rules.append("signal_conflicts_have_canonical_source")
    if metrics.canonical_selection_mismatch_count:
        failed_rules.append("canonical_source_preferred")
    return tuple(dict.fromkeys(failed_rules))


def write_silver_stock_nineturn_daily_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_key: str,
    overwrite: bool = False,
) -> SilverStockNineturnDailyWriteResult:
    raw_path = raw_stk_nineturn_path(lake_root, partition_key)
    identity_map_path = silver_stock_identity_map_path(lake_root)
    target_path = silver_stock_nineturn_daily_path(lake_root, partition_key)
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw stk_nineturn file: {raw_path}")
    if not identity_map_path.exists():
        raise FileNotFoundError(
            f"Missing silver stock identity map: {identity_map_path}"
        )
    if target_path.exists() and not overwrite:
        raise FileExistsError(
            f"Silver stock nineturn file already exists: {target_path}"
        )

    connect_duckdb = duckdb.connect
    with connect_duckdb() as connection:
        raw_metrics = load_raw_stk_nineturn_metrics(
            connection,
            path_plans=[
                build_stk_nineturn_path_plan(
                    trade_date=partition_key,
                    path=raw_path,
                )
            ],
        ).get(partition_key)
        if raw_metrics is None or raw_metrics.row_count <= 0:
            raise RuntimeError(
                f"Raw stk_nineturn has no rows for {partition_key}."
            )
        raw_failed_rules = raw_stk_nineturn_failed_rule_names(raw_metrics)
        if raw_failed_rules:
            raise RuntimeError(
                "Raw stk_nineturn failed content preflight: "
                f"trade_date={partition_key}, failed_rules={raw_failed_rules}."
            )

        mapping_audit = load_silver_stock_nineturn_mapping_audit(
            connection,
            raw_path=raw_path,
            identity_map_path=identity_map_path,
            trade_date=partition_key,
        )
        failure_samples = load_silver_stock_nineturn_mapping_failure_samples(
            connection,
            raw_path=raw_path,
            identity_map_path=identity_map_path,
            trade_date=partition_key,
        )
        if mapping_audit.unmapped_source_code_count:
            raise RuntimeError(
                "Silver stock nineturn has unmapped source codes: "
                f"count={mapping_audit.unmapped_source_code_count}, "
                f"samples={failure_samples}."
            )
        if mapping_audit.mapped_row_count != mapping_audit.source_row_count:
            raise RuntimeError(
                "Silver stock nineturn has ambiguous identity mappings: "
                f"source_row_count={mapping_audit.source_row_count}, "
                f"mapped_row_count={mapping_audit.mapped_row_count}."
            )
        if mapping_audit.market_value_conflict_key_count:
            raise RuntimeError(
                "Silver stock nineturn has market value conflicts: "
                f"count={mapping_audit.market_value_conflict_key_count}, "
                f"samples={failure_samples}."
            )
        if mapping_audit.unresolved_count_signal_conflict_key_count:
            raise RuntimeError(
                "Silver stock nineturn has signal conflicts without canonical source rows: "
                f"count={mapping_audit.unresolved_count_signal_conflict_key_count}, "
                f"samples={failure_samples}."
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = target_path.with_name(
            f"{target_path.name}.tmp.{uuid4().hex}"
        )
        try:
            connection.execute(
                copy_query_to_parquet(
                    build_silver_stock_nineturn_daily_select_sql(
                        raw_path=raw_path,
                        identity_map_path=identity_map_path,
                        trade_date=partition_key,
                    ),
                    temporary_path,
                )
            )
            observed_schema = describe_stk_nineturn_parquet_schema(
                connection,
                temporary_path,
            )
            if observed_schema != SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA:
                raise RuntimeError(
                    "Silver stock nineturn output schema mismatch: "
                    f"observed={observed_schema}, "
                    f"expected={SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA}."
                )
            output_metrics = load_silver_stock_nineturn_daily_metrics(
                connection,
                raw_path_plans=[
                    build_stk_nineturn_path_plan(
                        trade_date=partition_key,
                        path=raw_path,
                    )
                ],
                silver_path_plans=[
                    build_stk_nineturn_path_plan(
                        trade_date=partition_key,
                        path=temporary_path,
                    )
                ],
                identity_map_path=identity_map_path,
            ).get(partition_key)
            if output_metrics is None:
                raise RuntimeError(
                    f"Silver stock nineturn output audit is missing for {partition_key}."
                )
            output_failed_rules = silver_stock_nineturn_daily_failed_rule_names(
                output_metrics
            )
            if output_failed_rules:
                raise RuntimeError(
                    "Silver stock nineturn output failed final preflight: "
                    f"trade_date={partition_key}, failed_rules={output_failed_rules}."
                )
            os.replace(temporary_path, target_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    return SilverStockNineturnDailyWriteResult(
        target_path=target_path,
        row_count=output_metrics.row_count,
        source_row_count=mapping_audit.source_row_count,
        mapped_row_count=mapping_audit.mapped_row_count,
        alias_duplicate_key_count=mapping_audit.alias_duplicate_key_count,
        count_signal_conflict_key_count=(
            mapping_audit.count_signal_conflict_key_count
        ),
        market_value_conflict_key_count=(
            mapping_audit.market_value_conflict_key_count
        ),
        unmapped_source_code_count=mapping_audit.unmapped_source_code_count,
        observed_columns=tuple(
            column_name
            for column_name, _column_type in (
                SILVER_STOCK_NINETURN_DAILY_EXPECTED_SCHEMA
            )
        ),
    )
