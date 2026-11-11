"""Listed and suspended stock sets shared by daily checks and period readiness."""

from orchestrator.defs.duckdb_sql import read_parquet


def stock_trading_universe_ctes(*, trade_date, lifecycle_sql, suspend_path, listed_filter="TRUE"):
    return f"""
    listed AS (
      SELECT DISTINCT ts_code FROM ({lifecycle_sql}) stock_lifecycle
      WHERE list_date <= DATE '{trade_date}'
        AND (delist_date IS NULL OR DATE '{trade_date}' < delist_date)
        AND ({listed_filter})
    ),
    full_day_suspended AS (
      SELECT DISTINCT suspend.ts_code
      FROM {read_parquet(suspend_path, hive_partitioning=False)} suspend
      INNER JOIN listed USING (ts_code)
      WHERE suspend.trade_date = DATE '{trade_date}'
        AND suspend.suspend_type = 'S' AND suspend.suspend_timing IS NULL
    ),
    intraday_suspended AS (
      SELECT DISTINCT suspend.ts_code,suspend.suspend_type,suspend.suspend_timing
      FROM {read_parquet(suspend_path, hive_partitioning=False)} suspend
      INNER JOIN listed USING (ts_code)
      WHERE suspend.trade_date = DATE '{trade_date}'
        AND suspend.suspend_type = 'S' AND suspend.suspend_timing IS NOT NULL
    ),
    expected AS (
      SELECT ts_code FROM listed EXCEPT SELECT ts_code FROM full_day_suspended
    )"""
