"""DuckDB writer for the ``dc_daily`` technical-indicator Gold dataset.

P3 intentionally keeps this module free of Dagster decorators.  The writer is
validated in a temporary lake first; active assets, checks, jobs and sensors
are added only in later phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path
import resource
import sys
from time import perf_counter
from uuid import uuid4

from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    gold_dc_daily_technical_path,
    silver_dc_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
    SILVER_DC_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_board import DC_DAILY_CATEGORIES
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_TECHNICAL_BOLL,
    DC_DAILY_TECHNICAL_HISTORY_START_DATE,
    DC_DAILY_TECHNICAL_INDICATOR_VERSION,
    DC_DAILY_TECHNICAL_KDJ,
    DC_DAILY_TECHNICAL_MACD,
    DC_DAILY_TECHNICAL_MA_PERIODS,
    DC_DAILY_TECHNICAL_PARAMS_KEY,
    DC_DAILY_TECHNICAL_SOURCE_FILE_BATCH_SIZE,
)


class DcDailyTechnicalValidationError(ValueError):
    """Raised when source, output, or staging data violates the P3 contract."""


@dataclass(frozen=True, slots=True)
class DcDailyTechnicalWriteResult:
    trade_date: str
    target_path: Path
    source_file_count: int
    source_row_count: int
    written_row_count: int
    series_count: int
    null_warmup_counts: dict[str, int]
    duplicate_key_count: int
    input_rejection_count: int
    duckdb_elapsed_ms: float
    parquet_write_elapsed_ms: float
    validation_elapsed_ms: float
    total_elapsed_ms: float
    peak_memory_bytes: int
    staging_path: Path | None
    skipped_existing: bool

    def to_metadata(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "target_path": str(self.target_path),
            "source_file_count": self.source_file_count,
            "source_row_count": self.source_row_count,
            "written_row_count": self.written_row_count,
            "series_count": self.series_count,
            "null_warmup_counts": dict(self.null_warmup_counts),
            "duplicate_key_count": self.duplicate_key_count,
            "input_rejection_count": self.input_rejection_count,
            "duckdb_elapsed_ms": round(self.duckdb_elapsed_ms, 3),
            "parquet_write_elapsed_ms": round(self.parquet_write_elapsed_ms, 3),
            "validation_elapsed_ms": round(self.validation_elapsed_ms, 3),
            "total_elapsed_ms": round(self.total_elapsed_ms, 3),
            "peak_memory_bytes": self.peak_memory_bytes,
            "staging_path": str(self.staging_path) if self.staging_path else None,
            "skipped_existing": self.skipped_existing,
            "write_mode": "duckdb_set_based_staging_atomic_replace",
            "params_key": DC_DAILY_TECHNICAL_PARAMS_KEY,
            "indicator_version": DC_DAILY_TECHNICAL_INDICATOR_VERSION,
        }


def _normalize_trade_date(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _expected_schema(schema: tuple[object, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((str(column.name), str(column.type).upper()) for column in schema)


def _read_paths(paths: tuple[Path, ...]) -> str:
    if not paths:
        raise ValueError("At least one parquet path is required.")
    quoted_paths = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{quoted_paths}], hive_partitioning=false)"


def _path_batches(paths: tuple[Path, ...]) -> tuple[tuple[Path, ...], ...]:
    return tuple(
        paths[start : start + DC_DAILY_TECHNICAL_SOURCE_FILE_BATCH_SIZE]
        for start in range(0, len(paths), DC_DAILY_TECHNICAL_SOURCE_FILE_BATCH_SIZE)
    )


def _source_path_batches(
    paths_by_date: tuple[tuple[str, Path], ...],
) -> tuple[tuple[tuple[str, Path], ...], ...]:
    return tuple(
        paths_by_date[start : start + DC_DAILY_TECHNICAL_SOURCE_FILE_BATCH_SIZE]
        for start in range(0, len(paths_by_date), DC_DAILY_TECHNICAL_SOURCE_FILE_BATCH_SIZE)
    )


def _schema_mismatches(connection, relation: str, schema: tuple[object, ...]) -> dict[str, object]:
    observed = tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    )
    expected = _expected_schema(schema)
    return {
        "expected_columns": [name for name, _ in expected],
        "observed_columns": [name for name, _ in observed],
        "expected_types": {name: type_name for name, type_name in expected},
        "observed_types": {name: type_name for name, type_name in observed},
        "mismatch": observed != expected,
    }


def _calendar_dates(connection, calendar_path: Path, target_trade_date: str) -> tuple[str, ...]:
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing Silver trade calendar: {calendar_path}")
    rows = connection.execute(
        f"""
        SELECT CAST(trade_date AS DATE) AS trade_date, count(*) AS row_count
        FROM {read_parquet(calendar_path, hive_partitioning=False)}
        WHERE exchange = 'SSE'
          AND is_open = true
          AND CAST(trade_date AS DATE) >= DATE {duckdb_string(DC_DAILY_TECHNICAL_HISTORY_START_DATE)}
          AND CAST(trade_date AS DATE) <= DATE {duckdb_string(target_trade_date)}
        GROUP BY trade_date
        ORDER BY trade_date
        """
    ).fetchall()
    duplicate_dates = [str(row[0]) for row in rows if int(row[1]) != 1]
    if duplicate_dates:
        raise DcDailyTechnicalValidationError(
            f"Trade calendar has duplicate SSE open dates: {duplicate_dates[:5]}"
        )
    dates = tuple(str(row[0]) for row in rows)
    if target_trade_date not in dates:
        raise DcDailyTechnicalValidationError(
            f"Target trade date is not an expected SSE open date: {target_trade_date}"
        )
    return dates


def _source_sql(paths_by_date: tuple[tuple[str, Path], ...]) -> str:
    selects = tuple(
        f"""
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(trade_date AS DATE) AS trade_date,
          CAST(close AS DOUBLE) AS close,
          CAST(high AS DOUBLE) AS high,
          CAST(low AS DOUBLE) AS low,
          CAST(category AS VARCHAR) AS category,
          DATE {duckdb_string(trade_date)} AS source_partition_date
        FROM {read_parquet(path, hive_partitioning=False)}
        """
        for trade_date, path in paths_by_date
    )
    return "\nUNION ALL\n".join(selects)


def _validate_source_schemas(
    connection,
    *,
    source_paths: tuple[Path, ...],
) -> None:
    for path_batch in _path_batches(source_paths):
        source_schema = _schema_mismatches(
            connection,
            _read_paths(path_batch),
            SILVER_DC_DAILY_SCHEMA,
        )
        if source_schema["mismatch"]:
            raise DcDailyTechnicalValidationError(
                f"Silver dc_daily schema does not match contract: {source_schema}"
            )


def _create_source_in_bounded_batches(
    connection,
    *,
    paths_by_date: tuple[tuple[str, Path], ...],
) -> None:
    for batch_index, source_batch in enumerate(_source_path_batches(paths_by_date)):
        source_sql = _source_sql(source_batch)
        if batch_index == 0:
            connection.execute(
                f"CREATE OR REPLACE TEMP TABLE dc_daily_technical_source AS {source_sql}"
            )
        else:
            connection.execute(f"INSERT INTO dc_daily_technical_source {source_sql}")


def _validate_source(connection, expected_dates: tuple[str, ...], target_trade_date: str) -> dict[str, int]:
    allowed_categories = ", ".join(duckdb_string(value) for value in DC_DAILY_CATEGORIES)
    metrics = connection.execute(
        f"""
        SELECT
          count(*) AS source_row_count,
          count(*) FILTER (
            WHERE trade_date IS NULL OR source_partition_date <> trade_date
          ) AS out_of_partition_count,
          count(*) FILTER (
            WHERE ts_code IS NULL
               OR NOT regexp_full_match(ts_code, '^BK[0-9]{{4}}\\.DC$')
          ) AS invalid_code_count,
          count(*) FILTER (
            WHERE category IS NULL OR category NOT IN ({allowed_categories})
          ) AS invalid_category_count,
          count(*) FILTER (
            WHERE close IS NULL OR high IS NULL OR low IS NULL
               OR NOT isfinite(close) OR NOT isfinite(high) OR NOT isfinite(low)
          ) AS invalid_numeric_count
        FROM dc_daily_technical_source
        """
    ).fetchone()
    row_counts = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            """
            SELECT strftime(source_partition_date, '%Y-%m-%d'), count(*)
            FROM dc_daily_technical_source
            GROUP BY source_partition_date
            """
        ).fetchall()
    }
    missing_or_empty_dates = [trade_date for trade_date in expected_dates if row_counts.get(trade_date, 0) <= 0]
    if missing_or_empty_dates:
        raise DcDailyTechnicalValidationError(
            f"Silver source dates are missing or empty: {missing_or_empty_dates[:5]}"
        )

    source_row_count, out_of_partition, invalid_code, invalid_category, invalid_numeric = (
        int(value or 0) for value in metrics
    )
    duplicate_key_count = int(
        connection.execute(
            """
            SELECT coalesce(sum(row_count - 1), 0)
            FROM (
              SELECT ts_code, trade_date, category, count(*) AS row_count
              FROM dc_daily_technical_source
              GROUP BY ts_code, trade_date, category
              HAVING count(*) > 1
            ) duplicates
            """
        ).fetchone()[0]
        or 0
    )
    target_source_row_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM dc_daily_technical_source
            WHERE trade_date = DATE {duckdb_string(target_trade_date)}
            """
        ).fetchone()[0]
    )
    if any((out_of_partition, invalid_code, invalid_category, invalid_numeric, duplicate_key_count)):
        raise DcDailyTechnicalValidationError(
            "Silver source contract failed: "
            f"out_of_partition_count={out_of_partition}, "
            f"invalid_code_count={invalid_code}, "
            f"invalid_category_count={invalid_category}, "
            f"invalid_numeric_count={invalid_numeric}, "
            f"duplicate_key_count={duplicate_key_count}."
        )
    if source_row_count <= 0 or target_source_row_count <= 0:
        raise DcDailyTechnicalValidationError(
            f"Silver source has no usable rows for {target_trade_date}."
        )
    return {
        "source_row_count": source_row_count,
        "target_source_row_count": target_source_row_count,
        "duplicate_key_count": duplicate_key_count,
        "input_rejection_count": 0,
    }


def _indicator_sql(target_trade_date: str | None) -> str:
    ma_window_columns = ",\n".join(
        f"COUNT(close) OVER (PARTITION BY ts_code, category ORDER BY trade_date "
        f"ROWS BETWEEN {period - 1} PRECEDING AND CURRENT ROW) AS ma_{period}_count,\n"
        f"AVG(close) OVER (PARTITION BY ts_code, category ORDER BY trade_date "
        f"ROWS BETWEEN {period - 1} PRECEDING AND CURRENT ROW) AS ma_{period}_value"
        for period in DC_DAILY_TECHNICAL_MA_PERIODS
    )
    ma_output_columns = ",\n".join(
        f"CASE WHEN observation_count >= {period} THEN CAST(ma_{period}_value AS DOUBLE) "
        f"ELSE NULL::DOUBLE END AS ma_{period}"
        for period in DC_DAILY_TECHNICAL_MA_PERIODS
    )
    boll_period, boll_multiplier = DC_DAILY_TECHNICAL_BOLL
    macd_fast, macd_slow, macd_signal = DC_DAILY_TECHNICAL_MACD
    kdj_period, _, _ = DC_DAILY_TECHNICAL_KDJ
    alpha_fast = 2.0 / (macd_fast + 1.0)
    beta_fast = 1.0 - alpha_fast
    alpha_slow = 2.0 / (macd_slow + 1.0)
    beta_slow = 1.0 - alpha_slow
    alpha_signal = 2.0 / (macd_signal + 1.0)
    beta_signal = 1.0 - alpha_signal
    alpha_k = 1.0 / 3.0
    beta_k = 1.0 - alpha_k
    alpha_d = 1.0 / 3.0
    beta_d = 1.0 - alpha_d
    target_filter = (
        f"WHERE trade_date = DATE {duckdb_string(target_trade_date)}"
        if target_trade_date is not None
        else ""
    )
    return f"""
    WITH ordered AS (
      SELECT
        ts_code,
        trade_date,
        category,
        close,
        high,
        low,
        CAST(row_number() OVER (
          PARTITION BY ts_code, category ORDER BY trade_date
        ) AS INTEGER) AS observation_count,
        first_value(close) OVER (
          PARTITION BY ts_code, category ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS first_close
      FROM dc_daily_technical_source
    ),
    windowed AS (
      SELECT
        ordered.*,
        {ma_window_columns},
        COUNT(close) OVER (
          PARTITION BY ts_code, category ORDER BY trade_date
          ROWS BETWEEN {boll_period - 1} PRECEDING AND CURRENT ROW
        ) AS boll_count,
        AVG(close) OVER (
          PARTITION BY ts_code, category ORDER BY trade_date
          ROWS BETWEEN {boll_period - 1} PRECEDING AND CURRENT ROW
        ) AS boll_mid_value,
        stddev_pop(close) OVER (
          PARTITION BY ts_code, category ORDER BY trade_date
          ROWS BETWEEN {boll_period - 1} PRECEDING AND CURRENT ROW
        ) AS boll_stddev_value,
        max(high) OVER (
          PARTITION BY ts_code, category ORDER BY trade_date
          ROWS BETWEEN {kdj_period - 1} PRECEDING AND CURRENT ROW
        ) AS kdj_hhv,
        min(low) OVER (
          PARTITION BY ts_code, category ORDER BY trade_date
          ROWS BETWEEN {kdj_period - 1} PRECEDING AND CURRENT ROW
        ) AS kdj_llv
      FROM ordered
    ),
    rsv_values AS (
      SELECT
        windowed.*,
        CASE
          WHEN kdj_hhv = kdj_llv THEN 50.0
          ELSE (close - kdj_llv) / (kdj_hhv - kdj_llv) * 100.0
        END AS kdj_rsv
      FROM windowed
    ),
    macd_ema_values AS (
      SELECT
        rsv_values.*,
        pow({beta_fast}, observation_count) * (
          first_close + {alpha_fast} * sum(
            close * pow({beta_fast}, -observation_count)
          ) OVER (
            PARTITION BY ts_code, category ORDER BY trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        ) AS macd_ema_fast,
        pow({beta_slow}, observation_count) * (
          first_close + {alpha_slow} * sum(
            close * pow({beta_slow}, -observation_count)
          ) OVER (
            PARTITION BY ts_code, category ORDER BY trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        ) AS macd_ema_slow
      FROM rsv_values
    ),
    macd_dif_values AS (
      SELECT *, macd_ema_fast - macd_ema_slow AS macd_dif_value
      FROM macd_ema_values
    ),
    macd_values AS (
      SELECT
        macd_dif_values.*,
        {alpha_signal} * pow({beta_signal}, observation_count) * sum(
          macd_dif_value * pow({beta_signal}, -observation_count)
        ) OVER (
          PARTITION BY ts_code, category ORDER BY trade_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS macd_dea_value
      FROM macd_dif_values
    ),
    k_values AS (
      SELECT
        macd_values.*,
        pow({beta_k}, observation_count) * (
          50.0 + {alpha_k} * sum(kdj_rsv * pow({beta_k}, -observation_count)) OVER (
            PARTITION BY ts_code, category ORDER BY trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        ) AS kdj_k_value
      FROM macd_values
    ),
    d_values AS (
      SELECT
        k_values.*,
        pow({beta_d}, observation_count) * (
          50.0 + {alpha_d} * sum(kdj_k_value * pow({beta_d}, -observation_count)) OVER (
            PARTITION BY ts_code, category ORDER BY trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        ) AS kdj_d_value
      FROM k_values
    )
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(category AS VARCHAR) AS category,
      CAST(close AS DOUBLE) AS close,
      {ma_output_columns},
      CAST(kdj_k_value AS DOUBLE) AS kdj_k,
      CAST(kdj_d_value AS DOUBLE) AS kdj_d,
      CAST(3.0 * kdj_k_value - 2.0 * kdj_d_value AS DOUBLE) AS kdj_j,
      CAST(macd_dif_value AS DOUBLE) AS macd_dif,
      CAST(macd_dea_value AS DOUBLE) AS macd_dea,
      CAST(2.0 * (macd_dif_value - macd_dea_value) AS DOUBLE) AS macd,
      CASE WHEN boll_count >= {boll_period} THEN CAST(boll_mid_value AS DOUBLE) ELSE NULL::DOUBLE END AS boll_mid,
      CASE WHEN boll_count >= {boll_period} THEN CAST(boll_mid_value + {boll_multiplier} * boll_stddev_value AS DOUBLE) ELSE NULL::DOUBLE END AS boll_upper,
      CASE WHEN boll_count >= {boll_period} THEN CAST(boll_mid_value - {boll_multiplier} * boll_stddev_value AS DOUBLE) ELSE NULL::DOUBLE END AS boll_lower,
      CAST(observation_count AS INTEGER) AS observation_count,
      CAST({duckdb_string(DC_DAILY_TECHNICAL_PARAMS_KEY)} AS VARCHAR) AS params_key,
      CAST({duckdb_string(DC_DAILY_TECHNICAL_INDICATOR_VERSION)} AS VARCHAR) AS indicator_version
    FROM d_values
    {target_filter}
    """


def _output_metrics(connection, relation: str, target_trade_date: str) -> dict[str, object]:
    rows = connection.execute(
        f"""
        SELECT
          count(*) AS row_count,
          count(*) FILTER (WHERE trade_date IS NULL OR trade_date <> DATE {duckdb_string(target_trade_date)}) AS date_mismatch_count,
          count(*) FILTER (WHERE ts_code IS NULL OR category IS NULL OR close IS NULL) AS invalid_identity_count,
          count(*) FILTER (WHERE params_key <> {duckdb_string(DC_DAILY_TECHNICAL_PARAMS_KEY)} OR indicator_version <> {duckdb_string(DC_DAILY_TECHNICAL_INDICATOR_VERSION)}) AS metadata_mismatch_count,
          count(*) FILTER (WHERE observation_count < 1) AS invalid_observation_count,
          count(*) FILTER (
            WHERE (ma_5 IS NOT NULL AND NOT isfinite(ma_5))
               OR (ma_10 IS NOT NULL AND NOT isfinite(ma_10))
               OR (ma_15 IS NOT NULL AND NOT isfinite(ma_15))
               OR (ma_20 IS NOT NULL AND NOT isfinite(ma_20))
               OR (ma_30 IS NOT NULL AND NOT isfinite(ma_30))
               OR (ma_60 IS NOT NULL AND NOT isfinite(ma_60))
               OR (ma_120 IS NOT NULL AND NOT isfinite(ma_120))
               OR (ma_250 IS NOT NULL AND NOT isfinite(ma_250))
               OR (kdj_k IS NOT NULL AND NOT isfinite(kdj_k))
               OR (kdj_d IS NOT NULL AND NOT isfinite(kdj_d))
               OR (kdj_j IS NOT NULL AND NOT isfinite(kdj_j))
               OR (macd_dif IS NOT NULL AND NOT isfinite(macd_dif))
               OR (macd_dea IS NOT NULL AND NOT isfinite(macd_dea))
               OR (macd IS NOT NULL AND NOT isfinite(macd))
               OR (boll_mid IS NOT NULL AND NOT isfinite(boll_mid))
               OR (boll_upper IS NOT NULL AND NOT isfinite(boll_upper))
               OR (boll_lower IS NOT NULL AND NOT isfinite(boll_lower))
          ) AS invalid_numeric_count,
          count(*) FILTER (WHERE observation_count < 5 AND ma_5 IS NOT NULL) AS invalid_ma_5_warmup_count,
          count(*) FILTER (WHERE observation_count < 10 AND ma_10 IS NOT NULL) AS invalid_ma_10_warmup_count,
          count(*) FILTER (WHERE observation_count < 15 AND ma_15 IS NOT NULL) AS invalid_ma_15_warmup_count,
          count(*) FILTER (WHERE observation_count < 20 AND ma_20 IS NOT NULL) AS invalid_ma_20_warmup_count,
          count(*) FILTER (WHERE observation_count < 30 AND ma_30 IS NOT NULL) AS invalid_ma_30_warmup_count,
          count(*) FILTER (WHERE observation_count < 60 AND ma_60 IS NOT NULL) AS invalid_ma_60_warmup_count,
          count(*) FILTER (WHERE observation_count < 120 AND ma_120 IS NOT NULL) AS invalid_ma_120_warmup_count,
          count(*) FILTER (WHERE observation_count < 250 AND ma_250 IS NOT NULL) AS invalid_ma_250_warmup_count,
          count(*) FILTER (WHERE observation_count < 20 AND (boll_mid IS NOT NULL OR boll_upper IS NOT NULL OR boll_lower IS NOT NULL)) AS invalid_boll_warmup_count,
          count(*) FILTER (WHERE observation_count >= 20 AND (boll_mid IS NULL OR boll_upper IS NULL OR boll_lower IS NULL)) AS missing_boll_post_warmup_count,
          count(*) FILTER (WHERE ma_5 IS NULL) AS null_ma_5_count,
          count(*) FILTER (WHERE ma_10 IS NULL) AS null_ma_10_count,
          count(*) FILTER (WHERE ma_15 IS NULL) AS null_ma_15_count,
          count(*) FILTER (WHERE ma_20 IS NULL) AS null_ma_20_count,
          count(*) FILTER (WHERE ma_30 IS NULL) AS null_ma_30_count,
          count(*) FILTER (WHERE ma_60 IS NULL) AS null_ma_60_count,
          count(*) FILTER (WHERE ma_120 IS NULL) AS null_ma_120_count,
          count(*) FILTER (WHERE ma_250 IS NULL) AS null_ma_250_count,
          count(*) FILTER (WHERE boll_mid IS NULL) AS null_boll_mid_count,
          count(*) FILTER (WHERE boll_upper IS NULL) AS null_boll_upper_count,
          count(*) FILTER (WHERE boll_lower IS NULL) AS null_boll_lower_count
        FROM {relation}
        """
    ).fetchone()
    duplicate_key_count = int(
        connection.execute(
            f"""
            SELECT coalesce(sum(row_count - 1), 0)
            FROM (
              SELECT ts_code, trade_date, category, count(*) AS row_count
              FROM {relation}
              GROUP BY ts_code, trade_date, category
              HAVING count(*) > 1
            ) duplicates
            """
        ).fetchone()[0]
        or 0
    )
    series_count = int(
        connection.execute(
            f"SELECT count(DISTINCT (ts_code, category)) FROM {relation}"
        ).fetchone()[0]
    )
    null_counts = {
        field: int(rows[index] or 0)
        for index, field in enumerate(
            (
                "ma_5",
                "ma_10",
                "ma_15",
                "ma_20",
                "ma_30",
                "ma_60",
                "ma_120",
                "ma_250",
                "boll_mid",
                "boll_upper",
                "boll_lower",
            ),
            start=16,
        )
    }
    return {
        "row_count": int(rows[0] or 0),
        "date_mismatch_count": int(rows[1] or 0),
        "invalid_identity_count": int(rows[2] or 0),
        "metadata_mismatch_count": int(rows[3] or 0),
        "invalid_observation_count": int(rows[4] or 0),
        "invalid_numeric_count": int(rows[5] or 0),
        "duplicate_key_count": duplicate_key_count,
        "series_count": series_count,
        "null_warmup_counts": null_counts,
        "warmup_failures": {
            "ma_5": int(rows[6] or 0),
            "ma_10": int(rows[7] or 0),
            "ma_15": int(rows[8] or 0),
            "ma_20": int(rows[9] or 0),
            "ma_30": int(rows[10] or 0),
            "ma_60": int(rows[11] or 0),
            "ma_120": int(rows[12] or 0),
            "ma_250": int(rows[13] or 0),
            "boll": int(rows[14] or 0),
            "boll_post_warmup": int(rows[15] or 0),
        },
    }


def _validate_output_against_source(
    connection,
    relation: str,
    *,
    target_trade_date: str,
    expected_source_row_count: int,
) -> dict[str, object]:
    metrics = _output_metrics(connection, relation, target_trade_date)
    source_key_difference = int(
        connection.execute(
            f"""
            WITH source_keys AS (
              SELECT ts_code, trade_date, category
              FROM dc_daily_technical_source
              WHERE trade_date = DATE {duckdb_string(target_trade_date)}
            ), output_keys AS (
              SELECT ts_code, trade_date, category FROM {relation}
            ), missing_keys AS (
              SELECT * FROM source_keys EXCEPT SELECT * FROM output_keys
            ), extra_keys AS (
              SELECT * FROM output_keys EXCEPT SELECT * FROM source_keys
            )
            SELECT (SELECT count(*) FROM missing_keys) + (SELECT count(*) FROM extra_keys)
            """
        ).fetchone()[0]
        or 0
    )
    failures = {
        name: value
        for name, value in {
            "row_count": metrics["row_count"] != expected_source_row_count,
            "date_mismatch_count": metrics["date_mismatch_count"],
            "invalid_identity_count": metrics["invalid_identity_count"],
            "metadata_mismatch_count": metrics["metadata_mismatch_count"],
            "invalid_observation_count": metrics["invalid_observation_count"],
            "invalid_numeric_count": metrics["invalid_numeric_count"],
            "duplicate_key_count": metrics["duplicate_key_count"],
            "source_key_difference": source_key_difference,
            **metrics["warmup_failures"],
        }.items()
        if value
    }
    if failures:
        raise DcDailyTechnicalValidationError(
            f"Gold technical output contract failed for {target_trade_date}: {failures}"
        )
    return metrics


def _peak_memory_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def write_gold_dc_daily_technical_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
) -> DcDailyTechnicalWriteResult:
    """Compute and atomically publish one Gold technical-indicator partition."""

    started_at = perf_counter()
    target_trade_date = _normalize_trade_date(partition_key)
    target_path = gold_dc_daily_technical_path(lake_root_path, target_trade_date)
    calendar_path = silver_trade_calendar_path(lake_root_path)

    with duckdb_resource.connect() as connection:
        expected_dates = _calendar_dates(connection, calendar_path, target_trade_date)
        paths_by_date = tuple(
            (trade_date, silver_dc_daily_path(lake_root_path, trade_date))
            for trade_date in expected_dates
        )
        missing_paths = tuple(str(path) for _, path in paths_by_date if not path.exists())
        if missing_paths:
            raise FileNotFoundError(
                f"Missing Silver dc_daily source files: {list(missing_paths[:5])}"
            )

        source_paths = tuple(path for _, path in paths_by_date)
        _validate_source_schemas(connection, source_paths=source_paths)
        _create_source_in_bounded_batches(connection, paths_by_date=paths_by_date)
        source_metrics = _validate_source(connection, expected_dates, target_trade_date)
        target_source_row_count = source_metrics["target_source_row_count"]

        duckdb_elapsed_start = perf_counter()
        if target_path.exists():
            target_relation = read_parquet(target_path, hive_partitioning=False)
            target_schema = _schema_mismatches(connection, target_relation, GOLD_DC_DAILY_TECHNICAL_SCHEMA)
            if target_schema["mismatch"]:
                raise DcDailyTechnicalValidationError(
                    f"Existing Gold technical schema does not match contract: {target_schema}"
                )
            validation_started_at = perf_counter()
            target_metrics = _validate_output_against_source(
                connection,
                target_relation,
                target_trade_date=target_trade_date,
                expected_source_row_count=target_source_row_count,
            )
            validation_elapsed_ms = (perf_counter() - validation_started_at) * 1000
            duckdb_elapsed_ms = (perf_counter() - duckdb_elapsed_start) * 1000
            return DcDailyTechnicalWriteResult(
                trade_date=target_trade_date,
                target_path=target_path,
                source_file_count=len(source_paths),
                source_row_count=source_metrics["source_row_count"],
                written_row_count=target_metrics["row_count"],
                series_count=target_metrics["series_count"],
                null_warmup_counts=target_metrics["null_warmup_counts"],
                duplicate_key_count=target_metrics["duplicate_key_count"],
                input_rejection_count=source_metrics["input_rejection_count"],
                duckdb_elapsed_ms=duckdb_elapsed_ms,
                parquet_write_elapsed_ms=0.0,
                validation_elapsed_ms=validation_elapsed_ms,
                total_elapsed_ms=(perf_counter() - started_at) * 1000,
                peak_memory_bytes=_peak_memory_bytes(),
                staging_path=None,
                skipped_existing=True,
            )

        connection.execute(f"CREATE OR REPLACE TEMP TABLE dc_daily_technical_output AS {_indicator_sql(target_trade_date)}")
        duckdb_elapsed_ms = (perf_counter() - duckdb_elapsed_start) * 1000
        target_metrics = _validate_output_against_source(
            connection,
            "dc_daily_technical_output",
            target_trade_date=target_trade_date,
            expected_source_row_count=target_source_row_count,
        )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = target_path.with_name(f"{target_path.name}.p3-{uuid4().hex}.tmp")
        parquet_started_at = perf_counter()
        try:
            connection.execute(
                f"COPY (SELECT * FROM dc_daily_technical_output) TO {duckdb_string(staging_path)} (FORMAT PARQUET)"
            )
            parquet_write_elapsed_ms = (perf_counter() - parquet_started_at) * 1000
            validation_started_at = perf_counter()
            staging_schema = _schema_mismatches(
                connection,
                read_parquet(staging_path, hive_partitioning=False),
                GOLD_DC_DAILY_TECHNICAL_SCHEMA,
            )
            if staging_schema["mismatch"]:
                raise DcDailyTechnicalValidationError(
                    f"Gold technical staging schema does not match contract: {staging_schema}"
                )
            staging_metrics = _validate_output_against_source(
                connection,
                read_parquet(staging_path, hive_partitioning=False),
                target_trade_date=target_trade_date,
                expected_source_row_count=target_source_row_count,
            )
            validation_elapsed_ms = (perf_counter() - validation_started_at) * 1000
            if target_path.exists():
                raise FileExistsError(
                    f"Gold technical target appeared during publish; refusing overwrite: {target_path}"
                )
            os.replace(staging_path, target_path)
        except Exception:
            staging_path.unlink(missing_ok=True)
            raise

    return DcDailyTechnicalWriteResult(
        trade_date=target_trade_date,
        target_path=target_path,
        source_file_count=len(source_paths),
        source_row_count=source_metrics["source_row_count"],
        written_row_count=staging_metrics["row_count"],
        series_count=staging_metrics["series_count"],
        null_warmup_counts=staging_metrics["null_warmup_counts"],
        duplicate_key_count=staging_metrics["duplicate_key_count"],
        input_rejection_count=source_metrics["input_rejection_count"],
        duckdb_elapsed_ms=duckdb_elapsed_ms,
        parquet_write_elapsed_ms=parquet_write_elapsed_ms,
        validation_elapsed_ms=validation_elapsed_ms,
        total_elapsed_ms=(perf_counter() - started_at) * 1000,
        peak_memory_bytes=_peak_memory_bytes(),
        staging_path=staging_path,
        skipped_existing=False,
    )
