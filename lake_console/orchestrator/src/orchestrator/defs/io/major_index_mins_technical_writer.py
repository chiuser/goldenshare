"""DuckDB writer for major-index minute technical and recursive state files."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import ceil
from pathlib import Path
from time import perf_counter

import duckdb

from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_staging_path,
    gold_major_index_mins_technical_state_path,
    gold_major_index_mins_technical_state_staging_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    BOLL_PERIOD,
    BOLL_STD_MULTIPLIER,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_TYPES,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMNS,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_TYPES,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMNS,
    INDICATOR_VERSION,
    KDJ_ALPHA,
    KDJ_PERIOD,
    MA_PERIODS,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    PARAMS_KEY,
    expected_major_index_mins_technical_codes,
    major_index_mins_technical_continuing_codes,
    major_index_mins_technical_seed_codes,
    normalize_major_index_mins_technical_freq,
)

SESSION_BAR_COUNTS = {1: 241, 5: 49, 15: 17, 30: 9, 60: 5, 90: 3, 120: 2}
KDJ_SEED = 50.0


class MajorIndexMinsTechnicalValidationError(RuntimeError):
    """Raised when source, state, staging, or promotion contracts fail."""


@dataclass(frozen=True)
class MajorIndexMinsTechnicalAudit:
    row_count: int
    distinct_code_count: int
    min_trade_time: str | None
    max_trade_time: str | None
    errors: tuple[str, ...]
    failure_samples: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class MajorIndexMinsTechnicalWriteResult:
    freq: int
    trade_date: str
    source_paths: tuple[Path, ...]
    source_trade_dates: tuple[str, ...]
    previous_expected_trade_date: str | None
    previous_state_path: Path | None
    previous_technical_path: Path | None
    seed_codes: tuple[str, ...]
    continuing_codes: tuple[str, ...]
    technical_path: Path
    state_path: Path
    technical_row_count: int
    state_row_count: int
    input_row_count: int
    output_bytes: int
    state_output_bytes: int
    elapsed_ms: float

    def to_details(self) -> dict[str, object]:
        return {
            "freq": self.freq,
            "trade_date": self.trade_date,
            "source_file_count": len(self.source_paths),
            "source_trade_dates": list(self.source_trade_dates),
            "previous_expected_trade_date": self.previous_expected_trade_date,
            "previous_state_path": (
                str(self.previous_state_path)
                if self.previous_state_path is not None
                else None
            ),
            "previous_technical_path": (
                str(self.previous_technical_path)
                if self.previous_technical_path is not None
                else None
            ),
            "seed_code_count": len(self.seed_codes),
            "seed_codes": list(self.seed_codes),
            "continuing_code_count": len(self.continuing_codes),
            "input_row_count": self.input_row_count,
            "technical_row_count": self.technical_row_count,
            "state_row_count": self.state_row_count,
            "technical_output_bytes": self.output_bytes,
            "state_output_bytes": self.state_output_bytes,
            "elapsed_ms": self.elapsed_ms,
        }


def _normalize_trade_date(value: str) -> str:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except (TypeError, ValueError) as error:
        raise MajorIndexMinsTechnicalValidationError(
            f"trade date must be ISO YYYY-MM-DD: {value!r}"
        ) from error


def _normalize_expected_dates(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({_normalize_trade_date(value) for value in values}))
    if not normalized:
        raise MajorIndexMinsTechnicalValidationError(
            "expected trade dates must not be empty"
        )
    return normalized


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise MajorIndexMinsTechnicalValidationError(
            "at least one Silver source path is required"
        )
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False, union_by_name=True)
    values = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{values}], hive_partitioning=false, union_by_name=true)"


def _values_sql(
    values: Sequence[str],
    *,
    column: str,
    alias: str = "values_table",
) -> str:
    if not values:
        return (
            f"(SELECT CAST(NULL AS VARCHAR) AS {column} WHERE false) AS {alias}"
        )
    rows = ", ".join(f"({duckdb_string(value)})" for value in values)
    return f"(VALUES {rows}) AS {alias}({column})"


def _empty_relation(column_types: dict[str, str]) -> str:
    columns = ", ".join(
        f"CAST(NULL AS {type_name}) AS {name}"
        for name, type_name in column_types.items()
    )
    return f"(SELECT {columns} WHERE false)"


def _schema_cast_select(column_types: dict[str, str]) -> str:
    return ", ".join(
        f"CAST({name} AS {type_name}) AS {name}"
        for name, type_name in column_types.items()
    )


def _observed_schema(
    connection: duckdb.DuckDBPyConnection,
    relation_sql: str,
) -> dict[str, str]:
    rows = connection.execute(f"DESCRIBE SELECT * FROM {relation_sql}").fetchall()
    return {str(row[0]): str(row[1]).upper() for row in rows}


def _technical_freq_text(freq: int) -> str:
    return f"{freq}min"


def select_major_index_mins_technical_source_dates(
    *,
    expected_trade_dates: Sequence[str],
    target_trade_date: str,
    freq: int | str,
) -> tuple[str, ...]:
    normalized_dates = _normalize_expected_dates(expected_trade_dates)
    target = _normalize_trade_date(target_trade_date)
    normalized_freq = normalize_major_index_mins_technical_freq(freq)
    if target not in normalized_dates:
        raise MajorIndexMinsTechnicalValidationError(
            f"target date is not an expected trade date: {target}"
        )
    target_index = normalized_dates.index(target)
    prior_partition_count = ceil(
        (max(MA_PERIODS) - 1) / SESSION_BAR_COUNTS[normalized_freq]
    )
    start_index = max(0, target_index - prior_partition_count)
    return normalized_dates[start_index : target_index + 1]


def _validate_previous_inputs(
    connection: duckdb.DuckDBPyConnection,
    *,
    previous_state_sql: str,
    previous_technical_sql: str,
    continuing_codes: Sequence[str],
    previous_trade_date: str | None,
    freq: int,
) -> None:
    if not continuing_codes:
        return
    if previous_trade_date is None:
        raise MajorIndexMinsTechnicalValidationError(
            "continuing codes require a previous expected trade date"
        )
    continuing_values = _values_sql(continuing_codes, column="ts_code")
    state_errors = connection.execute(
        f"""
        WITH expected AS (SELECT ts_code FROM {continuing_values}),
        actual AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            count(*) AS row_count
          FROM {previous_state_sql}
          WHERE CAST(freq AS INTEGER) = {freq}
            AND CAST(trade_date AS DATE) = DATE {duckdb_string(previous_trade_date)}
            AND CAST(params_key AS VARCHAR) = {duckdb_string(PARAMS_KEY)}
            AND CAST(indicator_version AS INTEGER) = {INDICATOR_VERSION}
          GROUP BY ts_code
        )
        SELECT count(*)
        FROM expected
        LEFT JOIN actual USING (ts_code)
        WHERE coalesce(actual.row_count, 0) != 1
        """
    ).fetchone()[0]
    if int(state_errors):
        raise MajorIndexMinsTechnicalValidationError(
            "previous state does not cover every continuing code exactly once: "
            f"date={previous_trade_date}, freq={freq}, count={state_errors}"
        )
    technical_errors = connection.execute(
        f"""
        WITH expected AS (SELECT ts_code FROM {continuing_values}),
        previous_counts AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            max(CAST(observation_count AS INTEGER)) AS observation_count
          FROM {previous_technical_sql}
          WHERE CAST(freq AS INTEGER) = {freq}
            AND CAST(trade_date AS DATE) = DATE {duckdb_string(previous_trade_date)}
          GROUP BY ts_code
        )
        SELECT count(*)
        FROM expected
        LEFT JOIN previous_counts USING (ts_code)
        WHERE previous_counts.observation_count IS NULL
           OR previous_counts.observation_count <= 0
        """
    ).fetchone()[0]
    if int(technical_errors):
        raise MajorIndexMinsTechnicalValidationError(
            "previous technical observation count is missing for continuing codes: "
            f"date={previous_trade_date}, freq={freq}, count={technical_errors}"
        )


def _create_calculation_tables(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_paths: Sequence[Path],
    target_trade_date: str,
    expected_codes: Sequence[str],
    seed_codes: Sequence[str],
    continuing_codes: Sequence[str],
    previous_state_path: Path | None,
    previous_technical_path: Path | None,
    previous_trade_date: str | None,
    freq: int,
) -> int:
    source_sql = _read_parquet_paths(source_paths)
    expected_values = _values_sql(expected_codes, column="ts_code")
    seed_values = _values_sql(
        seed_codes,
        column="ts_code",
        alias="seed_scope",
    )
    previous_state_sql = (
        read_parquet(previous_state_path, hive_partitioning=False)
        if previous_state_path is not None
        else _empty_relation(GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_TYPES)
    )
    previous_technical_sql = (
        read_parquet(previous_technical_path, hive_partitioning=False)
        if previous_technical_path is not None
        else _empty_relation(GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_TYPES)
    )
    _validate_previous_inputs(
        connection,
        previous_state_sql=previous_state_sql,
        previous_technical_sql=previous_technical_sql,
        continuing_codes=continuing_codes,
        previous_trade_date=previous_trade_date,
        freq=freq,
    )

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE major_index_source_bars AS
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          {freq}::INTEGER AS freq,
          CAST(trade_time AS DATE) AS trade_date,
          CAST(trade_time AS TIMESTAMP) AS trade_time,
          CAST(high AS DOUBLE) AS high,
          CAST(low AS DOUBLE) AS low,
          CAST(close AS DOUBLE) AS close
        FROM {source_sql}
        WHERE CAST(freq AS VARCHAR) = {duckdb_string(_technical_freq_text(freq))}
          AND CAST(ts_code AS VARCHAR) IN (SELECT ts_code FROM {expected_values})
          AND CAST(trade_time AS DATE) <= DATE {duckdb_string(target_trade_date)}
        """
    )
    invalid_source_count = int(
        connection.execute(
            """
            SELECT count(*)
            FROM major_index_source_bars
            WHERE ts_code IS NULL
               OR trade_time IS NULL
               OR high IS NULL
               OR low IS NULL
               OR close IS NULL
               OR NOT isfinite(high)
               OR NOT isfinite(low)
               OR NOT isfinite(close)
               OR high < low
            """
        ).fetchone()[0]
    )
    duplicate_source_count = int(
        connection.execute(
            """
            SELECT count(*)
            FROM (
              SELECT ts_code, freq, trade_time
              FROM major_index_source_bars
              GROUP BY ts_code, freq, trade_time
              HAVING count(*) != 1
            )
            """
        ).fetchone()[0]
    )
    if invalid_source_count or duplicate_source_count:
        raise MajorIndexMinsTechnicalValidationError(
            "Silver source rows are invalid: "
            f"invalid={invalid_source_count}, duplicates={duplicate_source_count}"
        )
    target_scope_errors = int(
        connection.execute(
            f"""
            WITH expected AS (SELECT ts_code FROM {expected_values}),
            actual AS (
              SELECT ts_code, count(*) AS row_count
              FROM major_index_source_bars
              WHERE trade_date = DATE {duckdb_string(target_trade_date)}
              GROUP BY ts_code
            )
            SELECT count(*)
            FROM expected
            LEFT JOIN actual USING (ts_code)
            WHERE coalesce(actual.row_count, 0) = 0
            """
        ).fetchone()[0]
    )
    if target_scope_errors:
        raise MajorIndexMinsTechnicalValidationError(
            "target Silver source is missing expected codes: "
            f"date={target_trade_date}, freq={freq}, count={target_scope_errors}"
        )

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE major_index_previous_state AS
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(freq AS INTEGER) AS freq,
          CAST(macd_ema_fast AS DOUBLE) AS macd_ema_fast,
          CAST(macd_ema_slow AS DOUBLE) AS macd_ema_slow,
          CAST(macd_dea AS DOUBLE) AS macd_dea,
          CAST(kdj_k AS DOUBLE) AS kdj_k,
          CAST(kdj_d AS DOUBLE) AS kdj_d
        FROM {previous_state_sql}
        WHERE CAST(freq AS INTEGER) = {freq}
          AND CAST(ts_code AS VARCHAR) IN (SELECT ts_code FROM {expected_values})
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE major_index_previous_observation AS
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          max(CAST(observation_count AS INTEGER)) AS observation_count
        FROM {previous_technical_sql}
        WHERE CAST(freq AS INTEGER) = {freq}
          AND CAST(ts_code AS VARCHAR) IN (SELECT ts_code FROM {expected_values})
        GROUP BY ts_code
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE major_index_rolling_values AS
        SELECT
          *,
          count(close) OVER code_window AS available_observation_count,
          {', '.join(
              f'avg(close) OVER (PARTITION BY ts_code, freq ORDER BY trade_time ROWS BETWEEN {period - 1} PRECEDING AND CURRENT ROW) AS ma_{period}'
              for period in MA_PERIODS
          )},
          avg(close) OVER (
            PARTITION BY ts_code, freq ORDER BY trade_time
            ROWS BETWEEN {BOLL_PERIOD - 1} PRECEDING AND CURRENT ROW
          ) AS boll_mid,
          stddev_pop(close) OVER (
            PARTITION BY ts_code, freq ORDER BY trade_time
            ROWS BETWEEN {BOLL_PERIOD - 1} PRECEDING AND CURRENT ROW
          ) AS boll_sigma,
          max(high) OVER (
            PARTITION BY ts_code, freq ORDER BY trade_time
            ROWS BETWEEN {KDJ_PERIOD - 1} PRECEDING AND CURRENT ROW
          ) AS kdj_hhv,
          min(low) OVER (
            PARTITION BY ts_code, freq ORDER BY trade_time
            ROWS BETWEEN {KDJ_PERIOD - 1} PRECEDING AND CURRENT ROW
          ) AS kdj_llv
        FROM major_index_source_bars
        WINDOW code_window AS (
          PARTITION BY ts_code, freq ORDER BY trade_time
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE major_index_target_rows AS
        SELECT
          rolling.*,
          row_number() OVER (
            PARTITION BY rolling.ts_code, rolling.freq ORDER BY rolling.trade_time
          ) AS target_row_number,
          CASE
            WHEN rolling.kdj_hhv = rolling.kdj_llv THEN 50.0
            ELSE (rolling.close - rolling.kdj_llv)
                 / (rolling.kdj_hhv - rolling.kdj_llv) * 100.0
          END AS kdj_rsv,
          CASE
            WHEN seed_scope.ts_code IS NOT NULL THEN 0
            ELSE coalesce(previous_observation.observation_count, 0)
          END AS observation_base
        FROM major_index_rolling_values AS rolling
        LEFT JOIN {seed_values} USING (ts_code)
        LEFT JOIN major_index_previous_observation AS previous_observation
          USING (ts_code)
        WHERE rolling.trade_date = DATE {duckdb_string(target_trade_date)}
        """
    )

    alpha_fast = 2.0 / (MACD_FAST + 1.0)
    beta_fast = 1.0 - alpha_fast
    alpha_slow = 2.0 / (MACD_SLOW + 1.0)
    beta_slow = 1.0 - alpha_slow
    alpha_signal = 2.0 / (MACD_SIGNAL + 1.0)
    beta_signal = 1.0 - alpha_signal
    beta_kdj = 1.0 - KDJ_ALPHA
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE major_index_recursive_values AS
        WITH seeds AS (
          SELECT
            target.ts_code,
            target.freq,
            coalesce(state.macd_ema_fast, target.close) AS ema_fast_seed,
            coalesce(state.macd_ema_slow, target.close) AS ema_slow_seed,
            coalesce(state.macd_dea, 0.0) AS dea_seed,
            coalesce(state.kdj_k, {KDJ_SEED}) AS k_seed,
            coalesce(state.kdj_d, {KDJ_SEED}) AS d_seed
          FROM major_index_target_rows AS target
          LEFT JOIN major_index_previous_state AS state
            USING (ts_code, freq)
          WHERE target.target_row_number = 1
        ),
        ema_values AS (
          SELECT
            target.*,
            pow({beta_fast}, target_row_number) * (
              seeds.ema_fast_seed
              + {alpha_fast} * sum(close * pow({beta_fast}, -target_row_number))
                OVER code_rows
            ) AS macd_ema_fast,
            pow({beta_slow}, target_row_number) * (
              seeds.ema_slow_seed
              + {alpha_slow} * sum(close * pow({beta_slow}, -target_row_number))
                OVER code_rows
            ) AS macd_ema_slow,
            seeds.dea_seed,
            seeds.k_seed,
            seeds.d_seed
          FROM major_index_target_rows AS target
          INNER JOIN seeds USING (ts_code, freq)
          WINDOW code_rows AS (
            PARTITION BY target.ts_code, target.freq ORDER BY target.target_row_number
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        ),
        dif_values AS (
          SELECT *, macd_ema_fast - macd_ema_slow AS macd_dif
          FROM ema_values
        ),
        dea_values AS (
          SELECT
            *,
            pow({beta_signal}, target_row_number) * (
              dea_seed
              + {alpha_signal} * sum(
                  macd_dif * pow({beta_signal}, -target_row_number)
                ) OVER code_rows
            ) AS macd_dea_value
          FROM dif_values
          WINDOW code_rows AS (
            PARTITION BY ts_code, freq ORDER BY target_row_number
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        ),
        k_values AS (
          SELECT
            *,
            pow({beta_kdj}, target_row_number) * (
              k_seed
              + {KDJ_ALPHA} * sum(
                  kdj_rsv * pow({beta_kdj}, -target_row_number)
                ) OVER code_rows
            ) AS kdj_k_value
          FROM dea_values
          WINDOW code_rows AS (
            PARTITION BY ts_code, freq ORDER BY target_row_number
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        )
        SELECT
          *,
          pow({beta_kdj}, target_row_number) * (
            d_seed
            + {KDJ_ALPHA} * sum(
                kdj_k_value * pow({beta_kdj}, -target_row_number)
              ) OVER code_rows
          ) AS kdj_d_value
        FROM k_values
        WINDOW code_rows AS (
          PARTITION BY ts_code, freq ORDER BY target_row_number
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE major_index_target_technical AS
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(freq AS SMALLINT) AS freq,
          CAST(trade_date AS DATE) AS trade_date,
          CAST(trade_time AS TIMESTAMP) AS trade_time,
          {', '.join(
              f'CAST(CASE WHEN available_observation_count >= {period} THEN ma_{period} END AS DOUBLE) AS ma_{period}'
              for period in MA_PERIODS
          )},
          CAST(CASE WHEN available_observation_count >= {BOLL_PERIOD}
            THEN boll_mid END AS DOUBLE) AS boll_mid,
          CAST(CASE WHEN available_observation_count >= {BOLL_PERIOD}
            THEN boll_mid + {BOLL_STD_MULTIPLIER} * boll_sigma END AS DOUBLE)
            AS boll_upper,
          CAST(CASE WHEN available_observation_count >= {BOLL_PERIOD}
            THEN boll_mid - {BOLL_STD_MULTIPLIER} * boll_sigma END AS DOUBLE)
            AS boll_lower,
          CAST(macd_dif AS DOUBLE) AS macd_dif,
          CAST(macd_dea_value AS DOUBLE) AS macd_dea,
          CAST(2.0 * (macd_dif - macd_dea_value) AS DOUBLE) AS macd,
          CAST(kdj_k_value AS DOUBLE) AS kdj_k,
          CAST(kdj_d_value AS DOUBLE) AS kdj_d,
          CAST(3.0 * kdj_k_value - 2.0 * kdj_d_value AS DOUBLE) AS kdj_j,
          CAST(observation_base + target_row_number AS INTEGER)
            AS observation_count,
          CAST({duckdb_string(PARAMS_KEY)} AS VARCHAR) AS params_key,
          CAST({INDICATOR_VERSION} AS INTEGER) AS indicator_version
        FROM major_index_recursive_values
        ORDER BY ts_code, trade_time
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE major_index_target_state AS
        SELECT {_schema_cast_select(GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_TYPES)}
        FROM (
          SELECT
            ts_code,
            freq,
            trade_date,
            trade_time AS last_trade_time,
            macd_ema_fast,
            macd_ema_slow,
            macd_dea_value AS macd_dea,
            kdj_k_value AS kdj_k,
            kdj_d_value AS kdj_d,
            {duckdb_string(PARAMS_KEY)} AS params_key,
            {INDICATOR_VERSION} AS indicator_version
          FROM major_index_recursive_values
          QUALIFY row_number() OVER (
            PARTITION BY ts_code, freq ORDER BY trade_time DESC
          ) = 1
        )
        ORDER BY ts_code
        """
    )
    return int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM major_index_source_bars
            WHERE trade_date = DATE {duckdb_string(target_trade_date)}
            """
        ).fetchone()[0]
    )


def audit_major_index_mins_technical_relation(
    connection: duckdb.DuckDBPyConnection,
    *,
    relation_sql: str,
    expected_codes: Sequence[str],
    freq: int,
    trade_date: str,
    expected_row_count: int | None = None,
) -> MajorIndexMinsTechnicalAudit:
    errors: list[str] = []
    expected_schema = {
        name: type_name.upper()
        for name, type_name in GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_TYPES.items()
    }
    if _observed_schema(connection, relation_sql) != expected_schema:
        errors.append("schema")
    row = connection.execute(
        f"""
        SELECT
          count(*),
          count(DISTINCT ts_code),
          min(CAST(trade_time AS VARCHAR)),
          max(CAST(trade_time AS VARCHAR))
        FROM {relation_sql}
        """
    ).fetchone()
    row_count = int(row[0])
    distinct_code_count = int(row[1])
    if expected_row_count is not None and row_count != expected_row_count:
        errors.append("row_count")
    expected_values = _values_sql(expected_codes, column="ts_code")
    scope_mismatch_count = int(
        connection.execute(
            f"""
            WITH actual AS (
              SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
              FROM {relation_sql}
            ), expected AS (SELECT ts_code FROM {expected_values})
            SELECT count(*) FROM (
              (SELECT * FROM actual EXCEPT SELECT * FROM expected)
              UNION ALL
              (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            )
            """
        ).fetchone()[0]
    )
    if scope_mismatch_count:
        errors.append("code_scope")
    duplicate_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT ts_code, freq, trade_time
              FROM {relation_sql}
              GROUP BY ts_code, freq, trade_time
              HAVING count(*) != 1
            )
            """
        ).fetchone()[0]
    )
    if duplicate_count:
        errors.append("key_integrity")
    required = (
        "ts_code", "freq", "trade_date", "trade_time", "macd_dif", "macd_dea",
        "macd", "kdj_k", "kdj_d", "kdj_j", "observation_count", "params_key",
        "indicator_version",
    )
    required_null_sql = " OR ".join(f"{column} IS NULL" for column in required)
    invalid_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {relation_sql}
            WHERE {required_null_sql}
               OR CAST(freq AS INTEGER) != {freq}
               OR CAST(trade_date AS DATE) != DATE {duckdb_string(trade_date)}
               OR params_key != {duckdb_string(PARAMS_KEY)}
               OR indicator_version != {INDICATOR_VERSION}
               OR observation_count <= 0
               OR NOT isfinite(macd_dif)
               OR NOT isfinite(macd_dea)
               OR NOT isfinite(macd)
               OR NOT isfinite(kdj_k)
               OR NOT isfinite(kdj_d)
               OR NOT isfinite(kdj_j)
            """
        ).fetchone()[0]
    )
    if invalid_count:
        errors.append("partition_frequency_and_finite")
    warmup_rules = [
        f"((observation_count < {period}) != (ma_{period} IS NULL))"
        for period in MA_PERIODS
    ]
    warmup_rules.extend(
        (
            (
                f"(observation_count < {BOLL_PERIOD} AND NOT "
                "(boll_mid IS NULL AND boll_upper IS NULL "
                "AND boll_lower IS NULL))"
            ),
            (
                f"(observation_count >= {BOLL_PERIOD} AND "
                "(boll_mid IS NULL OR boll_upper IS NULL "
                "OR boll_lower IS NULL))"
            ),
        )
    )
    finite_columns = [f"ma_{period}" for period in MA_PERIODS]
    finite_columns.extend(("boll_mid", "boll_upper", "boll_lower"))
    finite_rules = " OR ".join(
        f"({column} IS NOT NULL AND NOT isfinite({column}))"
        for column in finite_columns
    )
    warmup_count = int(
        connection.execute(
            f"SELECT count(*) FROM {relation_sql} WHERE "
            f"{' OR '.join(warmup_rules)} OR {finite_rules}"
        ).fetchone()[0]
    )
    if warmup_count:
        errors.append("warmup")
    return MajorIndexMinsTechnicalAudit(
        row_count=row_count,
        distinct_code_count=distinct_code_count,
        min_trade_time=str(row[2]) if row[2] is not None else None,
        max_trade_time=str(row[3]) if row[3] is not None else None,
        errors=tuple(errors),
        failure_samples=tuple(
            {"rule": name, "count": count}
            for name, count in (
                ("scope", scope_mismatch_count),
                ("duplicate", duplicate_count),
                ("invalid", invalid_count),
                ("warmup", warmup_count),
            )
            if count
        ),
    )


def audit_major_index_mins_technical_state_relation(
    connection: duckdb.DuckDBPyConnection,
    *,
    relation_sql: str,
    expected_codes: Sequence[str],
    freq: int,
    trade_date: str,
    technical_relation_sql: str,
) -> MajorIndexMinsTechnicalAudit:
    errors: list[str] = []
    expected_schema = {
        name: type_name.upper()
        for name, type_name in GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_TYPES.items()
    }
    if _observed_schema(connection, relation_sql) != expected_schema:
        errors.append("schema")
    row = connection.execute(
        f"""
        SELECT
          count(*), count(DISTINCT ts_code),
          min(CAST(last_trade_time AS VARCHAR)),
          max(CAST(last_trade_time AS VARCHAR))
        FROM {relation_sql}
        """
    ).fetchone()
    row_count = int(row[0])
    distinct_code_count = int(row[1])
    expected_values = _values_sql(expected_codes, column="ts_code")
    invalid_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM {relation_sql}
            WHERE ts_code IS NULL OR last_trade_time IS NULL
               OR macd_ema_fast IS NULL OR macd_ema_slow IS NULL
               OR macd_dea IS NULL OR kdj_k IS NULL OR kdj_d IS NULL
               OR CAST(freq AS INTEGER) != {freq}
               OR CAST(trade_date AS DATE) != DATE {duckdb_string(trade_date)}
               OR params_key != {duckdb_string(PARAMS_KEY)}
               OR indicator_version != {INDICATOR_VERSION}
               OR NOT isfinite(macd_ema_fast)
               OR NOT isfinite(macd_ema_slow)
               OR NOT isfinite(macd_dea)
               OR NOT isfinite(kdj_k)
               OR NOT isfinite(kdj_d)
            """
        ).fetchone()[0]
    )
    duplicate_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT ts_code, freq, trade_date
              FROM {relation_sql}
              GROUP BY ts_code, freq, trade_date
              HAVING count(*) != 1
            )
            """
        ).fetchone()[0]
    )
    scope_mismatch_count = int(
        connection.execute(
            f"""
            WITH actual AS (
              SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
              FROM {relation_sql}
            ), expected AS (SELECT ts_code FROM {expected_values})
            SELECT count(*) FROM (
              (SELECT * FROM actual EXCEPT SELECT * FROM expected)
              UNION ALL
              (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            )
            """
        ).fetchone()[0]
    )
    last_time_mismatch_count = int(
        connection.execute(
            f"""
            WITH expected AS (
              SELECT ts_code, max(trade_time) AS last_trade_time
              FROM {technical_relation_sql}
              GROUP BY ts_code
            )
            SELECT count(*)
            FROM {relation_sql} AS state
            FULL OUTER JOIN expected
              ON state.ts_code = expected.ts_code
             AND state.last_trade_time = expected.last_trade_time
            WHERE state.ts_code IS NULL OR expected.ts_code IS NULL
            """
        ).fetchone()[0]
    )
    if invalid_count:
        errors.append("contract")
    if duplicate_count:
        errors.append("key_integrity")
    if scope_mismatch_count:
        errors.append("coverage")
    if last_time_mismatch_count:
        errors.append("last_trade_time")
    return MajorIndexMinsTechnicalAudit(
        row_count=row_count,
        distinct_code_count=distinct_code_count,
        min_trade_time=str(row[2]) if row[2] is not None else None,
        max_trade_time=str(row[3]) if row[3] is not None else None,
        errors=tuple(errors),
        failure_samples=tuple(
            {"rule": name, "count": count}
            for name, count in (
                ("invalid", invalid_count),
                ("duplicate", duplicate_count),
                ("scope", scope_mismatch_count),
                ("last_trade_time", last_time_mismatch_count),
            )
            if count
        ),
    )


def major_index_mins_technical_relation_counts(
    *,
    connection: duckdb.DuckDBPyConnection,
    target_relation: str,
    source_relation: str,
    partition_key: str,
    freq: int,
) -> dict[str, int]:
    """Return the row-level failure counts used by technical blocking checks."""

    date_literal = duckdb_string(partition_key)
    freq_text = duckdb_string(f"{freq}min")
    source_coverage = int(
        connection.execute(
            f"""
            WITH source_keys AS (
              SELECT CAST(ts_code AS VARCHAR) AS ts_code,
                     CAST(trade_time AS TIMESTAMP) AS trade_time
              FROM {source_relation}
              WHERE CAST(freq AS VARCHAR) = {freq_text}
                AND CAST(trade_time AS DATE) = DATE {date_literal}
            ), target_keys AS (
              SELECT CAST(ts_code AS VARCHAR) AS ts_code,
                     CAST(trade_time AS TIMESTAMP) AS trade_time
              FROM {target_relation}
            )
            SELECT count(*) FROM (
              (SELECT * FROM source_keys EXCEPT SELECT * FROM target_keys)
              UNION ALL
              (SELECT * FROM target_keys EXCEPT SELECT * FROM source_keys)
            )
            """
        ).fetchone()[0]
    )
    partition_frequency = int(
        connection.execute(
            f"""
            SELECT count(*) FROM {target_relation}
            WHERE CAST(freq AS INTEGER) != {freq}
               OR CAST(trade_date AS DATE) != DATE {date_literal}
               OR CAST(trade_time AS DATE) != DATE {date_literal}
            """
        ).fetchone()[0]
    )
    key_integrity = int(
        connection.execute(
            f"""
            SELECT
              count(*) FILTER (
                WHERE ts_code IS NULL OR freq IS NULL OR trade_time IS NULL
              )
              + count(*) - count(DISTINCT (ts_code, freq, trade_time))
            FROM {target_relation}
            """
        ).fetchone()[0]
    )
    no_future_input = int(
        connection.execute(
            f"""
            WITH source_bounds AS (
              SELECT min(trade_time) AS min_time, max(trade_time) AS max_time
              FROM {source_relation}
              WHERE CAST(freq AS VARCHAR) = {freq_text}
                AND CAST(trade_time AS DATE) = DATE {date_literal}
            )
            SELECT count(*)
            FROM {target_relation}, source_bounds
            WHERE CAST(trade_time AS DATE) > DATE {date_literal}
               OR trade_time < source_bounds.min_time
               OR trade_time > source_bounds.max_time
            """
        ).fetchone()[0]
    )
    return {
        "source_coverage": source_coverage,
        "partition_frequency": partition_frequency,
        "key_integrity": key_integrity,
        "no_future_input": no_future_input,
    }


def major_index_mins_technical_continuity_failure_count(
    *,
    connection: duckdb.DuckDBPyConnection,
    current_technical_relation: str,
    previous_technical_relation: str,
    previous_state_relation: str,
    continuing_codes: Sequence[str],
    freq: int,
    previous_trade_date: str,
) -> int:
    """Return continuing codes that do not inherit the strict previous state."""

    if not continuing_codes:
        return 0
    code_rows = ", ".join(
        f"({duckdb_string(code)})" for code in continuing_codes
    )
    expected = f"(VALUES {code_rows}) AS expected(ts_code)"
    previous_date = duckdb_string(previous_trade_date)
    return int(
        connection.execute(
            f"""
            WITH previous_state AS (
              SELECT ts_code, count(*) AS state_count
              FROM {previous_state_relation}
              WHERE CAST(freq AS INTEGER) = {freq}
                AND CAST(trade_date AS DATE) = DATE {previous_date}
              GROUP BY ts_code
            ), previous_observation AS (
              SELECT ts_code, max(observation_count) AS prior_count
              FROM {previous_technical_relation}
              WHERE CAST(freq AS INTEGER) = {freq}
                AND CAST(trade_date AS DATE) = DATE {previous_date}
              GROUP BY ts_code
            ), current_observation AS (
              SELECT ts_code, min(observation_count) AS current_min
              FROM {current_technical_relation}
              GROUP BY ts_code
            )
            SELECT count(*)
            FROM {expected}
            LEFT JOIN previous_state USING (ts_code)
            LEFT JOIN previous_observation USING (ts_code)
            LEFT JOIN current_observation USING (ts_code)
            WHERE coalesce(state_count, 0) != 1
               OR prior_count IS NULL
               OR current_min != prior_count + 1
            """
        ).fetchone()[0]
    )


def _assert_same_filesystem(staging_path: Path, target_path: Path) -> None:
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if staging_path.parent.stat().st_dev != target_path.parent.stat().st_dev:
        raise MajorIndexMinsTechnicalValidationError(
            "technical staging and target must share one filesystem for os.replace"
        )


def write_major_index_mins_technical_partition(
    *,
    lake_root_path: Path,
    staging_root_path: Path,
    duckdb_resource: DuckDBResource,
    freq: int | str,
    partition_key: str,
    run_id: str,
    expected_trade_dates: Sequence[str],
) -> MajorIndexMinsTechnicalWriteResult:
    started_at = perf_counter()
    normalized_freq = normalize_major_index_mins_technical_freq(freq)
    target_date = _normalize_trade_date(partition_key)
    normalized_dates = _normalize_expected_dates(expected_trade_dates)
    source_dates = select_major_index_mins_technical_source_dates(
        expected_trade_dates=normalized_dates,
        target_trade_date=target_date,
        freq=normalized_freq,
    )
    source_paths = tuple(
        silver_major_index_mins_path(
            lake_root_path,
            _technical_freq_text(normalized_freq),
            trade_date,
        )
        for trade_date in source_dates
    )
    missing_source_paths = tuple(path for path in source_paths if not path.exists())
    if missing_source_paths:
        raise MajorIndexMinsTechnicalValidationError(
            "required Silver history partition is missing: "
            f"samples={[str(path) for path in missing_source_paths[:5]]}"
        )
    target_index = normalized_dates.index(target_date)
    previous_trade_date = (
        normalized_dates[target_index - 1] if target_index > 0 else None
    )
    expected_codes = expected_major_index_mins_technical_codes(target_date)
    seed_codes = major_index_mins_technical_seed_codes(target_date)
    continuing_codes = major_index_mins_technical_continuing_codes(target_date)
    if continuing_codes and previous_trade_date is None:
        raise MajorIndexMinsTechnicalValidationError(
            "strict previous expected trade date is unavailable for "
            f"continuing codes: samples={list(continuing_codes[:5])}"
        )
    previous_state_path = (
        gold_major_index_mins_technical_state_path(
            lake_root_path,
            normalized_freq,
            previous_trade_date,
        )
        if previous_trade_date is not None and continuing_codes
        else None
    )
    previous_technical_path = (
        gold_major_index_mins_technical_path(
            lake_root_path,
            normalized_freq,
            previous_trade_date,
        )
        if previous_trade_date is not None and continuing_codes
        else None
    )
    for previous_path in (previous_state_path, previous_technical_path):
        if previous_path is not None and not previous_path.exists():
            raise MajorIndexMinsTechnicalValidationError(
                f"strict previous-date input is missing: {previous_path}"
            )
    technical_path = gold_major_index_mins_technical_path(
        lake_root_path, normalized_freq, target_date
    )
    state_path = gold_major_index_mins_technical_state_path(
        lake_root_path, normalized_freq, target_date
    )
    technical_staging_path = gold_major_index_mins_technical_staging_path(
        staging_root_path, run_id, normalized_freq, target_date
    )
    state_staging_path = gold_major_index_mins_technical_state_staging_path(
        staging_root_path, run_id, normalized_freq, target_date
    )
    for target_path in (technical_path, state_path):
        if target_path.exists():
            raise MajorIndexMinsTechnicalValidationError(
                f"daily writer refuses to overwrite existing target: {target_path}"
            )
    for staging_path in (technical_staging_path, state_staging_path):
        if staging_path.exists():
            raise MajorIndexMinsTechnicalValidationError(
                f"run-scoped staging target already exists: {staging_path}"
            )
    _assert_same_filesystem(technical_staging_path, technical_path)
    _assert_same_filesystem(state_staging_path, state_path)

    technical_promoted = False
    try:
        with duckdb_resource.connect() as connection:
            input_row_count = _create_calculation_tables(
                connection,
                source_paths=source_paths,
                target_trade_date=target_date,
                expected_codes=expected_codes,
                seed_codes=seed_codes,
                continuing_codes=continuing_codes,
                previous_state_path=previous_state_path,
                previous_technical_path=previous_technical_path,
                previous_trade_date=previous_trade_date,
                freq=normalized_freq,
            )
            technical_columns = ", ".join(GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMNS)
            state_columns = ", ".join(
                GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMNS
            )
            connection.execute(
                f"COPY (SELECT {technical_columns} FROM major_index_target_technical) "
                f"TO {duckdb_string(technical_staging_path)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            connection.execute(
                f"COPY (SELECT {state_columns} FROM major_index_target_state) "
                f"TO {duckdb_string(state_staging_path)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            technical_audit = audit_major_index_mins_technical_relation(
                connection,
                relation_sql=read_parquet(
                    technical_staging_path, hive_partitioning=False
                ),
                expected_codes=expected_codes,
                freq=normalized_freq,
                trade_date=target_date,
                expected_row_count=input_row_count,
            )
            state_audit = audit_major_index_mins_technical_state_relation(
                connection,
                relation_sql=read_parquet(
                    state_staging_path, hive_partitioning=False
                ),
                expected_codes=expected_codes,
                freq=normalized_freq,
                trade_date=target_date,
                technical_relation_sql=read_parquet(
                    technical_staging_path, hive_partitioning=False
                ),
            )
            if technical_audit.errors or state_audit.errors:
                raise MajorIndexMinsTechnicalValidationError(
                    "staged technical/state validation failed: "
                    f"technical={technical_audit.errors}, state={state_audit.errors}"
                )
        if technical_path.exists() or state_path.exists():
            raise MajorIndexMinsTechnicalValidationError(
                "paired target appeared during staging; refusing partial overwrite"
            )
        os.replace(technical_staging_path, technical_path)
        technical_promoted = True
        os.replace(state_staging_path, state_path)
    except Exception:
        for staging_path in (technical_staging_path, state_staging_path):
            if staging_path.exists():
                staging_path.unlink()
        if not technical_promoted and technical_path.exists():
            technical_path.unlink()
        raise

    return MajorIndexMinsTechnicalWriteResult(
        freq=normalized_freq,
        trade_date=target_date,
        source_paths=source_paths,
        source_trade_dates=source_dates,
        previous_expected_trade_date=previous_trade_date,
        previous_state_path=previous_state_path,
        previous_technical_path=previous_technical_path,
        seed_codes=seed_codes,
        continuing_codes=continuing_codes,
        technical_path=technical_path,
        state_path=state_path,
        technical_row_count=technical_audit.row_count,
        state_row_count=state_audit.row_count,
        input_row_count=input_row_count,
        output_bytes=technical_path.stat().st_size,
        state_output_bytes=state_path.stat().st_size,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


__all__ = [
    "MajorIndexMinsTechnicalAudit",
    "MajorIndexMinsTechnicalValidationError",
    "MajorIndexMinsTechnicalWriteResult",
    "audit_major_index_mins_technical_relation",
    "audit_major_index_mins_technical_state_relation",
    "major_index_mins_technical_continuity_failure_count",
    "major_index_mins_technical_relation_counts",
    "select_major_index_mins_technical_source_dates",
    "write_major_index_mins_technical_partition",
]
