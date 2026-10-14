"""The existing MACD/KDJ schema and coverage predicates, without resources or events."""

from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet


def macd_kdj_schema(connection, path, expected_types):
    observed = {
        str(r[0]): str(r[1]).upper()
        for r in connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchall()
    }
    return observed == {k: v.upper() for k, v in expected_types.items()}, observed


def macd_kdj_source_coverage_sql(*, source, indicator, freq, dates):
    days = ",".join(f"(DATE {duckdb_string(d)})" for d in dates)
    date_filter = ",".join(f"DATE {duckdb_string(d)}" for d in dates)
    return f"""WITH days AS (SELECT col0 AS day FROM (VALUES {days})),
      source_counts AS (SELECT CAST(trade_date AS DATE) AS day,count(*) n FROM {source}
        WHERE CAST(freq AS INTEGER)={freq} AND CAST(trade_date AS DATE) IN ({date_filter}) GROUP BY day),
      result_counts AS (SELECT CAST(trade_date AS DATE) AS day,count(*) n FROM {indicator}
        WHERE CAST(freq AS INTEGER)={freq} AND CAST(trade_date AS DATE) IN ({date_filter}) GROUP BY day)
      SELECT CAST(days.day AS VARCHAR),coalesce(source_counts.n,0),coalesce(result_counts.n,0)
      FROM days LEFT JOIN source_counts USING(day) LEFT JOIN result_counts USING(day)
      ORDER BY days.day"""


def macd_kdj_state_coverage_sql(*, indicator, state, freq, dates):
    days = ",".join(f"(DATE {duckdb_string(d)})" for d in dates)
    date_filter = ",".join(f"DATE {duckdb_string(d)}" for d in dates)
    return f"""WITH days AS (SELECT col0 AS day FROM (VALUES {days})),
      indicator_latest AS (
        SELECT CAST(trade_date AS DATE) AS day,ts_code,max(trade_time) AS last_trade_time
        FROM {indicator} WHERE CAST(freq AS INTEGER)={freq}
          AND CAST(trade_date AS DATE) IN ({date_filter}) GROUP BY day,ts_code),
      state_rows AS (SELECT CAST(trade_date AS DATE) AS day,ts_code,last_trade_time
        FROM {state} WHERE CAST(freq AS INTEGER)={freq}
          AND CAST(trade_date AS DATE) IN ({date_filter})),
      joined AS (
        SELECT coalesce(i.day,s.day) AS day,i.ts_code AS indicator_code,s.ts_code AS state_code,
          i.last_trade_time AS indicator_last_trade_time,s.last_trade_time AS state_last_trade_time
        FROM indicator_latest i FULL OUTER JOIN state_rows s USING(day,ts_code)),
      metrics AS (
        SELECT day,
          count(*) FILTER(WHERE indicator_last_trade_time IS NOT NULL AND
            (state_last_trade_time IS NULL OR indicator_last_trade_time!=state_last_trade_time)) current_mismatch,
          count(*) FILTER(WHERE state_last_trade_time IS NOT NULL AND
            CAST(state_last_trade_time AS DATE)>day) future_mismatch
        FROM joined GROUP BY day),
      indicator_counts AS (SELECT day,count(*) indicator_stock_count FROM indicator_latest GROUP BY day),
      state_counts AS (SELECT day,count(*) state_row_count FROM state_rows GROUP BY day)
      SELECT CAST(days.day AS VARCHAR),coalesce(indicator_stock_count,0),coalesce(state_row_count,0),
        coalesce(current_mismatch,0),coalesce(future_mismatch,0)
      FROM days LEFT JOIN metrics USING(day) LEFT JOIN indicator_counts USING(day)
        LEFT JOIN state_counts USING(day) ORDER BY days.day"""
