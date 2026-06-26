from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import duckdb

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_stock_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_QFQ_SCHEMA,
)


GOLD_STOCK_DAILY_QFQ_COLUMNS = tuple(
    column.name for column in GOLD_STOCK_DAILY_QFQ_SCHEMA
)
GOLD_STOCK_DAILY_QFQ_COLUMN_TYPES = {
    column.name: column.type for column in GOLD_STOCK_DAILY_QFQ_SCHEMA
}
STOCK_DAILY_QFQ_PREVIOUS_LOOKUP_LIMIT = 20


@dataclass(frozen=True)
class GoldStockDailyQfqPartitionWriteResult:
    path: Path
    stock_daily_file_path: Path
    trade_adj_factor_file_path: Path
    as_of_adj_factor_file_path: Path
    previous_lookup_trade_date_count: int
    previous_stock_daily_file_count: int
    previous_adj_factor_file_count: int
    source_row_count: int
    output_row_count: int
    missing_previous_row_count: int
    observed_columns: tuple[str, ...]


def load_stock_daily_qfq_previous_lookup_trade_dates(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    limit: int = STOCK_DAILY_QFQ_PREVIOUS_LOOKUP_LIMIT,
) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("previous lookup limit must be positive.")

    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing silver trade calendar file: {calendar_path}")

    rows = connection.execute(
        f"""
        SELECT strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS trade_date
        FROM {read_parquet(calendar_path, hive_partitioning=False)}
        WHERE CAST(exchange AS VARCHAR) = 'SSE'
          AND CAST(is_open AS BOOLEAN)
          AND CAST(trade_date AS DATE) < DATE {duckdb_string(trade_date)}
        ORDER BY CAST(trade_date AS DATE) DESC
        LIMIT {int(limit)}
        """
    ).fetchall()
    return tuple(reversed([str(row[0]) for row in rows]))


def build_stock_daily_qfq_select_sql(
    *,
    stock_daily_path: Path,
    trade_adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
    trade_date: str,
    as_of_trade_date: str,
) -> str:
    return f"""
{_stock_daily_qfq_base_ctes_sql(
    stock_daily_path=stock_daily_path,
    trade_adj_factor_path=trade_adj_factor_path,
    previous_stock_daily_paths=previous_stock_daily_paths,
    previous_adj_factor_paths=previous_adj_factor_paths,
    as_of_adj_factor_path=as_of_adj_factor_path,
    trade_date=trade_date,
    as_of_trade_date=as_of_trade_date,
)}
, priced_rows AS (
  SELECT
    ts_code,
    trade_date,
    open_qfq AS open,
    high_qfq AS high,
    low_qfq AS low,
    close_qfq AS close,
    CASE
      WHEN previous_trade_date IS NULL THEN CAST(0 AS DOUBLE)
      ELSE previous_close * previous_adj_factor / as_of_adj_factor
    END AS pre_close,
    vol,
    amount
  FROM joined_rows
  WHERE trade_adj_factor IS NOT NULL
    AND as_of_adj_factor IS NOT NULL
    AND (previous_trade_date IS NULL OR previous_adj_factor IS NOT NULL)
)
SELECT
  ts_code,
  trade_date,
  CAST(open AS DOUBLE) AS open,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(close AS DOUBLE) AS close,
  CAST(pre_close AS DOUBLE) AS pre_close,
  CAST(
    CASE
      WHEN pre_close = 0 THEN 0
      ELSE close - pre_close
    END AS DOUBLE
  ) AS change_amount,
  CAST(
    CASE
      WHEN pre_close = 0 THEN 0
      ELSE (close - pre_close) / pre_close * 100
    END AS DOUBLE
  ) AS pct_chg,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount
FROM priced_rows
ORDER BY ts_code, trade_date
"""


def build_stock_daily_qfq_coverage_sql(
    *,
    stock_daily_path: Path,
    trade_adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
    trade_date: str,
    as_of_trade_date: str,
) -> str:
    return f"""
{_stock_daily_qfq_base_ctes_sql(
    stock_daily_path=stock_daily_path,
    trade_adj_factor_path=trade_adj_factor_path,
    previous_stock_daily_paths=previous_stock_daily_paths,
    previous_adj_factor_paths=previous_adj_factor_paths,
    as_of_adj_factor_path=as_of_adj_factor_path,
    trade_date=trade_date,
    as_of_trade_date=as_of_trade_date,
)}
SELECT
  count(*) AS source_row_count,
  count(*) FILTER (
    WHERE trade_adj_factor IS NOT NULL
      AND as_of_adj_factor IS NOT NULL
      AND (previous_trade_date IS NULL OR previous_adj_factor IS NOT NULL)
  ) AS qfq_output_row_count,
  count(*) FILTER (WHERE trade_adj_factor IS NULL)
    AS missing_trade_adj_factor_row_count,
  count(*) FILTER (WHERE as_of_adj_factor IS NULL)
    AS missing_as_of_adj_factor_row_count,
  count(*) FILTER (WHERE previous_trade_date IS NULL)
    AS missing_previous_row_count,
  count(*) FILTER (
    WHERE previous_trade_date IS NOT NULL AND previous_adj_factor IS NULL
  ) AS missing_previous_adj_factor_row_count
FROM joined_rows
"""


def write_gold_stock_daily_qfq_partition(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    previous_lookup_trade_dates: Sequence[str],
    as_of_trade_date: str | None = None,
) -> GoldStockDailyQfqPartitionWriteResult:
    resolved_as_of_trade_date = as_of_trade_date or trade_date
    stock_daily_path = silver_stock_daily_path(lake_root, trade_date)
    trade_adj_factor_path = silver_adj_factor_path(lake_root, trade_date)
    as_of_adj_factor_path = silver_adj_factor_path(lake_root, resolved_as_of_trade_date)
    target_path = gold_stock_daily_qfq_path(lake_root, trade_date)

    for input_path, label in (
        (stock_daily_path, "silver stock daily"),
        (trade_adj_factor_path, "silver trade-date adj factor"),
        (as_of_adj_factor_path, "silver as-of adj factor"),
    ):
        if not input_path.exists():
            raise FileNotFoundError(f"Missing {label} file: {input_path}")

    previous_stock_daily_paths = tuple(
        path
        for path in (
            silver_stock_daily_path(lake_root, previous_trade_date)
            for previous_trade_date in previous_lookup_trade_dates
        )
        if path.exists()
    )
    previous_adj_factor_paths = tuple(
        path
        for path in (
            silver_adj_factor_path(lake_root, previous_trade_date)
            for previous_trade_date in previous_lookup_trade_dates
        )
        if path.exists()
    )
    coverage_row = connection.execute(
        build_stock_daily_qfq_coverage_sql(
            stock_daily_path=stock_daily_path,
            trade_adj_factor_path=trade_adj_factor_path,
            previous_stock_daily_paths=previous_stock_daily_paths,
            previous_adj_factor_paths=previous_adj_factor_paths,
            as_of_adj_factor_path=as_of_adj_factor_path,
            trade_date=trade_date,
            as_of_trade_date=resolved_as_of_trade_date,
        )
    ).fetchone()
    source_row_count = int(coverage_row[0])
    output_row_count = int(coverage_row[1])
    missing_trade_adj_factor_row_count = int(coverage_row[2])
    missing_as_of_adj_factor_row_count = int(coverage_row[3])
    missing_previous_row_count = int(coverage_row[4])
    missing_previous_adj_factor_row_count = int(coverage_row[5])

    if source_row_count <= 0:
        raise ValueError(f"Silver stock daily has no rows for {trade_date}.")
    if missing_trade_adj_factor_row_count:
        raise ValueError(
            "Missing trade-date adj factor rows for stock daily qfq: "
            f"trade_date={trade_date}, "
            f"missing_row_count={missing_trade_adj_factor_row_count}."
        )
    if missing_as_of_adj_factor_row_count:
        raise ValueError(
            "Missing as-of adj factor rows for stock daily qfq: "
            f"as_of_trade_date={resolved_as_of_trade_date}, "
            f"missing_row_count={missing_as_of_adj_factor_row_count}."
        )
    if missing_previous_adj_factor_row_count:
        raise ValueError(
            "Previous stock daily rows exist but previous adj factor rows are missing: "
            f"trade_date={trade_date}, "
            f"missing_row_count={missing_previous_adj_factor_row_count}."
        )
    if output_row_count != source_row_count:
        raise ValueError(
            "Stock daily qfq output row count must match source row count: "
            f"source_row_count={source_row_count}, output_row_count={output_row_count}."
        )

    _replace_parquet_from_query(
        connection,
        build_stock_daily_qfq_select_sql(
            stock_daily_path=stock_daily_path,
            trade_adj_factor_path=trade_adj_factor_path,
            previous_stock_daily_paths=previous_stock_daily_paths,
            previous_adj_factor_paths=previous_adj_factor_paths,
            as_of_adj_factor_path=as_of_adj_factor_path,
            trade_date=trade_date,
            as_of_trade_date=resolved_as_of_trade_date,
        ),
        target_path,
    )
    observed_columns = tuple(
        _column_names(connection, target_path, hive_partitioning=False)
    )
    written_row_count = _row_count(connection, target_path, hive_partitioning=False)
    if written_row_count != output_row_count:
        raise ValueError(
            "Written stock daily qfq row count changed after parquet write: "
            f"expected={output_row_count}, actual={written_row_count}."
        )

    return GoldStockDailyQfqPartitionWriteResult(
        path=target_path,
        stock_daily_file_path=stock_daily_path,
        trade_adj_factor_file_path=trade_adj_factor_path,
        as_of_adj_factor_file_path=as_of_adj_factor_path,
        previous_lookup_trade_date_count=len(tuple(previous_lookup_trade_dates)),
        previous_stock_daily_file_count=len(previous_stock_daily_paths),
        previous_adj_factor_file_count=len(previous_adj_factor_paths),
        source_row_count=source_row_count,
        output_row_count=output_row_count,
        missing_previous_row_count=missing_previous_row_count,
        observed_columns=observed_columns,
    )


def _stock_daily_qfq_base_ctes_sql(
    *,
    stock_daily_path: Path,
    trade_adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
    trade_date: str,
    as_of_trade_date: str,
) -> str:
    source_daily = read_parquet(stock_daily_path, hive_partitioning=False)
    trade_factor = read_parquet(trade_adj_factor_path, hive_partitioning=False)
    as_of_factor = read_parquet(as_of_adj_factor_path, hive_partitioning=False)
    previous_daily = _previous_stock_daily_source(previous_stock_daily_paths)
    previous_factor = _previous_adj_factor_source(previous_adj_factor_paths)
    trade_date_sql = f"DATE {duckdb_string(trade_date)}"
    as_of_trade_date_sql = f"DATE {duckdb_string(as_of_trade_date)}"
    return f"""
WITH source_daily AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(open AS DOUBLE) AS open,
    CAST(high AS DOUBLE) AS high,
    CAST(low AS DOUBLE) AS low,
    CAST(close AS DOUBLE) AS close,
    CAST(vol AS DOUBLE) AS vol,
    CAST(amount AS DOUBLE) AS amount
  FROM {source_daily}
  WHERE CAST(trade_date AS DATE) = {trade_date_sql}
),
trade_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(adj_factor AS DOUBLE) AS trade_adj_factor
  FROM {trade_factor}
  WHERE CAST(trade_date AS DATE) = {trade_date_sql}
),
as_of_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS as_of_trade_date,
    CAST(adj_factor AS DOUBLE) AS as_of_adj_factor
  FROM {as_of_factor}
  WHERE CAST(trade_date AS DATE) = {as_of_trade_date_sql}
),
previous_daily_candidates AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(close AS DOUBLE) AS close
  FROM {previous_daily}
  WHERE CAST(trade_date AS DATE) < {trade_date_sql}
),
previous_daily AS (
  SELECT ts_code, trade_date AS previous_trade_date, close AS previous_close
  FROM (
    SELECT
      ts_code,
      trade_date,
      close,
      row_number() OVER (
        PARTITION BY ts_code
        ORDER BY trade_date DESC
      ) AS row_number
    FROM previous_daily_candidates
  )
  WHERE row_number = 1
),
previous_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS previous_trade_date,
    CAST(adj_factor AS DOUBLE) AS previous_adj_factor
  FROM {previous_factor}
),
joined_rows AS (
  SELECT
    source_daily.ts_code,
    source_daily.trade_date,
    CAST(
      source_daily.open
      * trade_adj_factor.trade_adj_factor
      / as_of_adj_factor.as_of_adj_factor
      AS DOUBLE
    ) AS open_qfq,
    CAST(
      source_daily.high
      * trade_adj_factor.trade_adj_factor
      / as_of_adj_factor.as_of_adj_factor
      AS DOUBLE
    ) AS high_qfq,
    CAST(
      source_daily.low
      * trade_adj_factor.trade_adj_factor
      / as_of_adj_factor.as_of_adj_factor
      AS DOUBLE
    ) AS low_qfq,
    CAST(
      source_daily.close
      * trade_adj_factor.trade_adj_factor
      / as_of_adj_factor.as_of_adj_factor
      AS DOUBLE
    ) AS close_qfq,
    source_daily.vol,
    source_daily.amount,
    trade_adj_factor.trade_adj_factor,
    as_of_adj_factor.as_of_adj_factor,
    previous_daily.previous_trade_date,
    previous_daily.previous_close,
    previous_adj_factor.previous_adj_factor
  FROM source_daily
  LEFT JOIN trade_adj_factor
    ON source_daily.ts_code = trade_adj_factor.ts_code
   AND source_daily.trade_date = trade_adj_factor.trade_date
  LEFT JOIN as_of_adj_factor
    ON source_daily.ts_code = as_of_adj_factor.ts_code
  LEFT JOIN previous_daily
    ON source_daily.ts_code = previous_daily.ts_code
  LEFT JOIN previous_adj_factor
    ON previous_daily.ts_code = previous_adj_factor.ts_code
   AND previous_daily.previous_trade_date = previous_adj_factor.previous_trade_date
)
"""


def _previous_stock_daily_source(paths: Sequence[Path]) -> str:
    if paths:
        return _read_parquet_paths(paths)
    return """
    (
      SELECT
        CAST(NULL AS VARCHAR) AS ts_code,
        CAST(NULL AS DATE) AS trade_date,
        CAST(NULL AS DOUBLE) AS close
      WHERE false
    )
    """


def _previous_adj_factor_source(paths: Sequence[Path]) -> str:
    if paths:
        return _read_parquet_paths(paths)
    return """
    (
      SELECT
        CAST(NULL AS VARCHAR) AS ts_code,
        CAST(NULL AS DATE) AS trade_date,
        CAST(NULL AS DOUBLE) AS adj_factor
      WHERE false
    )
    """


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("At least one parquet path is required.")
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    path_list = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{path_list}], hive_partitioning=false, union_by_name=true)"


def _replace_parquet_from_query(
    connection: duckdb.DuckDBPyConnection,
    select_sql: str,
    target_path: Path,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()
    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


def _column_names(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    *,
    hive_partitioning: bool = False,
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [str(row[0]) for row in rows]


def _row_count(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    *,
    hive_partitioning: bool = False,
) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=hive_partitioning)
        ).fetchone()[0]
    )
