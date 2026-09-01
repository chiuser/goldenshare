"""Pure DuckDB SQL kernel for stock daily trend-channel calculations."""

from __future__ import annotations

import re

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
