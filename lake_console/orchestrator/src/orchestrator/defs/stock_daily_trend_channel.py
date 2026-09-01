"""Pure DuckDB SQL kernel for stock daily trend-channel calculations."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA,
    GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA,
)

FORMULA_KEY = "high-low-ema-hysteresis"
FORMULA_VERSION = "stock-daily-trend-channel-v1"
SHORT_PERIOD = 25
LONG_PERIOD = 90
SHORT_ALPHA = 2.0 / 26.0
LONG_ALPHA = 2.0 / 91.0
SHORT_DECAY = 1.0 - SHORT_ALPHA
LONG_DECAY = 1.0 - LONG_ALPHA
SEGMENT_TRADE_DAY_LIMIT = 250
DAILY_SOURCE_ROW_HARD_LIMIT = 10_000
DAILY_TEMP_SPILL_HARD_LIMIT_BYTES = 1_073_741_824
AUDIT_SAMPLE_LIMIT = 20

POSITION_VALUES = ("ABOVE", "INSIDE", "BELOW")
STATE_VALUES = ("UNKNOWN", "UP", "DOWN")
COMBINED_STATE_VALUES = (
    "UNKNOWN",
    "UP_UP",
    "UP_DOWN",
    "DOWN_UP",
    "DOWN_DOWN",
)

_RELATION_SEGMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class StockDailyTrendChannelAudit:
    """Bounded audit result shared by candidates, checks, and later readiness."""

    passed: bool
    checked_row_count: int
    failed_row_count: int
    source_row_count: int
    output_row_count: int
    failure_rule_counts: Mapping[str, int]
    failure_samples: Mapping[str, tuple[Mapping[str, Any], ...]]
    observed_columns: tuple[str, ...]


@dataclass(frozen=True)
class StockDailyTrendChannelCoverageAudit:
    """Aggregate state coverage contract for one trade date."""

    passed: bool
    checked_row_count: int
    failed_row_count: int
    expected_lifecycle_count: int
    qfq_observed_count: int
    previous_initialized_count: int
    expected_carry_count: int
    actual_observed_state_count: int
    actual_carry_state_count: int
    uninitialized_count: int
    missing_state_count: int
    unexpected_state_count: int
    failure_rule_counts: Mapping[str, int]
    failure_samples: Mapping[str, tuple[Mapping[str, Any], ...]]


@dataclass(frozen=True)
class StockDailyTrendChannelWriteResult:
    """Result of one validated paired candidate write and promotion."""

    trade_date: str
    qfq_source_path: Path
    previous_state_path: Path | None
    stock_basic_path: Path
    stock_lifecycle_path: Path
    result_path: Path
    state_path: Path
    result_candidate_path: Path
    state_candidate_path: Path
    source_row_count: int
    output_row_count: int
    observed_state_row_count: int
    carried_state_row_count: int
    uninitialized_lifecycle_code_count: int
    result_candidate_bytes: int
    state_candidate_bytes: int
    elapsed_ms: float
    peak_memory_bytes: int | None
    temp_spill_bytes: int
    observed_result_columns: tuple[str, ...]
    observed_state_columns: tuple[str, ...]

    @property
    def candidate_bytes(self) -> int:
        return self.result_candidate_bytes + self.state_candidate_bytes


def build_stock_daily_trend_channel_daily_sql(
    source_relation: str,
    *,
    previous_state_relation: str | None = None,
) -> str:
    """Build the one-trade-day formula query used by the daily asset."""

    return _build_stock_daily_trend_channel_sql(
        source_relation,
        previous_state_relation=previous_state_relation,
        segment_trade_day_count=1,
    )


def build_stock_daily_trend_channel_history_segment_sql(
    source_relation: str,
    *,
    segment_trade_day_count: int,
    previous_state_relation: str | None = None,
) -> str:
    """Build one bounded historical segment query."""

    return _build_stock_daily_trend_channel_sql(
        source_relation,
        previous_state_relation=previous_state_relation,
        segment_trade_day_count=segment_trade_day_count,
    )


def build_stock_daily_trend_channel_repair_segment_sql(
    source_relation: str,
    *,
    segment_trade_day_count: int,
    previous_state_relation: str | None = None,
) -> str:
    """Build one bounded repair segment using the same frozen formula."""

    return _build_stock_daily_trend_channel_sql(
        source_relation,
        previous_state_relation=previous_state_relation,
        segment_trade_day_count=segment_trade_day_count,
    )


def _build_stock_daily_trend_channel_sql(
    source_relation: str,
    *,
    previous_state_relation: str | None,
    segment_trade_day_count: int,
) -> str:
    source_sql = _quote_relation(source_relation)
    seed_sql = (
        _quote_relation(previous_state_relation)
        if previous_state_relation is not None
        else _empty_seed_relation_sql()
    )
    _validate_segment_trade_day_count(segment_trade_day_count)

    return f"""
WITH source_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(open AS DOUBLE) AS open,
    CAST(high AS DOUBLE) AS high,
    CAST(low AS DOUBLE) AS low,
    CAST(close AS DOUBLE) AS close
  FROM {source_sql}
),
seed_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(short_upper_raw AS DOUBLE) AS short_upper_raw,
    CAST(short_lower_raw AS DOUBLE) AS short_lower_raw,
    CAST(short_state AS VARCHAR) AS short_state,
    CAST(long_upper_raw AS DOUBLE) AS long_upper_raw,
    CAST(long_lower_raw AS DOUBLE) AS long_lower_raw,
    CAST(long_state AS VARCHAR) AS long_state
  FROM {seed_sql}
),
numbered AS (
  SELECT
    source_rows.*,
    row_number() OVER (
      PARTITION BY ts_code
      ORDER BY trade_date
    ) AS observation_number
  FROM source_rows
),
seeded AS (
  SELECT
    numbered.*,
    seed_rows.ts_code IS NOT NULL AS has_seed,
    seed_rows.short_upper_raw AS seed_short_upper_raw,
    seed_rows.short_lower_raw AS seed_short_lower_raw,
    coalesce(seed_rows.short_state, 'UNKNOWN') AS seed_short_state,
    seed_rows.long_upper_raw AS seed_long_upper_raw,
    seed_rows.long_lower_raw AS seed_long_lower_raw,
    coalesce(seed_rows.long_state, 'UNKNOWN') AS seed_long_state
  FROM numbered
  LEFT JOIN seed_rows USING (ts_code)
),
raw_bands AS (
  SELECT
    *,
    CASE WHEN has_seed THEN
      power({SHORT_DECAY!r}, observation_number) * (
        seed_short_upper_raw
        + {SHORT_ALPHA!r} * sum(
          high * power({SHORT_DECAY!r}, -observation_number)
        ) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
      )
    ELSE
      power({SHORT_DECAY!r}, observation_number - 1) * (
        first_value(high) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
        )
        + {SHORT_ALPHA!r} * sum(
          CASE
            WHEN observation_number = 1 THEN 0.0
            ELSE high * power({SHORT_DECAY!r}, -(observation_number - 1))
          END
        ) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
      )
    END AS short_upper_raw,
    CASE WHEN has_seed THEN
      power({SHORT_DECAY!r}, observation_number) * (
        seed_short_lower_raw
        + {SHORT_ALPHA!r} * sum(
          low * power({SHORT_DECAY!r}, -observation_number)
        ) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
      )
    ELSE
      power({SHORT_DECAY!r}, observation_number - 1) * (
        first_value(low) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
        )
        + {SHORT_ALPHA!r} * sum(
          CASE
            WHEN observation_number = 1 THEN 0.0
            ELSE low * power({SHORT_DECAY!r}, -(observation_number - 1))
          END
        ) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
      )
    END AS short_lower_raw,
    CASE WHEN has_seed THEN
      power({LONG_DECAY!r}, observation_number) * (
        seed_long_upper_raw
        + {LONG_ALPHA!r} * sum(
          high * power({LONG_DECAY!r}, -observation_number)
        ) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
      )
    ELSE
      power({LONG_DECAY!r}, observation_number - 1) * (
        first_value(high) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
        )
        + {LONG_ALPHA!r} * sum(
          CASE
            WHEN observation_number = 1 THEN 0.0
            ELSE high * power({LONG_DECAY!r}, -(observation_number - 1))
          END
        ) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
      )
    END AS long_upper_raw,
    CASE WHEN has_seed THEN
      power({LONG_DECAY!r}, observation_number) * (
        seed_long_lower_raw
        + {LONG_ALPHA!r} * sum(
          low * power({LONG_DECAY!r}, -observation_number)
        ) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
      )
    ELSE
      power({LONG_DECAY!r}, observation_number - 1) * (
        first_value(low) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
        )
        + {LONG_ALPHA!r} * sum(
          CASE
            WHEN observation_number = 1 THEN 0.0
            ELSE low * power({LONG_DECAY!r}, -(observation_number - 1))
          END
        ) OVER (
          PARTITION BY ts_code
          ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
      )
    END AS long_lower_raw
  FROM seeded
),
events AS (
  SELECT
    *,
    CASE
      WHEN close > short_upper_raw THEN 'ABOVE'
      WHEN close < short_lower_raw THEN 'BELOW'
      ELSE 'INSIDE'
    END AS short_position,
    CASE
      WHEN close > short_upper_raw THEN 'UP'
      WHEN close < short_lower_raw THEN 'DOWN'
    END AS short_event,
    CASE
      WHEN close > long_upper_raw THEN 'ABOVE'
      WHEN close < long_lower_raw THEN 'BELOW'
      ELSE 'INSIDE'
    END AS long_position,
    CASE
      WHEN close > long_upper_raw THEN 'UP'
      WHEN close < long_lower_raw THEN 'DOWN'
    END AS long_event
  FROM raw_bands
),
states AS (
  SELECT
    *,
    coalesce(
      last_value(short_event IGNORE NULLS) OVER (
        PARTITION BY ts_code
        ORDER BY trade_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      ),
      seed_short_state,
      'UNKNOWN'
    ) AS resolved_short_state,
    coalesce(
      last_value(long_event IGNORE NULLS) OVER (
        PARTITION BY ts_code
        ORDER BY trade_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      ),
      seed_long_state,
      'UNKNOWN'
    ) AS resolved_long_state
  FROM events
)
SELECT
  ts_code,
  trade_date,
  open,
  high,
  low,
  close,
  short_upper_raw,
  short_lower_raw,
  CAST(ROUND(CAST(short_upper_raw AS DECIMAL(38, 18)), 4) AS DOUBLE)
    AS short_upper,
  CAST(ROUND(CAST(short_lower_raw AS DECIMAL(38, 18)), 4) AS DOUBLE)
    AS short_lower,
  short_position,
  resolved_short_state AS short_state,
  long_upper_raw,
  long_lower_raw,
  CAST(ROUND(CAST(long_upper_raw AS DECIMAL(38, 18)), 4) AS DOUBLE)
    AS long_upper,
  CAST(ROUND(CAST(long_lower_raw AS DECIMAL(38, 18)), 4) AS DOUBLE)
    AS long_lower,
  long_position,
  resolved_long_state AS long_state,
  CASE
    WHEN resolved_short_state = 'UNKNOWN' OR resolved_long_state = 'UNKNOWN'
      THEN 'UNKNOWN'
    ELSE resolved_short_state || '_' || resolved_long_state
  END AS combined_state,
  '{FORMULA_VERSION}' AS formula_version
FROM states
ORDER BY ts_code ASC, trade_date ASC
""".strip()


def _quote_relation(relation: str) -> str:
    normalized = str(relation).strip()
    segments = normalized.split(".")
    if not normalized or any(
        not _RELATION_SEGMENT_PATTERN.fullmatch(segment) for segment in segments
    ):
        raise ValueError(
            "Trend-channel relation must be a dot-qualified SQL identifier."
        )
    return ".".join(f'"{segment}"' for segment in segments)


def _validate_segment_trade_day_count(segment_trade_day_count: int) -> None:
    if isinstance(segment_trade_day_count, bool) or not isinstance(
        segment_trade_day_count, int
    ):
        raise TypeError("segment_trade_day_count must be an integer")
    if not 1 <= segment_trade_day_count <= SEGMENT_TRADE_DAY_LIMIT:
        raise ValueError(
            "segment_trade_day_count must be between 1 and "
            f"{SEGMENT_TRADE_DAY_LIMIT}"
        )


def _empty_seed_relation_sql() -> str:
    return """(
      SELECT
        CAST(NULL AS VARCHAR) AS ts_code,
        CAST(NULL AS DOUBLE) AS short_upper_raw,
        CAST(NULL AS DOUBLE) AS short_lower_raw,
        CAST(NULL AS VARCHAR) AS short_state,
        CAST(NULL AS DOUBLE) AS long_upper_raw,
        CAST(NULL AS DOUBLE) AS long_lower_raw,
        CAST(NULL AS VARCHAR) AS long_state
      WHERE false
    )"""


def audit_stock_daily_trend_channel_result(
    *,
    connection: Any,
    result_path: Path,
    qfq_source_path: Path,
    trade_date: str,
) -> StockDailyTrendChannelAudit:
    """Audit one result file without recomputing the EMA formula."""

    normalized_trade_date = _normalize_trade_date(trade_date)
    missing_paths = tuple(
        path for path in (result_path, qfq_source_path) if not path.exists()
    )
    if missing_paths:
        return _missing_file_audit(
            rule_name="required_file_exists",
            missing_paths=missing_paths,
        )
    path_audit = _partition_file_path_audit(
        connection=connection,
        output_path=result_path,
        source_path=qfq_source_path,
        trade_date=normalized_trade_date,
    )
    if path_audit is not None:
        return path_audit

    observed_schema = _parquet_schema(connection, result_path)
    expected_schema = tuple(
        (column.name, column.type.upper())
        for column in GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA
    )
    output_row_count = _parquet_row_count(connection, result_path)
    source_row_count = _parquet_row_count(connection, qfq_source_path)
    if observed_schema != expected_schema:
        return _schema_failure_audit(
            observed_schema=observed_schema,
            output_row_count=output_row_count,
            source_row_count=source_row_count,
        )

    result_sql = read_parquet(result_path, hive_partitioning=False)
    qfq_sql = read_parquet(qfq_source_path, hive_partitioning=False)
    date_sql = duckdb_string(normalized_trade_date)
    counts = connection.execute(
        f"""
        WITH result_rows AS (
          SELECT * FROM {result_sql}
        ),
        duplicate_keys AS (
          SELECT ts_code, trade_date
          FROM result_rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        ),
        missing_source_rows AS (
          SELECT CAST(ts_code AS VARCHAR), CAST(trade_date AS DATE)
          FROM {qfq_sql}
          EXCEPT
          SELECT ts_code, trade_date FROM result_rows
        ),
        unexpected_result_rows AS (
          SELECT ts_code, trade_date FROM result_rows
          EXCEPT
          SELECT CAST(ts_code AS VARCHAR), CAST(trade_date AS DATE)
          FROM {qfq_sql}
        )
        SELECT
          count(*) FILTER (
            WHERE trade_date IS NULL OR trade_date != DATE {date_sql}
          ),
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
          ),
          (SELECT coalesce(sum(row_count), 0) FROM (
            SELECT count(*) AS row_count FROM result_rows
            GROUP BY ts_code, trade_date HAVING count(*) > 1
          )),
          count(*) FILTER (
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR NOT isfinite(open) OR NOT isfinite(high)
               OR NOT isfinite(low) OR NOT isfinite(close)
               OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
               OR low > least(open, close) OR greatest(open, close) > high
          ),
          count(*) FILTER (
            WHERE short_upper IS NULL OR short_lower IS NULL
               OR long_upper IS NULL OR long_lower IS NULL
               OR NOT isfinite(short_upper) OR NOT isfinite(short_lower)
               OR NOT isfinite(long_upper) OR NOT isfinite(long_lower)
               OR short_upper <= 0 OR short_lower <= 0
               OR long_upper <= 0 OR long_lower <= 0
               OR short_upper < short_lower OR long_upper < long_lower
          ),
          count(*) FILTER (
            WHERE short_position IS NULL OR long_position IS NULL
               OR short_state IS NULL OR long_state IS NULL
               OR combined_state IS NULL
               OR short_position NOT IN ('ABOVE', 'INSIDE', 'BELOW')
               OR long_position NOT IN ('ABOVE', 'INSIDE', 'BELOW')
               OR short_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
               OR long_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
               OR combined_state NOT IN (
                 'UNKNOWN', 'UP_UP', 'UP_DOWN', 'DOWN_UP', 'DOWN_DOWN'
               )
          ),
          count(*) FILTER (
            WHERE combined_state != CASE
              WHEN short_state = 'UNKNOWN' OR long_state = 'UNKNOWN'
                THEN 'UNKNOWN'
              ELSE short_state || '_' || long_state
            END
          ),
          count(*) FILTER (
            WHERE formula_version IS NULL
               OR formula_version != {duckdb_string(FORMULA_VERSION)}
          ),
          (SELECT count(*) FROM missing_source_rows),
          (SELECT count(*) FROM unexpected_result_rows)
        FROM result_rows
        """
    ).fetchone()
    failure_rule_counts = {
        "partition_date_matches": int(counts[0]),
        "key_columns_non_null": int(counts[1]),
        "unique_ts_code_trade_date": int(counts[2]),
        "ohlc_domain_valid": int(counts[3]),
        "channel_bands_valid": int(counts[4]),
        "enum_values_valid": int(counts[5]),
        "combined_state_consistent": int(counts[6]),
        "formula_version_matches": int(counts[7]),
        "missing_qfq_result_rows": int(counts[8]),
        "unexpected_result_rows": int(counts[9]),
    }
    samples = _result_failure_samples(
        connection=connection,
        result_sql=result_sql,
        qfq_sql=qfq_sql,
        trade_date=normalized_trade_date,
    )
    failed_row_count = sum(failure_rule_counts.values())
    return StockDailyTrendChannelAudit(
        passed=failed_row_count == 0 and output_row_count > 0,
        checked_row_count=output_row_count,
        failed_row_count=(failed_row_count if output_row_count > 0 else 1),
        source_row_count=source_row_count,
        output_row_count=output_row_count,
        failure_rule_counts={
            **failure_rule_counts,
            "row_count_positive": int(output_row_count <= 0),
        },
        failure_samples=samples,
        observed_columns=tuple(column[0] for column in observed_schema),
    )


def audit_stock_daily_trend_channel_state(
    *,
    connection: Any,
    state_path: Path,
    stock_lifecycle_path: Path,
    trade_date: str,
) -> StockDailyTrendChannelAudit:
    """Audit one state file against its schema and lifecycle boundary."""

    normalized_trade_date = _normalize_trade_date(trade_date)
    missing_paths = tuple(
        path for path in (state_path, stock_lifecycle_path) if not path.exists()
    )
    if missing_paths:
        return _missing_file_audit(
            rule_name="required_file_exists",
            missing_paths=missing_paths,
        )
    path_audit = _partition_file_path_audit(
        connection=connection,
        output_path=state_path,
        source_path=stock_lifecycle_path,
        trade_date=normalized_trade_date,
    )
    if path_audit is not None:
        return path_audit

    observed_schema = _parquet_schema(connection, state_path)
    expected_schema = tuple(
        (column.name, column.type.upper())
        for column in GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA
    )
    output_row_count = _parquet_row_count(connection, state_path)
    if observed_schema != expected_schema:
        return _schema_failure_audit(
            observed_schema=observed_schema,
            output_row_count=output_row_count,
            source_row_count=0,
        )

    state_sql = read_parquet(state_path, hive_partitioning=False)
    lifecycle_sql = read_parquet(stock_lifecycle_path, hive_partitioning=False)
    date_sql = duckdb_string(normalized_trade_date)
    counts = connection.execute(
        f"""
        WITH state_rows AS (
          SELECT * FROM {state_sql}
        ),
        valid_lifecycle AS (
          SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
          FROM {lifecycle_sql}
          WHERE CAST(is_cny_stock AS BOOLEAN)
            AND CAST(list_date AS DATE) <= DATE {date_sql}
            AND (
              delist_date IS NULL OR CAST(delist_date AS DATE) > DATE {date_sql}
            )
        )
        SELECT
          count(*) FILTER (
            WHERE trade_date IS NULL OR trade_date != DATE {date_sql}
          ),
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
               OR state_source_trade_date IS NULL
               OR observed_on_partition IS NULL
               OR short_upper_raw IS NULL OR short_lower_raw IS NULL
               OR short_state IS NULL OR long_upper_raw IS NULL
               OR long_lower_raw IS NULL OR long_state IS NULL
               OR combined_state IS NULL OR formula_version IS NULL
          ),
          (SELECT coalesce(sum(row_count), 0) FROM (
            SELECT count(*) AS row_count FROM state_rows
            GROUP BY ts_code, trade_date HAVING count(*) > 1
          )),
          count(*) FILTER (
            WHERE NOT isfinite(short_upper_raw)
               OR NOT isfinite(short_lower_raw)
               OR NOT isfinite(long_upper_raw)
               OR NOT isfinite(long_lower_raw)
               OR short_upper_raw <= 0 OR short_lower_raw <= 0
               OR long_upper_raw <= 0 OR long_lower_raw <= 0
               OR short_upper_raw < short_lower_raw
               OR long_upper_raw < long_lower_raw
          ),
          count(*) FILTER (
            WHERE short_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
               OR long_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
               OR combined_state NOT IN (
                 'UNKNOWN', 'UP_UP', 'UP_DOWN', 'DOWN_UP', 'DOWN_DOWN'
               )
          ),
          count(*) FILTER (
            WHERE combined_state != CASE
              WHEN short_state = 'UNKNOWN' OR long_state = 'UNKNOWN'
                THEN 'UNKNOWN'
              ELSE short_state || '_' || long_state
            END
          ),
          count(*) FILTER (
            WHERE state_source_trade_date > trade_date
               OR (
                 observed_on_partition
                 AND state_source_trade_date != trade_date
               )
          ),
          count(*) FILTER (
            WHERE formula_version != {duckdb_string(FORMULA_VERSION)}
          ),
          count(*) FILTER (
            WHERE NOT EXISTS (
              SELECT 1 FROM valid_lifecycle
              WHERE valid_lifecycle.ts_code = state_rows.ts_code
            )
          )
        FROM state_rows
        """
    ).fetchone()
    lifecycle_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {lifecycle_sql}
            WHERE CAST(is_cny_stock AS BOOLEAN)
              AND CAST(list_date AS DATE) <= DATE {date_sql}
              AND (
                delist_date IS NULL OR CAST(delist_date AS DATE) > DATE {date_sql}
              )
            """
        ).fetchone()[0]
    )
    failure_rule_counts = {
        "partition_date_matches": int(counts[0]),
        "required_columns_non_null": int(counts[1]),
        "unique_ts_code_trade_date": int(counts[2]),
        "raw_channel_values_valid": int(counts[3]),
        "state_enums_valid": int(counts[4]),
        "combined_state_consistent": int(counts[5]),
        "state_source_date_valid": int(counts[6]),
        "formula_version_matches": int(counts[7]),
        "lifecycle_membership_valid": int(counts[8]),
    }
    samples = _state_failure_samples(
        connection=connection,
        state_sql=state_sql,
        lifecycle_sql=lifecycle_sql,
        trade_date=normalized_trade_date,
    )
    failed_row_count = sum(failure_rule_counts.values())
    return StockDailyTrendChannelAudit(
        passed=failed_row_count == 0,
        checked_row_count=output_row_count,
        failed_row_count=failed_row_count,
        source_row_count=lifecycle_count,
        output_row_count=output_row_count,
        failure_rule_counts=failure_rule_counts,
        failure_samples=samples,
        observed_columns=tuple(column[0] for column in observed_schema),
    )


def audit_stock_daily_trend_channel_state_coverage(
    *,
    connection: Any,
    state_path: Path,
    qfq_source_path: Path,
    stock_lifecycle_path: Path,
    previous_state_path: Path | None,
    trade_date: str,
) -> StockDailyTrendChannelCoverageAudit:
    """Audit observed, carry, and uninitialized state with one aggregate query."""

    normalized_trade_date = _normalize_trade_date(trade_date)
    missing_paths = tuple(
        path
        for path in (state_path, qfq_source_path, stock_lifecycle_path)
        if not path.exists()
    )
    if previous_state_path is not None and not previous_state_path.exists():
        missing_paths = (*missing_paths, previous_state_path)
    if missing_paths:
        missing_count = len(missing_paths)
        return StockDailyTrendChannelCoverageAudit(
            passed=False,
            checked_row_count=0,
            failed_row_count=missing_count,
            expected_lifecycle_count=0,
            qfq_observed_count=0,
            previous_initialized_count=0,
            expected_carry_count=0,
            actual_observed_state_count=0,
            actual_carry_state_count=0,
            uninitialized_count=0,
            missing_state_count=0,
            unexpected_state_count=0,
            failure_rule_counts={"required_file_exists": missing_count},
            failure_samples={
                "required_file_exists": tuple(
                    {"path": str(path)} for path in missing_paths[:AUDIT_SAMPLE_LIMIT]
                )
            },
        )

    state_sql = read_parquet(state_path, hive_partitioning=False)
    qfq_sql = read_parquet(qfq_source_path, hive_partitioning=False)
    lifecycle_sql = read_parquet(stock_lifecycle_path, hive_partitioning=False)
    previous_sql = (
        read_parquet(previous_state_path, hive_partitioning=False)
        if previous_state_path is not None
        else _empty_previous_state_rows_sql()
    )
    date_sql = duckdb_string(normalized_trade_date)
    metrics = connection.execute(
        f"""
        WITH valid_lifecycle AS (
          SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
          FROM {lifecycle_sql}
          WHERE CAST(is_cny_stock AS BOOLEAN)
            AND CAST(list_date AS DATE) <= DATE {date_sql}
            AND (
              delist_date IS NULL OR CAST(delist_date AS DATE) > DATE {date_sql}
            )
        ),
        qfq_codes AS (
          SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
          FROM {qfq_sql}
          WHERE CAST(trade_date AS DATE) = DATE {date_sql}
        ),
        previous_codes AS (
          SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
          FROM {previous_sql}
        ),
        expected_carry AS (
          SELECT previous_codes.ts_code
          FROM previous_codes
          JOIN valid_lifecycle USING (ts_code)
          LEFT JOIN qfq_codes USING (ts_code)
          WHERE qfq_codes.ts_code IS NULL
        ),
        expected_state AS (
          SELECT ts_code FROM qfq_codes
          UNION
          SELECT ts_code FROM expected_carry
        ),
        actual_state AS (
          SELECT CAST(ts_code AS VARCHAR) AS ts_code,
                 CAST(observed_on_partition AS BOOLEAN) AS observed_on_partition
          FROM {state_sql}
          WHERE CAST(trade_date AS DATE) = DATE {date_sql}
        ),
        uninitialized AS (
          SELECT valid_lifecycle.ts_code
          FROM valid_lifecycle
          LEFT JOIN expected_state USING (ts_code)
          WHERE expected_state.ts_code IS NULL
        ),
        missing_state AS (
          SELECT ts_code FROM expected_state
          EXCEPT
          SELECT ts_code FROM actual_state
        ),
        unexpected_state AS (
          SELECT ts_code FROM actual_state
          EXCEPT
          SELECT ts_code FROM expected_state
        )
        SELECT
          (SELECT count(*) FROM valid_lifecycle),
          (SELECT count(*) FROM qfq_codes),
          (SELECT count(*) FROM previous_codes),
          (SELECT count(*) FROM expected_carry),
          (SELECT count(*) FROM actual_state WHERE observed_on_partition),
          (SELECT count(*) FROM actual_state WHERE NOT observed_on_partition),
          (SELECT count(*) FROM uninitialized),
          (SELECT count(*) FROM missing_state),
          (SELECT count(*) FROM unexpected_state)
        """
    ).fetchone()
    expected_lifecycle_count = int(metrics[0])
    qfq_observed_count = int(metrics[1])
    previous_initialized_count = int(metrics[2])
    expected_carry_count = int(metrics[3])
    actual_observed_state_count = int(metrics[4])
    actual_carry_state_count = int(metrics[5])
    uninitialized_count = int(metrics[6])
    missing_state_count = int(metrics[7])
    unexpected_state_count = int(metrics[8])
    observed_count_delta = abs(actual_observed_state_count - qfq_observed_count)
    carry_count_delta = abs(actual_carry_state_count - expected_carry_count)
    lifecycle_equation_delta = abs(
        expected_lifecycle_count
        - (
            actual_observed_state_count
            + actual_carry_state_count
            + uninitialized_count
        )
    )
    failure_rule_counts = {
        "observed_state_matches_qfq": observed_count_delta,
        "carry_state_matches_expected": carry_count_delta,
        "lifecycle_equation_matches": lifecycle_equation_delta,
        "missing_state": missing_state_count,
        "unexpected_state": unexpected_state_count,
    }
    failed_row_count = sum(failure_rule_counts.values())
    samples = _coverage_failure_samples(
        connection=connection,
        state_sql=state_sql,
        qfq_sql=qfq_sql,
        lifecycle_sql=lifecycle_sql,
        previous_sql=previous_sql,
        trade_date=normalized_trade_date,
    )
    return StockDailyTrendChannelCoverageAudit(
        passed=failed_row_count == 0,
        checked_row_count=actual_observed_state_count + actual_carry_state_count,
        failed_row_count=failed_row_count,
        expected_lifecycle_count=expected_lifecycle_count,
        qfq_observed_count=qfq_observed_count,
        previous_initialized_count=previous_initialized_count,
        expected_carry_count=expected_carry_count,
        actual_observed_state_count=actual_observed_state_count,
        actual_carry_state_count=actual_carry_state_count,
        uninitialized_count=uninitialized_count,
        missing_state_count=missing_state_count,
        unexpected_state_count=unexpected_state_count,
        failure_rule_counts=failure_rule_counts,
        failure_samples=samples,
    )


def _result_failure_samples(
    *,
    connection: Any,
    result_sql: str,
    qfq_sql: str,
    trade_date: str,
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    date_sql = duckdb_string(trade_date)
    rows = connection.execute(
        f"""
        WITH result_rows AS (
          SELECT * FROM {result_sql}
        ),
        duplicate_keys AS (
          SELECT ts_code, trade_date
          FROM result_rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        ),
        violations AS (
          SELECT 'partition_date_matches' AS rule_name, ts_code, trade_date
          FROM result_rows
          WHERE trade_date IS NULL OR trade_date != DATE {date_sql}
          UNION ALL
          SELECT 'key_columns_non_null', ts_code, trade_date
          FROM result_rows
          WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
          UNION ALL
          SELECT 'unique_ts_code_trade_date', result_rows.ts_code,
                 result_rows.trade_date
          FROM result_rows
          JOIN duplicate_keys USING (ts_code, trade_date)
          UNION ALL
          SELECT 'ohlc_domain_valid', ts_code, trade_date
          FROM result_rows
          WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
             OR NOT isfinite(open) OR NOT isfinite(high)
             OR NOT isfinite(low) OR NOT isfinite(close)
             OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
             OR low > least(open, close) OR greatest(open, close) > high
          UNION ALL
          SELECT 'channel_bands_valid', ts_code, trade_date
          FROM result_rows
          WHERE short_upper IS NULL OR short_lower IS NULL
             OR long_upper IS NULL OR long_lower IS NULL
             OR NOT isfinite(short_upper) OR NOT isfinite(short_lower)
             OR NOT isfinite(long_upper) OR NOT isfinite(long_lower)
             OR short_upper <= 0 OR short_lower <= 0
             OR long_upper <= 0 OR long_lower <= 0
             OR short_upper < short_lower OR long_upper < long_lower
          UNION ALL
          SELECT 'enum_values_valid', ts_code, trade_date
          FROM result_rows
          WHERE short_position IS NULL OR long_position IS NULL
             OR short_state IS NULL OR long_state IS NULL
             OR combined_state IS NULL
             OR short_position NOT IN ('ABOVE', 'INSIDE', 'BELOW')
             OR long_position NOT IN ('ABOVE', 'INSIDE', 'BELOW')
             OR short_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
             OR long_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
             OR combined_state NOT IN (
               'UNKNOWN', 'UP_UP', 'UP_DOWN', 'DOWN_UP', 'DOWN_DOWN'
             )
          UNION ALL
          SELECT 'combined_state_consistent', ts_code, trade_date
          FROM result_rows
          WHERE combined_state != CASE
            WHEN short_state = 'UNKNOWN' OR long_state = 'UNKNOWN'
              THEN 'UNKNOWN'
            ELSE short_state || '_' || long_state
          END
          UNION ALL
          SELECT 'formula_version_matches', ts_code, trade_date
          FROM result_rows
          WHERE formula_version IS NULL
             OR formula_version != {duckdb_string(FORMULA_VERSION)}
          UNION ALL
          SELECT 'missing_qfq_result_rows', CAST(ts_code AS VARCHAR),
                 CAST(trade_date AS DATE)
          FROM {qfq_sql}
          EXCEPT
          SELECT 'missing_qfq_result_rows', ts_code, trade_date
          FROM result_rows
          UNION ALL
          SELECT 'unexpected_result_rows', ts_code, trade_date
          FROM result_rows
          EXCEPT
          SELECT 'unexpected_result_rows', CAST(ts_code AS VARCHAR),
                 CAST(trade_date AS DATE)
          FROM {qfq_sql}
        ),
        ranked AS (
          SELECT
            rule_name,
            ts_code,
            strftime(trade_date, '%Y-%m-%d') AS trade_date,
            row_number() OVER (
              PARTITION BY rule_name ORDER BY ts_code, trade_date
            ) AS sample_number
          FROM violations
        )
        SELECT rule_name, ts_code, trade_date
        FROM ranked
        WHERE sample_number <= {AUDIT_SAMPLE_LIMIT}
        ORDER BY rule_name, sample_number
        """
    ).fetchall()
    return _failure_sample_mapping(rows)


def _state_failure_samples(
    *,
    connection: Any,
    state_sql: str,
    lifecycle_sql: str,
    trade_date: str,
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    date_sql = duckdb_string(trade_date)
    rows = connection.execute(
        f"""
        WITH state_rows AS (
          SELECT * FROM {state_sql}
        ),
        valid_lifecycle AS (
          SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
          FROM {lifecycle_sql}
          WHERE CAST(is_cny_stock AS BOOLEAN)
            AND CAST(list_date AS DATE) <= DATE {date_sql}
            AND (
              delist_date IS NULL OR CAST(delist_date AS DATE) > DATE {date_sql}
            )
        ),
        duplicate_keys AS (
          SELECT ts_code, trade_date
          FROM state_rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        ),
        violations AS (
          SELECT 'partition_date_matches' AS rule_name, ts_code, trade_date
          FROM state_rows
          WHERE trade_date IS NULL OR trade_date != DATE {date_sql}
          UNION ALL
          SELECT 'required_columns_non_null', ts_code, trade_date
          FROM state_rows
          WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
             OR state_source_trade_date IS NULL OR observed_on_partition IS NULL
             OR short_upper_raw IS NULL OR short_lower_raw IS NULL
             OR short_state IS NULL OR long_upper_raw IS NULL
             OR long_lower_raw IS NULL OR long_state IS NULL
             OR combined_state IS NULL OR formula_version IS NULL
          UNION ALL
          SELECT 'unique_ts_code_trade_date', state_rows.ts_code,
                 state_rows.trade_date
          FROM state_rows
          JOIN duplicate_keys USING (ts_code, trade_date)
          UNION ALL
          SELECT 'raw_channel_values_valid', ts_code, trade_date
          FROM state_rows
          WHERE NOT isfinite(short_upper_raw) OR NOT isfinite(short_lower_raw)
             OR NOT isfinite(long_upper_raw) OR NOT isfinite(long_lower_raw)
             OR short_upper_raw <= 0 OR short_lower_raw <= 0
             OR long_upper_raw <= 0 OR long_lower_raw <= 0
             OR short_upper_raw < short_lower_raw
             OR long_upper_raw < long_lower_raw
          UNION ALL
          SELECT 'state_enums_valid', ts_code, trade_date
          FROM state_rows
          WHERE short_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
             OR long_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
             OR combined_state NOT IN (
               'UNKNOWN', 'UP_UP', 'UP_DOWN', 'DOWN_UP', 'DOWN_DOWN'
             )
          UNION ALL
          SELECT 'combined_state_consistent', ts_code, trade_date
          FROM state_rows
          WHERE combined_state != CASE
            WHEN short_state = 'UNKNOWN' OR long_state = 'UNKNOWN'
              THEN 'UNKNOWN'
            ELSE short_state || '_' || long_state
          END
          UNION ALL
          SELECT 'state_source_date_valid', ts_code, trade_date
          FROM state_rows
          WHERE state_source_trade_date > trade_date
             OR (observed_on_partition AND state_source_trade_date != trade_date)
          UNION ALL
          SELECT 'formula_version_matches', ts_code, trade_date
          FROM state_rows
          WHERE formula_version != {duckdb_string(FORMULA_VERSION)}
          UNION ALL
          SELECT 'lifecycle_membership_valid', state_rows.ts_code,
                 state_rows.trade_date
          FROM state_rows
          LEFT JOIN valid_lifecycle USING (ts_code)
          WHERE valid_lifecycle.ts_code IS NULL
        ),
        ranked AS (
          SELECT
            rule_name,
            ts_code,
            strftime(trade_date, '%Y-%m-%d') AS trade_date,
            row_number() OVER (
              PARTITION BY rule_name ORDER BY ts_code, trade_date
            ) AS sample_number
          FROM violations
        )
        SELECT rule_name, ts_code, trade_date
        FROM ranked
        WHERE sample_number <= {AUDIT_SAMPLE_LIMIT}
        ORDER BY rule_name, sample_number
        """
    ).fetchall()
    return _failure_sample_mapping(rows)


def _coverage_failure_samples(
    *,
    connection: Any,
    state_sql: str,
    qfq_sql: str,
    lifecycle_sql: str,
    previous_sql: str,
    trade_date: str,
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    date_sql = duckdb_string(trade_date)
    rows = connection.execute(
        f"""
        WITH valid_lifecycle AS (
          SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
          FROM {lifecycle_sql}
          WHERE CAST(is_cny_stock AS BOOLEAN)
            AND CAST(list_date AS DATE) <= DATE {date_sql}
            AND (
              delist_date IS NULL OR CAST(delist_date AS DATE) > DATE {date_sql}
            )
        ),
        qfq_codes AS (
          SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
          FROM {qfq_sql}
          WHERE CAST(trade_date AS DATE) = DATE {date_sql}
        ),
        previous_codes AS (
          SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
          FROM {previous_sql}
        ),
        expected_carry AS (
          SELECT previous_codes.ts_code
          FROM previous_codes
          JOIN valid_lifecycle USING (ts_code)
          LEFT JOIN qfq_codes USING (ts_code)
          WHERE qfq_codes.ts_code IS NULL
        ),
        expected_state AS (
          SELECT ts_code, true AS observed_on_partition FROM qfq_codes
          UNION ALL
          SELECT ts_code, false AS observed_on_partition FROM expected_carry
        ),
        actual_state AS (
          SELECT CAST(ts_code AS VARCHAR) AS ts_code,
                 CAST(observed_on_partition AS BOOLEAN) AS observed_on_partition
          FROM {state_sql}
          WHERE CAST(trade_date AS DATE) = DATE {date_sql}
        ),
        violations AS (
          SELECT 'missing_state' AS rule_name, expected_state.ts_code,
                 DATE {date_sql} AS trade_date
          FROM expected_state
          LEFT JOIN actual_state USING (ts_code, observed_on_partition)
          WHERE actual_state.ts_code IS NULL
          UNION ALL
          SELECT 'unexpected_state', actual_state.ts_code, DATE {date_sql}
          FROM actual_state
          LEFT JOIN expected_state USING (ts_code, observed_on_partition)
          WHERE expected_state.ts_code IS NULL
        ),
        ranked AS (
          SELECT
            rule_name,
            ts_code,
            strftime(trade_date, '%Y-%m-%d') AS trade_date,
            row_number() OVER (
              PARTITION BY rule_name ORDER BY ts_code
            ) AS sample_number
          FROM violations
        )
        SELECT rule_name, ts_code, trade_date
        FROM ranked
        WHERE sample_number <= {AUDIT_SAMPLE_LIMIT}
        ORDER BY rule_name, sample_number
        """
    ).fetchall()
    return _failure_sample_mapping(rows)


def _failure_sample_mapping(
    rows: list[tuple[Any, ...]],
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    rule_names = tuple(dict.fromkeys(str(row[0]) for row in rows))
    return {
        rule_name: tuple(
            {"ts_code": str(row[1]), "trade_date": str(row[2])}
            for row in rows
            if str(row[0]) == rule_name
        )
        for rule_name in rule_names
    }


def _missing_file_audit(
    *,
    rule_name: str,
    missing_paths: tuple[Path, ...],
) -> StockDailyTrendChannelAudit:
    missing_count = len(missing_paths)
    return StockDailyTrendChannelAudit(
        passed=False,
        checked_row_count=0,
        failed_row_count=missing_count,
        source_row_count=0,
        output_row_count=0,
        failure_rule_counts={rule_name: missing_count},
        failure_samples={
            rule_name: tuple(
                {"path": str(path)} for path in missing_paths[:AUDIT_SAMPLE_LIMIT]
            )
        },
        observed_columns=(),
    )


def _schema_failure_audit(
    *,
    observed_schema: tuple[tuple[str, str], ...],
    output_row_count: int,
    source_row_count: int,
) -> StockDailyTrendChannelAudit:
    return StockDailyTrendChannelAudit(
        passed=False,
        checked_row_count=output_row_count,
        failed_row_count=1,
        source_row_count=source_row_count,
        output_row_count=output_row_count,
        failure_rule_counts={"schema_matches_contract": 1},
        failure_samples={
            "schema_matches_contract": (
                {
                    "observed_schema": [
                        [column_name, column_type]
                        for column_name, column_type in observed_schema
                    ]
                },
            )
        },
        observed_columns=tuple(column[0] for column in observed_schema),
    )


def _partition_file_path_audit(
    *,
    connection: Any,
    output_path: Path,
    source_path: Path,
    trade_date: str,
) -> StockDailyTrendChannelAudit | None:
    partition_files = tuple(sorted(output_path.parent.glob("*.parquet")))
    path_matches = output_path.parent.name == f"trade_date={trade_date}"
    single_file_matches = len(partition_files) == 1 and partition_files[0] == output_path
    if path_matches and single_file_matches:
        return None
    output_row_count = _parquet_row_count(connection, output_path)
    source_row_count = _parquet_row_count(connection, source_path)
    failure_rule_counts = {
        "partition_path_matches": int(not path_matches),
        "single_partition_file": int(not single_file_matches),
    }
    return StockDailyTrendChannelAudit(
        passed=False,
        checked_row_count=output_row_count,
        failed_row_count=sum(failure_rule_counts.values()),
        source_row_count=source_row_count,
        output_row_count=output_row_count,
        failure_rule_counts=failure_rule_counts,
        failure_samples={
            "partition_file_contract": tuple(
                {"path": str(path)}
                for path in partition_files[:AUDIT_SAMPLE_LIMIT]
            )
        },
        observed_columns=tuple(
            column[0] for column in _parquet_schema(connection, output_path)
        ),
    )


def _parquet_schema(connection: Any, path: Path) -> tuple[tuple[str, str], ...]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return tuple((str(row[0]), str(row[1]).upper()) for row in rows)


def _parquet_row_count(connection: Any, path: Path) -> int:
    return int(
        connection.execute(
            f"SELECT count(*) FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchone()[0]
    )


def _normalize_trade_date(value: str) -> str:
    normalized = str(value).strip()
    parsed = date.fromisoformat(normalized)
    if parsed.isoformat() != normalized:
        raise ValueError("trade_date must be an ISO date")
    return normalized


def _empty_previous_state_rows_sql() -> str:
    return """(
      SELECT
        CAST(NULL AS VARCHAR) AS ts_code,
        CAST(NULL AS DATE) AS trade_date,
        CAST(NULL AS DATE) AS state_source_trade_date,
        CAST(NULL AS BOOLEAN) AS observed_on_partition,
        CAST(NULL AS DOUBLE) AS short_upper_raw,
        CAST(NULL AS DOUBLE) AS short_lower_raw,
        CAST(NULL AS VARCHAR) AS short_state,
        CAST(NULL AS DOUBLE) AS long_upper_raw,
        CAST(NULL AS DOUBLE) AS long_lower_raw,
        CAST(NULL AS VARCHAR) AS long_state,
        CAST(NULL AS VARCHAR) AS combined_state,
        CAST(NULL AS VARCHAR) AS formula_version
      WHERE false
    )"""


def write_stock_daily_trend_channel_daily_partition(
    *,
    connection: Any,
    trade_date: str,
    qfq_source_path: Path,
    stock_basic_path: Path,
    stock_lifecycle_path: Path,
    previous_trade_date: str | None,
    previous_state_path: Path | None,
    result_candidate_path: Path,
    state_candidate_path: Path,
    result_target_path: Path,
    state_target_path: Path,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> StockDailyTrendChannelWriteResult:
    """Write, audit, and promote one paired daily result/state partition."""

    started_at = perf_counter()
    normalized_trade_date = _normalize_trade_date(trade_date)
    normalized_previous_trade_date = (
        _normalize_trade_date(previous_trade_date)
        if previous_trade_date is not None
        else None
    )
    _assert_daily_path_contracts(
        qfq_source_path=qfq_source_path,
        stock_basic_path=stock_basic_path,
        stock_lifecycle_path=stock_lifecycle_path,
        previous_state_path=previous_state_path,
        result_candidate_path=result_candidate_path,
        state_candidate_path=state_candidate_path,
        result_target_path=result_target_path,
        state_target_path=state_target_path,
    )
    _prepare_daily_output_directories(
        result_candidate_path=result_candidate_path,
        state_candidate_path=state_candidate_path,
        result_target_path=result_target_path,
        state_target_path=state_target_path,
    )
    _assert_same_filesystem(
        candidate_path=result_candidate_path,
        target_path=result_target_path,
    )
    _assert_same_filesystem(
        candidate_path=state_candidate_path,
        target_path=state_target_path,
    )
    _assert_daily_disk_capacity(
        staging_path=result_candidate_path,
        qfq_source_path=qfq_source_path,
        stock_lifecycle_path=stock_lifecycle_path,
        previous_state_path=previous_state_path,
    )
    source_row_count = _validate_daily_source_inputs(
        connection=connection,
        trade_date=normalized_trade_date,
        qfq_source_path=qfq_source_path,
        stock_basic_path=stock_basic_path,
        stock_lifecycle_path=stock_lifecycle_path,
        previous_trade_date=normalized_previous_trade_date,
        previous_state_path=previous_state_path,
    )
    _create_daily_work_relations(
        connection=connection,
        trade_date=normalized_trade_date,
        qfq_source_path=qfq_source_path,
        stock_lifecycle_path=stock_lifecycle_path,
        previous_state_path=previous_state_path,
    )
    formula_sql = build_stock_daily_trend_channel_daily_sql(
        "trend_daily_source",
        previous_state_relation=(
            "trend_previous_state" if previous_state_path is not None else None
        ),
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE trend_observed AS {formula_sql}"
    )
    connection.execute(_build_daily_state_output_sql(normalized_trade_date))
    connection.execute(
        copy_query_to_parquet(
            _daily_result_output_sql(),
            result_candidate_path,
        )
    )
    connection.execute(
        copy_query_to_parquet(
            _daily_state_output_sql(),
            state_candidate_path,
        )
    )

    result_audit = audit_stock_daily_trend_channel_result(
        connection=connection,
        result_path=result_candidate_path,
        qfq_source_path=qfq_source_path,
        trade_date=normalized_trade_date,
    )
    state_audit = audit_stock_daily_trend_channel_state(
        connection=connection,
        state_path=state_candidate_path,
        stock_lifecycle_path=stock_lifecycle_path,
        trade_date=normalized_trade_date,
    )
    coverage_audit = audit_stock_daily_trend_channel_state_coverage(
        connection=connection,
        state_path=state_candidate_path,
        qfq_source_path=qfq_source_path,
        stock_lifecycle_path=stock_lifecycle_path,
        previous_state_path=previous_state_path,
        trade_date=normalized_trade_date,
    )
    if not result_audit.passed or not state_audit.passed or not coverage_audit.passed:
        raise ValueError(
            "Stock daily trend-channel candidate audit failed: "
            f"result={dict(result_audit.failure_rule_counts)}, "
            f"state={dict(state_audit.failure_rule_counts)}, "
            f"coverage={dict(coverage_audit.failure_rule_counts)}."
        )
    if result_target_path.exists() or state_target_path.exists():
        raise FileExistsError(
            "Paired stock daily trend-channel target appeared during candidate "
            "validation; refusing partial overwrite."
        )

    temp_spill_bytes = int(
        connection.execute(
            "SELECT coalesce(sum(size), 0) FROM duckdb_temporary_files()"
        ).fetchone()[0]
    )
    if temp_spill_bytes > DAILY_TEMP_SPILL_HARD_LIMIT_BYTES:
        raise RuntimeError(
            "DuckDB temp spill exceeded the daily trend-channel hard limit after "
            f"candidate validation: {temp_spill_bytes} bytes."
        )
    _promote_paired_candidates(
        result_candidate_path=result_candidate_path,
        state_candidate_path=state_candidate_path,
        result_target_path=result_target_path,
        state_target_path=state_target_path,
        replace_file=replace_file,
    )
    return StockDailyTrendChannelWriteResult(
        trade_date=normalized_trade_date,
        qfq_source_path=qfq_source_path,
        previous_state_path=previous_state_path,
        stock_basic_path=stock_basic_path,
        stock_lifecycle_path=stock_lifecycle_path,
        result_path=result_target_path,
        state_path=state_target_path,
        result_candidate_path=result_candidate_path,
        state_candidate_path=state_candidate_path,
        source_row_count=source_row_count,
        output_row_count=result_audit.output_row_count,
        observed_state_row_count=coverage_audit.actual_observed_state_count,
        carried_state_row_count=coverage_audit.actual_carry_state_count,
        uninitialized_lifecycle_code_count=coverage_audit.uninitialized_count,
        result_candidate_bytes=result_target_path.stat().st_size,
        state_candidate_bytes=state_target_path.stat().st_size,
        elapsed_ms=(perf_counter() - started_at) * 1000,
        peak_memory_bytes=None,
        temp_spill_bytes=temp_spill_bytes,
        observed_result_columns=result_audit.observed_columns,
        observed_state_columns=state_audit.observed_columns,
    )


def _assert_daily_path_contracts(
    *,
    qfq_source_path: Path,
    stock_basic_path: Path,
    stock_lifecycle_path: Path,
    previous_state_path: Path | None,
    result_candidate_path: Path,
    state_candidate_path: Path,
    result_target_path: Path,
    state_target_path: Path,
) -> None:
    required_paths = (qfq_source_path, stock_basic_path, stock_lifecycle_path)
    missing_paths = tuple(path for path in required_paths if not path.exists())
    if previous_state_path is not None and not previous_state_path.exists():
        missing_paths = (*missing_paths, previous_state_path)
    if missing_paths:
        raise FileNotFoundError(
            "Missing stock daily trend-channel input files: "
            + ", ".join(str(path) for path in missing_paths)
        )
    existing_targets = tuple(
        path for path in (result_target_path, state_target_path) if path.exists()
    )
    if existing_targets:
        raise FileExistsError(
            "Stock daily trend-channel formal targets are no-overwrite: "
            + ", ".join(str(path) for path in existing_targets)
        )
    existing_candidates = tuple(
        path
        for path in (result_candidate_path, state_candidate_path)
        if path.exists()
    )
    if existing_candidates:
        raise FileExistsError(
            "Run-scoped stock daily trend-channel candidates already exist: "
            + ", ".join(str(path) for path in existing_candidates)
        )


def _prepare_daily_output_directories(
    *,
    result_candidate_path: Path,
    state_candidate_path: Path,
    result_target_path: Path,
    state_target_path: Path,
) -> None:
    result_candidate_path.parent.mkdir(parents=True, exist_ok=True)
    state_candidate_path.parent.mkdir(parents=True, exist_ok=True)
    result_target_path.parent.mkdir(parents=True, exist_ok=True)
    state_target_path.parent.mkdir(parents=True, exist_ok=True)


def _assert_same_filesystem(*, candidate_path: Path, target_path: Path) -> None:
    if candidate_path.parent.stat().st_dev != target_path.parent.stat().st_dev:
        raise RuntimeError(
            "Stock daily trend-channel candidate and target must share one "
            "filesystem for atomic os.replace."
        )


def _assert_daily_disk_capacity(
    *,
    staging_path: Path,
    qfq_source_path: Path,
    stock_lifecycle_path: Path,
    previous_state_path: Path | None,
) -> None:
    estimated_candidate_bytes = (
        qfq_source_path.stat().st_size
        + stock_lifecycle_path.stat().st_size
        + (previous_state_path.stat().st_size if previous_state_path is not None else 0)
    )
    required_free_bytes = (
        2 * estimated_candidate_bytes + DAILY_TEMP_SPILL_HARD_LIMIT_BYTES
    )
    free_bytes = shutil.disk_usage(staging_path.parent).free
    if free_bytes < required_free_bytes:
        raise RuntimeError(
            "Insufficient staging space for stock daily trend-channel candidates: "
            f"free={free_bytes}, required={required_free_bytes}."
        )


def _validate_daily_source_inputs(
    *,
    connection: Any,
    trade_date: str,
    qfq_source_path: Path,
    stock_basic_path: Path,
    stock_lifecycle_path: Path,
    previous_trade_date: str | None,
    previous_state_path: Path | None,
) -> int:
    qfq_sql = read_parquet(qfq_source_path, hive_partitioning=False)
    basic_sql = read_parquet(stock_basic_path, hive_partitioning=False)
    lifecycle_sql = read_parquet(stock_lifecycle_path, hive_partitioning=False)
    date_sql = duckdb_string(trade_date)
    counts = connection.execute(
        f"""
        WITH qfq_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close
          FROM {qfq_sql}
        ),
        valid_lifecycle AS (
          SELECT CAST(ts_code AS VARCHAR) AS ts_code
          FROM {lifecycle_sql}
          WHERE CAST(is_cny_stock AS BOOLEAN)
            AND CAST(list_date AS DATE) <= DATE {date_sql}
            AND (
              delist_date IS NULL OR CAST(delist_date AS DATE) > DATE {date_sql}
            )
        )
        SELECT
          (SELECT count(*) FROM qfq_rows),
          (SELECT count(*) FROM {basic_sql}),
          (SELECT count(*) FROM valid_lifecycle),
          (SELECT coalesce(sum(row_count), 0) FROM (
            SELECT count(*) AS row_count FROM qfq_rows
            GROUP BY ts_code, trade_date HAVING count(*) > 1
          )),
          (SELECT count(*) FROM qfq_rows
           WHERE trade_date IS NULL OR trade_date != DATE {date_sql}),
          (SELECT count(*) FROM qfq_rows
           WHERE ts_code IS NULL OR trim(ts_code) = ''
              OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
              OR NOT isfinite(open) OR NOT isfinite(high)
              OR NOT isfinite(low) OR NOT isfinite(close)
              OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
              OR low > least(open, close) OR greatest(open, close) > high),
          (SELECT count(*) FROM qfq_rows
           LEFT JOIN valid_lifecycle USING (ts_code)
           WHERE valid_lifecycle.ts_code IS NULL),
          (SELECT coalesce(sum(row_count), 0) FROM (
            SELECT count(*) AS row_count FROM valid_lifecycle
            GROUP BY ts_code HAVING count(*) > 1
          ))
        """
    ).fetchone()
    source_row_count = int(counts[0])
    basic_row_count = int(counts[1])
    lifecycle_row_count = int(counts[2])
    failure_counts = {
        "qfq_row_count_positive": int(source_row_count <= 0),
        "qfq_row_limit": int(source_row_count > DAILY_SOURCE_ROW_HARD_LIMIT),
        "stock_basic_row_count_positive": int(basic_row_count <= 0),
        "stock_basic_row_limit": int(basic_row_count > DAILY_SOURCE_ROW_HARD_LIMIT),
        "lifecycle_row_count_positive": int(lifecycle_row_count <= 0),
        "lifecycle_row_limit": int(
            lifecycle_row_count > DAILY_SOURCE_ROW_HARD_LIMIT
        ),
        "qfq_unique_key": int(counts[3]),
        "qfq_partition_date_matches": int(counts[4]),
        "qfq_ohlc_valid": int(counts[5]),
        "qfq_lifecycle_membership": int(counts[6]),
        "lifecycle_unique_code": int(counts[7]),
    }
    if any(failure_counts.values()):
        raise ValueError(
            "Stock daily trend-channel source validation failed: "
            f"{failure_counts}."
        )
    if (previous_trade_date is None) != (previous_state_path is None):
        raise ValueError(
            "previous_trade_date and previous_state_path must either both be set "
            "or both be absent."
        )
    if previous_state_path is not None and previous_trade_date is not None:
        previous_audit = audit_stock_daily_trend_channel_state(
            connection=connection,
            state_path=previous_state_path,
            stock_lifecycle_path=stock_lifecycle_path,
            trade_date=previous_trade_date,
        )
        if not previous_audit.passed:
            raise ValueError(
                "Previous stock daily trend-channel state is invalid: "
                f"{dict(previous_audit.failure_rule_counts)}."
            )
    return source_row_count


def _create_daily_work_relations(
    *,
    connection: Any,
    trade_date: str,
    qfq_source_path: Path,
    stock_lifecycle_path: Path,
    previous_state_path: Path | None,
) -> None:
    date_sql = duckdb_string(trade_date)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW trend_daily_source AS
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(trade_date AS DATE) AS trade_date,
          CAST(open AS DOUBLE) AS open,
          CAST(high AS DOUBLE) AS high,
          CAST(low AS DOUBLE) AS low,
          CAST(close AS DOUBLE) AS close
        FROM {read_parquet(qfq_source_path, hive_partitioning=False)}
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW trend_valid_lifecycle AS
        SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
        FROM {read_parquet(stock_lifecycle_path, hive_partitioning=False)}
        WHERE CAST(is_cny_stock AS BOOLEAN)
          AND CAST(list_date AS DATE) <= DATE {date_sql}
          AND (delist_date IS NULL OR CAST(delist_date AS DATE) > DATE {date_sql})
        """
    )
    previous_sql = (
        read_parquet(previous_state_path, hive_partitioning=False)
        if previous_state_path is not None
        else _empty_previous_state_rows_sql()
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW trend_previous_state AS
        SELECT * FROM {previous_sql}
        """
    )


def _build_daily_state_output_sql(trade_date: str) -> str:
    date_sql = duckdb_string(trade_date)
    return f"""
    CREATE OR REPLACE TEMP TABLE trend_state_output AS
    SELECT
      ts_code,
      DATE {date_sql} AS trade_date,
      DATE {date_sql} AS state_source_trade_date,
      true AS observed_on_partition,
      CAST(short_upper_raw AS DOUBLE) AS short_upper_raw,
      CAST(short_lower_raw AS DOUBLE) AS short_lower_raw,
      CAST(short_state AS VARCHAR) AS short_state,
      CAST(long_upper_raw AS DOUBLE) AS long_upper_raw,
      CAST(long_lower_raw AS DOUBLE) AS long_lower_raw,
      CAST(long_state AS VARCHAR) AS long_state,
      CAST(combined_state AS VARCHAR) AS combined_state,
      CAST(formula_version AS VARCHAR) AS formula_version
    FROM trend_observed
    UNION ALL
    SELECT
      previous.ts_code,
      DATE {date_sql} AS trade_date,
      previous.state_source_trade_date,
      false AS observed_on_partition,
      previous.short_upper_raw,
      previous.short_lower_raw,
      previous.short_state,
      previous.long_upper_raw,
      previous.long_lower_raw,
      previous.long_state,
      previous.combined_state,
      previous.formula_version
    FROM trend_previous_state AS previous
    JOIN trend_valid_lifecycle AS lifecycle USING (ts_code)
    LEFT JOIN trend_daily_source AS observed USING (ts_code)
    WHERE observed.ts_code IS NULL
    """


def _daily_result_output_sql() -> str:
    return """
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(open AS DOUBLE) AS open,
      CAST(high AS DOUBLE) AS high,
      CAST(low AS DOUBLE) AS low,
      CAST(close AS DOUBLE) AS close,
      CAST(short_upper AS DOUBLE) AS short_upper,
      CAST(short_lower AS DOUBLE) AS short_lower,
      CAST(short_position AS VARCHAR) AS short_position,
      CAST(short_state AS VARCHAR) AS short_state,
      CAST(long_upper AS DOUBLE) AS long_upper,
      CAST(long_lower AS DOUBLE) AS long_lower,
      CAST(long_position AS VARCHAR) AS long_position,
      CAST(long_state AS VARCHAR) AS long_state,
      CAST(combined_state AS VARCHAR) AS combined_state,
      CAST(formula_version AS VARCHAR) AS formula_version
    FROM trend_observed
    ORDER BY ts_code
    """


def _daily_state_output_sql() -> str:
    return """
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(state_source_trade_date AS DATE) AS state_source_trade_date,
      CAST(observed_on_partition AS BOOLEAN) AS observed_on_partition,
      CAST(short_upper_raw AS DOUBLE) AS short_upper_raw,
      CAST(short_lower_raw AS DOUBLE) AS short_lower_raw,
      CAST(short_state AS VARCHAR) AS short_state,
      CAST(long_upper_raw AS DOUBLE) AS long_upper_raw,
      CAST(long_lower_raw AS DOUBLE) AS long_lower_raw,
      CAST(long_state AS VARCHAR) AS long_state,
      CAST(combined_state AS VARCHAR) AS combined_state,
      CAST(formula_version AS VARCHAR) AS formula_version
    FROM trend_state_output
    ORDER BY ts_code
    """


def _promote_paired_candidates(
    *,
    result_candidate_path: Path,
    state_candidate_path: Path,
    result_target_path: Path,
    state_target_path: Path,
    replace_file: Callable[[Path, Path], None],
) -> None:
    replace_file(state_candidate_path, state_target_path)
    try:
        replace_file(result_candidate_path, result_target_path)
    except OSError:
        try:
            os.replace(state_target_path, state_candidate_path)
        except OSError:
            if state_target_path.exists():
                try:
                    shutil.copy2(state_target_path, state_candidate_path)
                except OSError:
                    pass
                state_target_path.unlink()
        raise
