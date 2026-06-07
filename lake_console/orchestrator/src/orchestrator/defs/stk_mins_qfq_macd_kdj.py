from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path
from typing import Sequence

import duckdb

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string, read_parquet
from orchestrator.defs.paths import (
    PATH_TEMPLATE_TS_CODE,
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_QFQ_FREQS,
    normalize_stk_mins_qfq_freq,
)


GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS = tuple(
    column.name for column in GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA
)
GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMN_TYPES = {
    column.name: column.type for column in GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA
}
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMNS = tuple(
    column.name for column in GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA
)
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMN_TYPES = {
    column.name: column.type for column in GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA
}

GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY = "macd_12_26_9__kdj_9_3_3"
GOLD_STK_MINS_QFQ_MACD_KDJ_INDICATOR_VERSION = 1
SEGMENT_BAR_COUNT = 1024

MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9
KDJ_PERIOD = 9
KDJ_ALPHA = 1.0 / 3.0
KDJ_SEED = 50.0


@dataclass(frozen=True)
class GoldStkMinsQfqMacdKdjWriteResult:
    path: Path
    ts_code: str
    year: str
    row_count: int
    replacement_row_count: int


@dataclass(frozen=True)
class GoldStkMinsQfqMacdKdjStateWriteResult:
    path: Path
    freq: int
    trade_date: str
    row_count: int


@dataclass(frozen=True)
class GoldStkMinsQfqMacdKdjPartitionWriteResult:
    freq: int
    trade_date: str
    source_file_count: int
    previous_state_file_path: Path | None
    indicator_file_count: int
    indicator_sample_file_paths: tuple[str, ...]
    indicator_row_count: int
    indicator_replacement_row_count: int
    state_file_path: Path
    state_row_count: int
    initialized_without_previous_state: bool
    observed_indicator_columns: tuple[str, ...]
    observed_state_columns: tuple[str, ...]


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("At least one parquet path is required.")
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False, union_by_name=True)
    quoted_paths = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{quoted_paths}], hive_partitioning=false, union_by_name=true)"


def _date_values_sql(trade_dates: Sequence[str]) -> str:
    if not trade_dates:
        raise ValueError("At least one trade date is required.")
    values = ", ".join(f"(DATE {duckdb_string(trade_date)})" for trade_date in trade_dates)
    return f"(VALUES {values}) AS target_trade_dates(trade_date)"


def _stock_code_filter_sql(stock_codes: Sequence[str]) -> str:
    normalized = tuple(sorted({stock_code.strip() for stock_code in stock_codes if stock_code.strip()}))
    if not normalized:
        return ""
    values = ", ".join(duckdb_string(stock_code) for stock_code in normalized)
    return f"AND CAST(ts_code AS VARCHAR) IN ({values})"


def _normalize_trade_dates(trade_dates: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({date.fromisoformat(item).isoformat() for item in trade_dates}))
    if not normalized:
        raise ValueError("At least one trade date is required.")
    return normalized


def _temp_path_for(target_path: Path) -> Path:
    return target_path.with_name(f".{target_path.name}.tmp")


def _schema_cast_columns(column_types: dict[str, str]) -> str:
    return ", ".join(
        f"CAST({column} AS {column_type}) AS {column}"
        for column, column_type in column_types.items()
    )


def _empty_state_source_sql() -> str:
    return f"""
    (
      SELECT {_schema_cast_columns(GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMN_TYPES)}
      FROM (
        SELECT
          NULL AS ts_code,
          NULL AS freq,
          NULL AS trade_date,
          NULL AS last_trade_time,
          NULL AS macd_ema_fast,
          NULL AS macd_ema_slow,
          NULL AS macd_dea,
          NULL AS kdj_k,
          NULL AS kdj_d,
          NULL AS params_key,
          NULL AS indicator_version
      )
      WHERE false
    )
    """


def discover_gold_stk_mins_qfq_source_year_paths(
    lake_root: Path,
    *,
    freq: int | str,
    trade_dates: Sequence[str],
) -> tuple[Path, ...]:
    normalized_freq = normalize_stk_mins_qfq_freq(freq)
    years = {date.fromisoformat(trade_date).year for trade_date in trade_dates}
    years.update(year - 1 for year in tuple(years))
    paths: list[Path] = []
    for year in sorted(years):
        freq_root = gold_stk_mins_qfq_path(
            lake_root,
            normalized_freq,
            PATH_TEMPLATE_TS_CODE,
            str(year),
        ).parents[2]
        paths.extend(sorted(freq_root.glob(f"ts_code=*/year={year}/part-000.parquet")))
    return tuple(paths)


def discover_latest_macd_kdj_state_path_before_trade_date(
    lake_root: Path,
    *,
    freq: int | str,
    trade_date: str,
) -> Path | None:
    normalized_freq = normalize_stk_mins_qfq_freq(freq)
    state_root = gold_stk_mins_qfq_macd_kdj_state_path(
        lake_root,
        normalized_freq,
        trade_date,
    ).parents[1]
    candidates = []
    for path in sorted(state_root.glob("trade_date=*/part-000.parquet")):
        state_trade_date = path.parent.name.removeprefix("trade_date=")
        if state_trade_date < trade_date:
            candidates.append(path)
    return candidates[-1] if candidates else None


def _create_macd_kdj_source_tables(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_qfq_paths: Sequence[Path],
    target_trade_dates: Sequence[str],
    previous_state_paths: Sequence[Path],
    freq: int,
    stock_codes: Sequence[str] = (),
) -> bool:
    target_dates = _normalize_trade_dates(target_trade_dates)
    target_dates_sql = _date_values_sql(target_dates)
    source_sql = _read_parquet_paths(source_qfq_paths)
    previous_state_sql = (
        _read_parquet_paths(previous_state_paths)
        if previous_state_paths
        else _empty_state_source_sql()
    )
    min_target_date = target_dates[0]
    max_target_date = target_dates[-1]
    stock_code_filter = _stock_code_filter_sql(stock_codes)

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE macd_kdj_source_all_rows AS
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(freq AS INTEGER) AS freq,
          CAST(trade_date AS DATE) AS trade_date,
          CAST(trade_time AS TIMESTAMP) AS trade_time,
          CAST(high AS DOUBLE) AS high,
          CAST(low AS DOUBLE) AS low,
          CAST(close AS DOUBLE) AS close
        FROM {source_sql}
        WHERE CAST(freq AS INTEGER) = {freq}
          AND CAST(trade_date AS DATE) <= DATE {duckdb_string(max_target_date)}
          {stock_code_filter}
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE macd_kdj_previous_state_rows AS
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(freq AS INTEGER) AS freq,
          CAST(trade_date AS DATE) AS trade_date,
          CAST(last_trade_time AS TIMESTAMP) AS last_trade_time,
          CAST(macd_ema_fast AS DOUBLE) AS macd_ema_fast,
          CAST(macd_ema_slow AS DOUBLE) AS macd_ema_slow,
          CAST(macd_dea AS DOUBLE) AS macd_dea,
          CAST(kdj_k AS DOUBLE) AS kdj_k,
          CAST(kdj_d AS DOUBLE) AS kdj_d,
          CAST(params_key AS VARCHAR) AS params_key,
          CAST(indicator_version AS INTEGER) AS indicator_version
        FROM {previous_state_sql}
        WHERE CAST(freq AS INTEGER) = {freq}
        QUALIFY row_number() OVER (
          PARTITION BY ts_code, freq
          ORDER BY trade_date DESC, last_trade_time DESC
        ) = 1
        """
    )
    previous_state_count = int(
        connection.execute("SELECT count(*) FROM macd_kdj_previous_state_rows").fetchone()[0]
    )
    initialized_without_previous_state = previous_state_count == 0

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE macd_kdj_calculation_rows AS
        WITH ranked_source AS (
          SELECT
            *,
            row_number() OVER (
              PARTITION BY ts_code, freq
              ORDER BY trade_time
            ) AS source_row_number
          FROM macd_kdj_source_all_rows
        ),
        first_target_rank AS (
          SELECT
            ts_code,
            freq,
            min(source_row_number) AS first_target_row_number
          FROM ranked_source
          WHERE trade_date >= DATE {duckdb_string(min_target_date)}
            AND trade_date <= DATE {duckdb_string(max_target_date)}
            AND trade_date IN (SELECT trade_date FROM {target_dates_sql})
          GROUP BY ts_code, freq
        ),
        rows_with_lookback AS (
          SELECT ranked_source.*
          FROM ranked_source
          INNER JOIN first_target_rank USING (ts_code, freq)
          WHERE ranked_source.trade_date IN (SELECT trade_date FROM {target_dates_sql})
             OR (
               ranked_source.source_row_number >= first_target_rank.first_target_row_number - {KDJ_PERIOD - 1}
               AND ranked_source.source_row_number < first_target_rank.first_target_row_number
             )
        ),
        rsv_rows AS (
          SELECT
            *,
            max(high) OVER (
              PARTITION BY ts_code, freq
              ORDER BY trade_time
              ROWS BETWEEN {KDJ_PERIOD - 1} PRECEDING AND CURRENT ROW
            ) AS kdj_hhv,
            min(low) OVER (
              PARTITION BY ts_code, freq
              ORDER BY trade_time
              ROWS BETWEEN {KDJ_PERIOD - 1} PRECEDING AND CURRENT ROW
            ) AS kdj_llv
          FROM rows_with_lookback
        ),
        target_rows AS (
          SELECT
            ts_code,
            freq,
            trade_date,
            trade_time,
            close,
            CASE
              WHEN kdj_hhv = kdj_llv THEN 50.0
              ELSE (close - kdj_llv) / (kdj_hhv - kdj_llv) * 100.0
            END AS kdj_rsv
          FROM rsv_rows
          WHERE trade_date IN (SELECT trade_date FROM {target_dates_sql})
        )
        SELECT
          *,
          row_number() OVER (
            PARTITION BY ts_code, freq
            ORDER BY trade_time
          ) AS calculation_row_number,
          CAST(floor((row_number() OVER (
            PARTITION BY ts_code, freq
            ORDER BY trade_time
          ) - 1) / {SEGMENT_BAR_COUNT}) AS INTEGER) AS segment_index,
          CAST(((row_number() OVER (
            PARTITION BY ts_code, freq
            ORDER BY trade_time
          ) - 1) % {SEGMENT_BAR_COUNT}) + 1 AS INTEGER) AS segment_row_number
        FROM target_rows
        ORDER BY segment_index, ts_code, trade_time
        """
    )
    missing_old_state_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT DISTINCT ts_code, freq
              FROM macd_kdj_calculation_rows
            ) AS target_codes
            LEFT JOIN macd_kdj_previous_state_rows AS previous_state
              ON previous_state.ts_code = target_codes.ts_code
             AND previous_state.freq = target_codes.freq
            WHERE previous_state.ts_code IS NULL
              AND EXISTS (
                SELECT 1
                FROM macd_kdj_source_all_rows AS prior_source
                WHERE prior_source.ts_code = target_codes.ts_code
                  AND prior_source.freq = target_codes.freq
                  AND prior_source.trade_date < DATE {duckdb_string(min_target_date)}
              )
            """
        ).fetchone()[0]
    )
    if missing_old_state_count:
        raise RuntimeError(
            "Gold qfq MACD/KDJ previous state is missing for existing stocks: "
            f"freq={freq}, missing_old_state_count={missing_old_state_count}."
        )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE macd_kdj_indicator_work_rows (
          ts_code VARCHAR,
          freq INTEGER,
          trade_date DATE,
          trade_time TIMESTAMP,
          macd_dif_qfq DOUBLE,
          macd_dea_qfq DOUBLE,
          macd_qfq DOUBLE,
          kdj_k_qfq DOUBLE,
          kdj_d_qfq DOUBLE,
          kdj_qfq DOUBLE,
          params_key VARCHAR,
          indicator_version INTEGER,
          macd_ema_fast DOUBLE,
          macd_ema_slow DOUBLE,
          macd_dea DOUBLE,
          kdj_k DOUBLE,
          kdj_d DOUBLE,
          segment_index INTEGER,
          segment_row_number INTEGER
        )
        """
    )
    return initialized_without_previous_state


def _insert_macd_kdj_segment_rows(
    connection: duckdb.DuckDBPyConnection,
    *,
    segment_index: int,
) -> None:
    alpha_fast = 2.0 / (MACD_FAST_PERIOD + 1.0)
    beta_fast = 1.0 - alpha_fast
    alpha_slow = 2.0 / (MACD_SLOW_PERIOD + 1.0)
    beta_slow = 1.0 - alpha_slow
    alpha_dea = 2.0 / (MACD_SIGNAL_PERIOD + 1.0)
    beta_dea = 1.0 - alpha_dea
    alpha_k = KDJ_ALPHA
    beta_k = 1.0 - alpha_k
    alpha_d = KDJ_ALPHA
    beta_d = 1.0 - alpha_d

    connection.execute(
        f"""
        INSERT INTO macd_kdj_indicator_work_rows
        WITH segment_rows AS (
          SELECT *
          FROM macd_kdj_calculation_rows
          WHERE segment_index = {segment_index}
        ),
        segment_seed AS (
          SELECT
            segment_rows.ts_code,
            segment_rows.freq,
            COALESCE(previous_work.macd_ema_fast, previous_state.macd_ema_fast, segment_rows.close) AS seed_ema_fast,
            COALESCE(previous_work.macd_ema_slow, previous_state.macd_ema_slow, segment_rows.close) AS seed_ema_slow,
            COALESCE(previous_work.macd_dea, previous_state.macd_dea, 0.0) AS seed_macd_dea,
            COALESCE(previous_work.kdj_k, previous_state.kdj_k, {KDJ_SEED}) AS seed_kdj_k,
            COALESCE(previous_work.kdj_d, previous_state.kdj_d, {KDJ_SEED}) AS seed_kdj_d
          FROM segment_rows
          LEFT JOIN macd_kdj_previous_state_rows AS previous_state
            ON previous_state.ts_code = segment_rows.ts_code
           AND previous_state.freq = segment_rows.freq
          LEFT JOIN (
            SELECT
              ts_code,
              freq,
              macd_ema_fast,
              macd_ema_slow,
              macd_dea,
              kdj_k,
              kdj_d
            FROM macd_kdj_indicator_work_rows
            WHERE segment_index = {segment_index - 1}
            QUALIFY row_number() OVER (
              PARTITION BY ts_code, freq
              ORDER BY segment_row_number DESC
            ) = 1
          ) AS previous_work
            ON previous_work.ts_code = segment_rows.ts_code
           AND previous_work.freq = segment_rows.freq
          WHERE segment_rows.segment_row_number = 1
        ),
        ema_values AS (
          SELECT
            segment_rows.*,
            pow({beta_fast}, segment_row_number) * (
              segment_seed.seed_ema_fast
              + {alpha_fast} * sum(segment_rows.close * pow({beta_fast}, -segment_row_number))
                OVER (
                  PARTITION BY segment_rows.ts_code, segment_rows.freq
                  ORDER BY segment_row_number
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )
            ) AS macd_ema_fast,
            pow({beta_slow}, segment_row_number) * (
              segment_seed.seed_ema_slow
              + {alpha_slow} * sum(segment_rows.close * pow({beta_slow}, -segment_row_number))
                OVER (
                  PARTITION BY segment_rows.ts_code, segment_rows.freq
                  ORDER BY segment_row_number
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )
            ) AS macd_ema_slow,
            segment_seed.seed_macd_dea,
            segment_seed.seed_kdj_k,
            segment_seed.seed_kdj_d
          FROM segment_rows
          INNER JOIN segment_seed USING (ts_code, freq)
        ),
        dif_values AS (
          SELECT
            *,
            macd_ema_fast - macd_ema_slow AS macd_dif_qfq
          FROM ema_values
        ),
        dea_values AS (
          SELECT
            *,
            pow({beta_dea}, segment_row_number) * (
              seed_macd_dea
              + {alpha_dea} * sum(macd_dif_qfq * pow({beta_dea}, -segment_row_number))
                OVER (
                  PARTITION BY ts_code, freq
                  ORDER BY segment_row_number
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )
            ) AS macd_dea
          FROM dif_values
        ),
        k_values AS (
          SELECT
            *,
            pow({beta_k}, segment_row_number) * (
              seed_kdj_k
              + {alpha_k} * sum(kdj_rsv * pow({beta_k}, -segment_row_number))
                OVER (
                  PARTITION BY ts_code, freq
                  ORDER BY segment_row_number
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )
            ) AS kdj_k
          FROM dea_values
        ),
        d_values AS (
          SELECT
            *,
            pow({beta_d}, segment_row_number) * (
              seed_kdj_d
              + {alpha_d} * sum(kdj_k * pow({beta_d}, -segment_row_number))
                OVER (
                  PARTITION BY ts_code, freq
                  ORDER BY segment_row_number
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )
            ) AS kdj_d
          FROM k_values
        )
        SELECT
          ts_code,
          freq,
          trade_date,
          trade_time,
          macd_dif_qfq,
          macd_dea AS macd_dea_qfq,
          2.0 * (macd_dif_qfq - macd_dea) AS macd_qfq,
          kdj_k AS kdj_k_qfq,
          kdj_d AS kdj_d_qfq,
          3.0 * kdj_k - 2.0 * kdj_d AS kdj_qfq,
          {duckdb_string(GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY)} AS params_key,
          {GOLD_STK_MINS_QFQ_MACD_KDJ_INDICATOR_VERSION} AS indicator_version,
          macd_ema_fast,
          macd_ema_slow,
          macd_dea,
          kdj_k,
          kdj_d,
          segment_index,
          segment_row_number
        FROM d_values
        ORDER BY ts_code, trade_time
        """
    )


def _populate_macd_kdj_indicator_work_rows(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute(
        "SELECT max(segment_index) FROM macd_kdj_calculation_rows"
    ).fetchone()
    if row is None or row[0] is None:
        return 0
    max_segment_index = int(row[0])
    for segment_index in range(max_segment_index + 1):
        _insert_macd_kdj_segment_rows(connection, segment_index=segment_index)
    return int(
        connection.execute("SELECT count(*) FROM macd_kdj_indicator_work_rows").fetchone()[0]
    )


def _create_macd_kdj_replacement_tables(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_qfq_paths: Sequence[Path],
    target_trade_dates: Sequence[str],
    previous_state_paths: Sequence[Path],
    freq: int,
    stock_codes: Sequence[str] = (),
) -> bool:
    initialized_without_previous_state = _create_macd_kdj_source_tables(
        connection,
        source_qfq_paths=source_qfq_paths,
        target_trade_dates=target_trade_dates,
        previous_state_paths=previous_state_paths,
        freq=freq,
        stock_codes=stock_codes,
    )
    _populate_macd_kdj_indicator_work_rows(connection)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE macd_kdj_indicator_replacement_rows AS
        SELECT {_schema_cast_columns(GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMN_TYPES)}
        FROM macd_kdj_indicator_work_rows
        ORDER BY ts_code, trade_time
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE macd_kdj_state_replacement_rows AS
        WITH target_dates AS (
          SELECT trade_date FROM {_date_values_sql(target_trade_dates)}
        ),
        new_state_events AS (
          SELECT
            ts_code,
            freq,
            trade_date AS state_date,
            trade_time AS last_trade_time,
            macd_ema_fast,
            macd_ema_slow,
            macd_dea,
            kdj_k,
            kdj_d,
            params_key,
            indicator_version,
            row_number() OVER (
              PARTITION BY ts_code, freq, trade_date
              ORDER BY trade_time DESC
            ) AS row_number
          FROM macd_kdj_indicator_work_rows
        ),
        all_state_events AS (
          SELECT
            ts_code,
            freq,
            trade_date AS state_date,
            last_trade_time,
            macd_ema_fast,
            macd_ema_slow,
            macd_dea,
            kdj_k,
            kdj_d,
            params_key,
            indicator_version
          FROM macd_kdj_previous_state_rows
          UNION ALL
          SELECT
            ts_code,
            freq,
            state_date,
            last_trade_time,
            macd_ema_fast,
            macd_ema_slow,
            macd_dea,
            kdj_k,
            kdj_d,
            params_key,
            indicator_version
          FROM new_state_events
          WHERE row_number = 1
        ),
        ranked AS (
          SELECT
            all_state_events.ts_code,
            all_state_events.freq,
            target_dates.trade_date,
            all_state_events.last_trade_time,
            all_state_events.macd_ema_fast,
            all_state_events.macd_ema_slow,
            all_state_events.macd_dea,
            all_state_events.kdj_k,
            all_state_events.kdj_d,
            all_state_events.params_key,
            all_state_events.indicator_version,
            row_number() OVER (
              PARTITION BY target_dates.trade_date, all_state_events.ts_code, all_state_events.freq
              ORDER BY all_state_events.state_date DESC, all_state_events.last_trade_time DESC
            ) AS row_number
          FROM target_dates
          INNER JOIN all_state_events
            ON all_state_events.state_date <= target_dates.trade_date
        )
        SELECT {_schema_cast_columns(GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMN_TYPES)}
        FROM ranked
        WHERE row_number = 1
        ORDER BY ts_code
        """
    )
    return initialized_without_previous_state


def _existing_indicator_rows_select(target_path: Path) -> str:
    if not target_path.exists():
        null_columns = ", ".join(
            f"CAST(NULL AS {column_type}) AS {column}"
            for column, column_type in GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMN_TYPES.items()
        )
        return f"SELECT {null_columns} WHERE false"
    columns = ", ".join(GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS)
    return f"SELECT {columns} FROM {read_parquet(target_path, hive_partitioning=False)}"


def _validate_indicator_year_file(
    connection: duckdb.DuckDBPyConnection,
    *,
    target_path: Path,
    freq: int,
    ts_code: str,
    year: str,
) -> None:
    mismatch_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(target_path, hive_partitioning=False)}
            WHERE freq != {freq}
               OR ts_code != {duckdb_string(ts_code)}
               OR strftime(trade_date, '%Y') != {duckdb_string(year)}
            """
        ).fetchone()[0]
    )
    if mismatch_count:
        raise RuntimeError(
            "Gold qfq MACD/KDJ year file has rows outside target stock-year: "
            f"path={target_path}, mismatch_count={mismatch_count}."
        )


def _write_indicator_group_to_year_file(
    connection: duckdb.DuckDBPyConnection,
    *,
    target_path: Path,
    freq: int,
    ts_code: str,
    year: str,
    fail_if_target_exists: bool,
) -> int:
    if target_path.exists():
        if fail_if_target_exists:
            raise FileExistsError(f"Gold qfq MACD/KDJ target already exists: {target_path}")
        _validate_indicator_year_file(
            connection,
            target_path=target_path,
            freq=freq,
            ts_code=ts_code,
            year=year,
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_path_for(target_path)
    if temp_path.exists():
        temp_path.unlink()
    columns = ", ".join(GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS)
    connection.execute(
        copy_query_to_parquet(
            f"""
            WITH replacement_group AS (
              SELECT {columns}
              FROM macd_kdj_indicator_replacement_rows
              WHERE ts_code = {duckdb_string(ts_code)}
                AND strftime(trade_date, '%Y') = {duckdb_string(year)}
            ),
            existing_rows AS (
              {_existing_indicator_rows_select(target_path)}
            ),
            merged_rows AS (
              SELECT {columns}
              FROM existing_rows
              WHERE trade_date NOT IN (
                SELECT DISTINCT trade_date FROM replacement_group
              )
              UNION ALL
              SELECT {columns}
              FROM replacement_group
            )
            SELECT {columns}
            FROM merged_rows
            ORDER BY trade_date, trade_time
            """,
            temp_path,
        )
    )
    _validate_indicator_year_file(
        connection,
        target_path=temp_path,
        freq=freq,
        ts_code=ts_code,
        year=year,
    )
    row_count = int(
        connection.execute(
            f"SELECT count(*) FROM {read_parquet(temp_path, hive_partitioning=False)}"
        ).fetchone()[0]
    )
    os.replace(temp_path, target_path)
    return row_count


def _write_state_partition_file(
    connection: duckdb.DuckDBPyConnection,
    *,
    target_path: Path,
    freq: int,
    trade_date: str,
) -> int:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_path_for(target_path)
    if temp_path.exists():
        temp_path.unlink()
    columns = ", ".join(GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMNS)
    connection.execute(
        copy_query_to_parquet(
            f"""
            SELECT {columns}
            FROM macd_kdj_state_replacement_rows
            WHERE freq = {freq}
              AND trade_date = DATE {duckdb_string(trade_date)}
            ORDER BY ts_code
            """,
            temp_path,
        )
    )
    mismatch_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(temp_path, hive_partitioning=False)}
            WHERE freq != {freq}
               OR trade_date != DATE {duckdb_string(trade_date)}
            """
        ).fetchone()[0]
    )
    if mismatch_count:
        raise RuntimeError(
            "Gold qfq MACD/KDJ state file has rows outside target partition: "
            f"path={target_path}, mismatch_count={mismatch_count}."
        )
    row_count = int(
        connection.execute(
            f"SELECT count(*) FROM {read_parquet(temp_path, hive_partitioning=False)}"
        ).fetchone()[0]
    )
    os.replace(temp_path, target_path)
    return row_count


def write_gold_stk_mins_qfq_macd_kdj_rows(
    *,
    lake_root: Path,
    freq: int | str,
    source_qfq_paths: Sequence[Path],
    target_trade_dates: Sequence[str],
    previous_state_paths: Sequence[Path] = (),
    stock_codes: Sequence[str] = (),
    fail_if_target_exists: bool = False,
    allow_empty_replacement: bool = False,
) -> tuple[
    tuple[GoldStkMinsQfqMacdKdjWriteResult, ...],
    tuple[GoldStkMinsQfqMacdKdjStateWriteResult, ...],
    bool,
]:
    normalized_freq = normalize_stk_mins_qfq_freq(freq)
    normalized_trade_dates = _normalize_trade_dates(target_trade_dates)
    if not source_qfq_paths:
        raise FileNotFoundError("Missing source gold qfq files for MACD/KDJ computation.")

    with connect_configured_duckdb() as connection:
        initialized_without_previous_state = _create_macd_kdj_replacement_tables(
            connection,
            source_qfq_paths=source_qfq_paths,
            target_trade_dates=normalized_trade_dates,
            previous_state_paths=previous_state_paths,
            freq=normalized_freq,
            stock_codes=stock_codes,
        )
        replacement_row_count = int(
            connection.execute(
                "SELECT count(*) FROM macd_kdj_indicator_replacement_rows"
            ).fetchone()[0]
        )
        if replacement_row_count == 0 and allow_empty_replacement:
            return (), (), initialized_without_previous_state
        if replacement_row_count == 0:
            raise RuntimeError(
                "Gold qfq MACD/KDJ computation produced no indicator rows: "
                f"freq={normalized_freq}, trade_dates={normalized_trade_dates}."
            )

        groups = connection.execute(
            """
            SELECT
              ts_code,
              strftime(trade_date, '%Y') AS year,
              count(*) AS replacement_row_count
            FROM macd_kdj_indicator_replacement_rows
            GROUP BY ts_code, year
            ORDER BY ts_code, year
            """
        ).fetchall()
        indicator_results: list[GoldStkMinsQfqMacdKdjWriteResult] = []
        for ts_code, year, group_replacement_row_count in groups:
            target_path = gold_stk_mins_qfq_macd_kdj_path(
                lake_root,
                normalized_freq,
                str(ts_code),
                str(year),
            )
            row_count = _write_indicator_group_to_year_file(
                connection,
                target_path=target_path,
                freq=normalized_freq,
                ts_code=str(ts_code),
                year=str(year),
                fail_if_target_exists=fail_if_target_exists,
            )
            indicator_results.append(
                GoldStkMinsQfqMacdKdjWriteResult(
                    path=target_path,
                    ts_code=str(ts_code),
                    year=str(year),
                    row_count=row_count,
                    replacement_row_count=int(group_replacement_row_count),
                )
            )

        state_results: list[GoldStkMinsQfqMacdKdjStateWriteResult] = []
        for trade_date_value in normalized_trade_dates:
            state_path = gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root,
                normalized_freq,
                trade_date_value,
            )
            row_count = _write_state_partition_file(
                connection,
                target_path=state_path,
                freq=normalized_freq,
                trade_date=trade_date_value,
            )
            state_results.append(
                GoldStkMinsQfqMacdKdjStateWriteResult(
                    path=state_path,
                    freq=normalized_freq,
                    trade_date=trade_date_value,
                    row_count=row_count,
                )
            )

    return (
        tuple(indicator_results),
        tuple(state_results),
        initialized_without_previous_state,
    )


def write_gold_stk_mins_qfq_macd_kdj_asset_partition(
    *,
    lake_root: Path,
    freq: int | str,
    partition_key: str,
) -> GoldStkMinsQfqMacdKdjPartitionWriteResult:
    normalized_freq = normalize_stk_mins_qfq_freq(freq)
    source_paths = discover_gold_stk_mins_qfq_source_year_paths(
        lake_root,
        freq=normalized_freq,
        trade_dates=[partition_key],
    )
    if not source_paths:
        raise FileNotFoundError(
            "Missing source gold qfq stock-year files for MACD/KDJ: "
            f"freq={normalized_freq}, partition={partition_key}."
        )
    previous_state_path = discover_latest_macd_kdj_state_path_before_trade_date(
        lake_root,
        freq=normalized_freq,
        trade_date=partition_key,
    )
    indicator_results, state_results, initialized_without_previous_state = (
        write_gold_stk_mins_qfq_macd_kdj_rows(
            lake_root=lake_root,
            freq=normalized_freq,
            source_qfq_paths=source_paths,
            target_trade_dates=[partition_key],
            previous_state_paths=(
                (previous_state_path,) if previous_state_path is not None else ()
            ),
        )
    )
    if not indicator_results:
        raise RuntimeError(
            "Gold qfq MACD/KDJ asset write produced no indicator files: "
            f"freq={normalized_freq}, partition={partition_key}."
        )
    if len(state_results) != 1:
        raise RuntimeError(
            "Gold qfq MACD/KDJ asset write produced unexpected state files: "
            f"freq={normalized_freq}, partition={partition_key}, count={len(state_results)}."
        )

    indicator_file_paths = tuple(str(result.path) for result in indicator_results)
    return GoldStkMinsQfqMacdKdjPartitionWriteResult(
        freq=normalized_freq,
        trade_date=partition_key,
        source_file_count=len(source_paths),
        previous_state_file_path=previous_state_path,
        indicator_file_count=len(indicator_results),
        indicator_sample_file_paths=indicator_file_paths[:20],
        indicator_row_count=sum(result.replacement_row_count for result in indicator_results),
        indicator_replacement_row_count=sum(
            result.replacement_row_count for result in indicator_results
        ),
        state_file_path=state_results[0].path,
        state_row_count=state_results[0].row_count,
        initialized_without_previous_state=initialized_without_previous_state,
        observed_indicator_columns=GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS,
        observed_state_columns=GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMNS,
    )


def all_stk_mins_qfq_macd_kdj_asset_freqs() -> tuple[int, ...]:
    return STK_MINS_QFQ_FREQS
