"""Pure DuckDB builder and audit for canonical CN A-share Gold minute bars."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from time import perf_counter

import duckdb

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    AUCTION_ANCHOR_ROLE,
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
    REGULAR_SOURCE_ROLE,
    canonical_gold_minute_window_map_sql,
    cn_a_derived_minute_completion_predicate,
    expected_gold_minute_times,
    normalize_cn_a_gold_minute_freq,
)

CANONICAL_GOLD_MINUTE_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "freq": "INTEGER",
    "trade_date": "DATE",
    "trade_time": "TIMESTAMP",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "vol": "DOUBLE",
    "amount": "DOUBLE",
    "exchange": "VARCHAR",
    "vwap": "DOUBLE",
}


class CanonicalGoldMinuteValidationError(ValueError):
    """Raised when a canonical Gold minute input violates the frozen contract."""


@dataclass(frozen=True, slots=True)
class CanonicalGoldMinuteAudit:
    ready: bool
    row_count: int
    expected_row_count: int
    schema_matches: bool
    schema_errors: tuple[str, ...]
    duplicate_key_count: int
    missing_key_count: int
    unexpected_key_count: int
    invalid_partition_count: int
    invalid_frequency_count: int
    invalid_target_time_count: int
    non_1m_0930_row_count: int
    post_close_row_count: int
    invalid_value_count: int
    invalid_exchange_count: int
    elapsed_ms: float

    @property
    def failed_rules(self) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.schema_matches:
            failures.append("schema")
        for name, count in (
            ("row_count", abs(self.row_count - self.expected_row_count)),
            ("duplicate_key", self.duplicate_key_count),
            ("missing_key", self.missing_key_count),
            ("unexpected_key", self.unexpected_key_count),
            ("partition", self.invalid_partition_count),
            ("frequency", self.invalid_frequency_count),
            ("target_time", self.invalid_target_time_count),
            ("non_1m_0930", self.non_1m_0930_row_count),
            ("post_close", self.post_close_row_count),
            ("value_domain", self.invalid_value_count),
            ("exchange", self.invalid_exchange_count),
        ):
            if count:
                failures.append(name)
        return tuple(failures)


def _normalize_partition_key(value: object) -> str:
    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise CanonicalGoldMinuteValidationError(
            f"partition key must be ISO YYYY-MM-DD: {value!r}."
        ) from error
    if text != parsed.isoformat():
        raise CanonicalGoldMinuteValidationError(
            f"partition key must be ISO YYYY-MM-DD: {value!r}."
        )
    return text


def _normalize_partition_keys(values: Sequence[object]) -> tuple[str, ...]:
    normalized = tuple(sorted({_normalize_partition_key(value) for value in values}))
    if not normalized:
        raise CanonicalGoldMinuteValidationError(
            "partition key collection must not be empty."
        )
    return normalized


def _normalize_expected_codes(values: Sequence[object]) -> tuple[str, ...]:
    normalized = tuple(sorted({str(value).strip().upper() for value in values}))
    if not normalized or any(not value for value in normalized):
        raise CanonicalGoldMinuteValidationError(
            "expected code collection must not be empty or contain blank values."
        )
    return normalized


def _values_relation(values: Sequence[str], *, column_name: str) -> str:
    rows = ", ".join(f"({duckdb_string(value)})" for value in values)
    return f"(VALUES {rows}) AS values_relation({column_name})"


def _observed_schema(
    connection: duckdb.DuckDBPyConnection,
    relation_sql: str,
) -> dict[str, str]:
    rows = connection.execute(f"DESCRIBE SELECT * FROM ({relation_sql})").fetchall()
    return {str(row[0]): str(row[1]).upper() for row in rows}


def build_canonical_gold_minute_select_sql(
    *,
    source_relation_sql: str,
    target_freq: int | str,
    partition_key: str,
    price_basis_relation_sql: str | None = None,
) -> str:
    """Build one canonical Gold minute relation without reading or writing files."""

    return build_canonical_gold_minute_batch_select_sql(
        source_relation_sql=source_relation_sql,
        target_freq=target_freq,
        partition_keys=(partition_key,),
        price_basis_relation_sql=price_basis_relation_sql,
    )


def build_canonical_gold_minute_batch_select_sql(
    *,
    source_relation_sql: str,
    target_freq: int | str,
    partition_keys: Sequence[object],
    price_basis_relation_sql: str | None = None,
) -> str:
    """Build canonical Gold bars for a bounded set of trade dates in one scan."""

    normalized_freq = normalize_cn_a_gold_minute_freq(target_freq)
    source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[normalized_freq]
    trade_dates = _normalize_partition_keys(partition_keys)
    trade_dates_sql = ", ".join(
        f"DATE {duckdb_string(trade_date)}" for trade_date in trade_dates
    )
    window_map_sql = canonical_gold_minute_window_map_sql(normalized_freq)
    completion_predicate = cn_a_derived_minute_completion_predicate(
        regular_row_count_column="regular_row_count",
        regular_time_count_column="regular_time_count",
        anchor_row_count_column="anchor_row_count",
        anchor_time_count_column="anchor_time_count",
        expected_regular_count_column="expected_regular_count",
        expected_anchor_count_column="expected_anchor_count",
    )
    if price_basis_relation_sql is None:
        price_basis_cte = """
price_adjusted AS (
  SELECT
    source_rows.ts_code,
    source_rows.source_freq,
    source_rows.trade_date,
    source_rows.trade_time,
    source_rows.open,
    source_rows.high,
    source_rows.low,
    source_rows.close,
    source_rows.vol,
    source_rows.amount,
    source_rows.exchange,
    source_rows.vwap,
    1.0::DOUBLE AS price_multiplier
  FROM source_rows
)
""".strip()
    else:
        price_basis_cte = f"""
price_basis AS MATERIALIZED (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(price_multiplier AS DOUBLE) AS price_multiplier
  FROM ({price_basis_relation_sql})
),
price_adjusted AS (
  SELECT
    source_rows.ts_code,
    source_rows.source_freq,
    source_rows.trade_date,
    source_rows.trade_time,
    source_rows.open,
    source_rows.high,
    source_rows.low,
    source_rows.close,
    source_rows.vol,
    source_rows.amount,
    source_rows.exchange,
    source_rows.vwap,
    price_basis.price_multiplier
  FROM source_rows
  INNER JOIN price_basis
    ON price_basis.ts_code = source_rows.ts_code
   AND price_basis.trade_date = source_rows.trade_date
  WHERE price_basis.price_multiplier IS NOT NULL
    AND isfinite(price_basis.price_multiplier)
    AND price_basis.price_multiplier > 0
)
""".strip()

    return f"""
WITH window_map AS MATERIALIZED (
{window_map_sql}
),
source_rows AS MATERIALIZED (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    TRY_CAST(
      regexp_extract(lower(trim(CAST(freq AS VARCHAR))), '^([0-9]+)', 1)
      AS INTEGER
    ) AS source_freq,
    CAST(trade_time AS DATE) AS trade_date,
    CAST(trade_time AS TIMESTAMP) AS trade_time,
    CAST(open AS DOUBLE) AS open,
    CAST(high AS DOUBLE) AS high,
    CAST(low AS DOUBLE) AS low,
    CAST(close AS DOUBLE) AS close,
    CAST(vol AS DOUBLE) AS vol,
    CAST(amount AS DOUBLE) AS amount,
    CAST(exchange AS VARCHAR) AS exchange,
    CAST(vwap AS DOUBLE) AS vwap
  FROM ({source_relation_sql})
  WHERE CAST(trade_time AS DATE) IN ({trade_dates_sql})
),
{price_basis_cte},
regular_rows AS MATERIALIZED (
  SELECT
    price_adjusted.ts_code,
    price_adjusted.trade_date,
    price_adjusted.trade_time,
    price_adjusted.open * price_adjusted.price_multiplier AS open,
    price_adjusted.high * price_adjusted.price_multiplier AS high,
    price_adjusted.low * price_adjusted.price_multiplier AS low,
    price_adjusted.close * price_adjusted.price_multiplier AS close,
    price_adjusted.vol,
    price_adjusted.amount,
    upper(trim(price_adjusted.exchange)) AS exchange,
    price_adjusted.vwap * price_adjusted.price_multiplier AS vwap,
    window_map.source_role,
    window_map.window_id,
    window_map.target_time,
    window_map.expected_regular_count,
    window_map.expected_anchor_count
  FROM price_adjusted
  INNER JOIN window_map
    ON window_map.source_time = strftime(
      price_adjusted.trade_time,
      '%H:%M:%S'
    )
  WHERE price_adjusted.source_freq = {source_freq}
    AND window_map.source_role = {duckdb_string(REGULAR_SOURCE_ROLE)}
),
anchor_rows AS MATERIALIZED (
  SELECT
    price_adjusted.ts_code,
    price_adjusted.trade_date,
    price_adjusted.trade_time,
    price_adjusted.open * price_adjusted.price_multiplier AS open,
    price_adjusted.high * price_adjusted.price_multiplier AS high,
    price_adjusted.low * price_adjusted.price_multiplier AS low,
    price_adjusted.close * price_adjusted.price_multiplier AS close,
    price_adjusted.vol,
    price_adjusted.amount,
    upper(trim(price_adjusted.exchange)) AS exchange,
    price_adjusted.vwap * price_adjusted.price_multiplier AS vwap,
    window_map.source_role,
    window_map.window_id,
    window_map.target_time,
    window_map.expected_regular_count,
    window_map.expected_anchor_count
  FROM price_adjusted
  INNER JOIN window_map
    ON window_map.source_time = strftime(
      price_adjusted.trade_time,
      '%H:%M:%S'
    )
  WHERE price_adjusted.source_freq = {source_freq}
    AND window_map.source_role = {duckdb_string(AUCTION_ANCHOR_ROLE)}
),
mapped_rows AS MATERIALIZED (
  SELECT
    ts_code,
    trade_date,
    trade_time,
    open,
    high,
    low,
    close,
    vol,
    amount,
    exchange,
    vwap,
    source_role,
    window_id,
    target_time,
    expected_regular_count,
    expected_anchor_count
  FROM regular_rows
  UNION ALL
  SELECT
    ts_code,
    trade_date,
    trade_time,
    open,
    high,
    low,
    close,
    vol,
    amount,
    exchange,
    vwap,
    source_role,
    window_id,
    target_time,
    expected_regular_count,
    expected_anchor_count
  FROM anchor_rows
),
aggregated AS (
  SELECT
    ts_code,
    trade_date,
    exchange,
    window_id,
    target_time,
    expected_regular_count,
    expected_anchor_count,
    count(*) FILTER (
      WHERE source_role = {duckdb_string(REGULAR_SOURCE_ROLE)}
    ) AS regular_row_count,
    count(DISTINCT trade_time) FILTER (
      WHERE source_role = {duckdb_string(REGULAR_SOURCE_ROLE)}
    ) AS regular_time_count,
    count(*) FILTER (
      WHERE source_role = {duckdb_string(AUCTION_ANCHOR_ROLE)}
    ) AS anchor_row_count,
    count(DISTINCT trade_time) FILTER (
      WHERE source_role = {duckdb_string(AUCTION_ANCHOR_ROLE)}
    ) AS anchor_time_count,
    arg_min(open, trade_time) FILTER (
      WHERE source_role = {duckdb_string(REGULAR_SOURCE_ROLE)}
    ) AS regular_open,
    arg_max(close, trade_time) FILTER (
      WHERE source_role = {duckdb_string(REGULAR_SOURCE_ROLE)}
    ) AS regular_close,
    max(high) FILTER (
      WHERE source_role = {duckdb_string(REGULAR_SOURCE_ROLE)}
    ) AS regular_high,
    min(low) FILTER (
      WHERE source_role = {duckdb_string(REGULAR_SOURCE_ROLE)}
    ) AS regular_low,
    max(close) FILTER (
      WHERE source_role = {duckdb_string(AUCTION_ANCHOR_ROLE)}
    ) AS anchor_close,
    sum(vol) AS vol,
    sum(amount) AS amount,
    arg_max(vwap, trade_time) FILTER (
      WHERE source_role = {duckdb_string(REGULAR_SOURCE_ROLE)}
    ) AS regular_vwap
  FROM mapped_rows
  GROUP BY
    ts_code,
    trade_date,
    exchange,
    window_id,
    target_time,
    expected_regular_count,
    expected_anchor_count
  HAVING {completion_predicate}
)
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  {normalized_freq}::INTEGER AS freq,
  CAST(trade_date AS DATE) AS trade_date,
  CAST(
    strftime(trade_date, '%Y-%m-%d') || ' ' || target_time
    AS TIMESTAMP
  ) AS trade_time,
  CAST(
    CASE WHEN expected_anchor_count = 1 THEN anchor_close ELSE regular_open END
    AS DOUBLE
  ) AS open,
  CAST(
    CASE
      WHEN expected_anchor_count = 1 THEN greatest(regular_high, anchor_close)
      ELSE regular_high
    END
    AS DOUBLE
  ) AS high,
  CAST(
    CASE
      WHEN expected_anchor_count = 1 THEN least(regular_low, anchor_close)
      ELSE regular_low
    END
    AS DOUBLE
  ) AS low,
  CAST(regular_close AS DOUBLE) AS close,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount,
  CAST(exchange AS VARCHAR) AS exchange,
  CAST(CASE WHEN {normalized_freq} = 1 THEN regular_vwap ELSE NULL END AS DOUBLE)
    AS vwap
FROM aggregated
ORDER BY ts_code, trade_time
""".strip()


def audit_canonical_gold_minute_relation(
    connection: duckdb.DuckDBPyConnection,
    *,
    relation_sql: str,
    target_freq: int | str,
    partition_key: str,
    expected_codes: Sequence[object],
) -> CanonicalGoldMinuteAudit:
    """Audit exact code/time coverage and core value rules in one set-based query."""

    started_at = perf_counter()
    normalized_freq = normalize_cn_a_gold_minute_freq(target_freq)
    trade_date = _normalize_partition_key(partition_key)
    codes = _normalize_expected_codes(expected_codes)
    target_times = expected_gold_minute_times("SSE", normalized_freq)
    expected_row_count = len(codes) * len(target_times)
    expected_schema = {
        name: type_name.upper()
        for name, type_name in CANONICAL_GOLD_MINUTE_COLUMN_TYPES.items()
    }
    observed_schema = _observed_schema(connection, relation_sql)
    schema_errors = tuple(
        sorted(
            {
                *(
                    f"missing:{name}"
                    for name in expected_schema.keys() - observed_schema.keys()
                ),
                *(
                    f"unexpected:{name}"
                    for name in observed_schema.keys() - expected_schema.keys()
                ),
                *(
                    f"type:{name}:{observed_schema[name]}"
                    for name in expected_schema.keys() & observed_schema.keys()
                    if observed_schema[name] != expected_schema[name]
                ),
            }
        )
    )
    if schema_errors:
        return CanonicalGoldMinuteAudit(
            ready=False,
            row_count=0,
            expected_row_count=expected_row_count,
            schema_matches=False,
            schema_errors=schema_errors,
            duplicate_key_count=0,
            missing_key_count=expected_row_count,
            unexpected_key_count=0,
            invalid_partition_count=0,
            invalid_frequency_count=0,
            invalid_target_time_count=0,
            non_1m_0930_row_count=0,
            post_close_row_count=0,
            invalid_value_count=0,
            invalid_exchange_count=0,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )

    code_values = _values_relation(codes, column_name="ts_code")
    time_values = _values_relation(target_times, column_name="target_time")
    metrics = connection.execute(
        f"""
        WITH actual AS MATERIALIZED (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(freq AS INTEGER) AS freq,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(vol AS DOUBLE) AS vol,
            CAST(amount AS DOUBLE) AS amount,
            upper(trim(CAST(exchange AS VARCHAR))) AS exchange
          FROM ({relation_sql})
        ),
        expected_codes AS (SELECT ts_code FROM {code_values}),
        expected_times AS (SELECT target_time FROM {time_values}),
        expected_keys AS MATERIALIZED (
          SELECT expected_codes.ts_code, expected_times.target_time
          FROM expected_codes CROSS JOIN expected_times
        ),
        actual_keys AS MATERIALIZED (
          SELECT
            ts_code,
            strftime(trade_time, '%H:%M:%S') AS target_time,
            count(*) AS key_row_count
          FROM actual
          GROUP BY ts_code, target_time
        )
        SELECT
          (SELECT count(*) FROM actual) AS row_count,
          (
            SELECT coalesce(sum(key_row_count - 1), 0)
            FROM actual_keys
            WHERE key_row_count > 1
          ) AS duplicate_key_count,
          (
            SELECT count(*)
            FROM expected_keys
            ANTI JOIN actual_keys USING (ts_code, target_time)
          ) AS missing_key_count,
          (
            SELECT count(*)
            FROM actual_keys
            ANTI JOIN expected_keys USING (ts_code, target_time)
          ) AS unexpected_key_count,
          (
            SELECT count(*) FROM actual
            WHERE trade_date != DATE {duckdb_string(trade_date)}
               OR CAST(trade_time AS DATE) != DATE {duckdb_string(trade_date)}
          ) AS invalid_partition_count,
          (
            SELECT count(*) FROM actual WHERE freq != {normalized_freq}
          ) AS invalid_frequency_count,
          (
            SELECT count(*) FROM actual
            WHERE strftime(trade_time, '%H:%M:%S') NOT IN (
              SELECT target_time FROM expected_times
            )
          ) AS invalid_target_time_count,
          (
            SELECT count(*) FROM actual
            WHERE {normalized_freq} != 1
              AND strftime(trade_time, '%H:%M:%S') = '09:30:00'
          ) AS non_1m_0930_row_count,
          (
            SELECT count(*) FROM actual
            WHERE strftime(trade_time, '%H:%M:%S') > '15:00:00'
          ) AS post_close_row_count,
          (
            SELECT count(*) FROM actual
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR vol IS NULL OR amount IS NULL
               OR NOT isfinite(open) OR NOT isfinite(high)
               OR NOT isfinite(low) OR NOT isfinite(close)
               OR NOT isfinite(vol) OR NOT isfinite(amount)
               OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
               OR high < low OR open < low OR open > high
               OR close < low OR close > high OR vol < 0 OR amount < 0
          ) AS invalid_value_count,
          (
            SELECT count(*) FROM actual
            WHERE exchange NOT IN ('SSE', 'SZSE', 'BSE', 'XSHG', 'XSHE')
          ) AS invalid_exchange_count
        """
    ).fetchone()
    counts = tuple(int(value) for value in metrics)
    (
        row_count,
        duplicate_key_count,
        missing_key_count,
        unexpected_key_count,
        invalid_partition_count,
        invalid_frequency_count,
        invalid_target_time_count,
        non_1m_0930_row_count,
        post_close_row_count,
        invalid_value_count,
        invalid_exchange_count,
    ) = counts
    ready = row_count == expected_row_count and not any(counts[1:])
    return CanonicalGoldMinuteAudit(
        ready=ready,
        row_count=row_count,
        expected_row_count=expected_row_count,
        schema_matches=True,
        schema_errors=(),
        duplicate_key_count=duplicate_key_count,
        missing_key_count=missing_key_count,
        unexpected_key_count=unexpected_key_count,
        invalid_partition_count=invalid_partition_count,
        invalid_frequency_count=invalid_frequency_count,
        invalid_target_time_count=invalid_target_time_count,
        non_1m_0930_row_count=non_1m_0930_row_count,
        post_close_row_count=post_close_row_count,
        invalid_value_count=invalid_value_count,
        invalid_exchange_count=invalid_exchange_count,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


__all__ = [
    "CANONICAL_GOLD_MINUTE_COLUMN_TYPES",
    "CanonicalGoldMinuteAudit",
    "CanonicalGoldMinuteValidationError",
    "audit_canonical_gold_minute_relation",
    "build_canonical_gold_minute_select_sql",
]
