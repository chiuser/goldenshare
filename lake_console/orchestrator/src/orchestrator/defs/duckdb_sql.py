from pathlib import Path

from orchestrator.defs.corrections.suspend_full_day import (
    suspend_full_day_raw_overrides_values_sql,
    suspend_full_day_ranges_values_sql,
)
from orchestrator.defs.corrections.suspend_timing import (
    suspend_timing_corrections_values_sql,
)

STOCK_DAILY_MIN_TRADE_DATE = "2014-01-01"
BJ_MARKET_OPEN_DATE = "2021-11-15"

TRADE_CALENDAR_RAW_REQUIRED_COLUMNS = (
    "exchange",
    "cal_date",
    "is_open",
    "pretrade_date",
)

TRADE_CALENDAR_SILVER_REQUIRED_COLUMNS = (
    "exchange",
    "trade_date",
    "is_open",
    "pretrade_date",
)

TRADE_CALENDAR_BOOTSTRAP_SELECT_TEMPLATE = """
SELECT
  CAST(exchange AS VARCHAR) AS exchange,
  CASE
    WHEN cal_date IS NULL OR trim(CAST(cal_date AS VARCHAR)) = '' THEN NULL
    ELSE strftime(CAST(CAST(cal_date AS VARCHAR) AS DATE), '%Y%m%d')
  END AS cal_date,
  CASE
    WHEN is_open IS NULL THEN NULL
    WHEN CAST(is_open AS VARCHAR) IN ('true', 'TRUE', 'True', '1') THEN 1
    WHEN CAST(is_open AS VARCHAR) IN ('false', 'FALSE', 'False', '0') THEN 0
    ELSE NULL
  END AS is_open,
  CASE
    WHEN pretrade_date IS NULL OR trim(CAST(pretrade_date AS VARCHAR)) = '' THEN NULL
    ELSE strftime(CAST(CAST(pretrade_date AS VARCHAR) AS DATE), '%Y%m%d')
  END AS pretrade_date
FROM read_parquet({old_path}, hive_partitioning=false, union_by_name=true)
"""

STOCK_BASIC_RAW_COLUMNS = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "fullname",
    "enname",
    "cnspell",
    "market",
    "exchange",
    "curr_type",
    "list_status",
    "list_date",
    "delist_date",
    "is_hs",
    "act_name",
    "act_ent_type",
)

STOCK_BASIC_RAW_REQUIRED_COLUMNS = (
    "ts_code",
    "symbol",
    "name",
    "market",
    "exchange",
    "list_status",
    "list_date",
    "delist_date",
)

STOCK_BASIC_SILVER_REQUIRED_COLUMNS = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "market",
    "exchange",
    "list_status",
    "list_date",
    "delist_date",
    "is_hs",
)

STOCK_BASIC_KNOWN_LIST_STATUS_VALUES = ("L", "D", "P", "G")

STOCK_BASIC_BOOTSTRAP_SELECT_TEMPLATE = """
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CAST(symbol AS VARCHAR) AS symbol,
  CAST(name AS VARCHAR) AS name,
  CAST(area AS VARCHAR) AS area,
  CAST(industry AS VARCHAR) AS industry,
  CAST(fullname AS VARCHAR) AS fullname,
  CAST(enname AS VARCHAR) AS enname,
  CAST(cnspell AS VARCHAR) AS cnspell,
  CAST(market AS VARCHAR) AS market,
  CAST(exchange AS VARCHAR) AS exchange,
  CAST(curr_type AS VARCHAR) AS curr_type,
  CAST(list_status AS VARCHAR) AS list_status,
  CASE
    WHEN list_date IS NULL OR trim(CAST(list_date AS VARCHAR)) = '' THEN NULL
    ELSE CAST(list_date AS VARCHAR)
  END AS list_date,
  CASE
    WHEN delist_date IS NULL OR trim(CAST(delist_date AS VARCHAR)) = '' THEN NULL
    ELSE CAST(delist_date AS VARCHAR)
  END AS delist_date,
  CAST(is_hs AS VARCHAR) AS is_hs,
  CAST(act_name AS VARCHAR) AS act_name,
  CAST(act_ent_type AS VARCHAR) AS act_ent_type
FROM read_parquet({old_path}, hive_partitioning=false, union_by_name=true)
"""

STOCK_DAILY_RAW_REQUIRED_COLUMNS = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)

STOCK_DAILY_SILVER_REQUIRED_COLUMNS = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change_amount",
    "pct_chg",
    "vol",
    "amount",
)

STOCK_DAILY_BOOTSTRAP_SELECT_TEMPLATE = """
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CASE
    WHEN trade_date IS NULL OR trim(CAST(trade_date AS VARCHAR)) = '' THEN NULL
    WHEN regexp_matches(trim(CAST(trade_date AS VARCHAR)), '^\\d{{8}}$')
      THEN trim(CAST(trade_date AS VARCHAR))
    ELSE strftime(CAST(trade_date AS DATE), '%Y%m%d')
  END AS trade_date,
  CAST(open AS DOUBLE) AS open,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(close AS DOUBLE) AS close,
  CAST(pre_close AS DOUBLE) AS pre_close,
  CAST(change AS DOUBLE) AS change,
  CAST(pct_chg AS DOUBLE) AS pct_chg,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount
FROM read_parquet({old_path}, hive_partitioning=false, union_by_name=true)
"""

SUSPEND_D_RAW_COLUMNS = (
    "ts_code",
    "trade_date",
    "suspend_timing",
    "suspend_type",
)

SUSPEND_D_RAW_REQUIRED_COLUMNS = SUSPEND_D_RAW_COLUMNS

SUSPEND_D_SILVER_REQUIRED_COLUMNS = SUSPEND_D_RAW_COLUMNS

SUSPEND_D_KNOWN_TYPE_VALUES = ("S", "R")

SUSPEND_D_BOOTSTRAP_SELECT_TEMPLATE = """
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  strftime(CAST(trade_date AS DATE), '%Y%m%d') AS trade_date,
  CAST(suspend_timing AS VARCHAR) AS suspend_timing,
  CAST(suspend_type AS VARCHAR) AS suspend_type
FROM read_parquet({old_path}, hive_partitioning=false, union_by_name=true)
"""

MARKET_BREADTH_DAILY_COLUMNS = (
    "trade_date",
    "up_count",
    "down_count",
    "flat_count",
    "total_count",
    "red_rate",
)


def duckdb_string(value: str | Path) -> str:
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def read_parquet(
    path: Path,
    *,
    hive_partitioning: bool = False,
    union_by_name: bool = False,
) -> str:
    hive = "true" if hive_partitioning else "false"
    union = ", union_by_name=true" if union_by_name else ""
    return f"read_parquet({duckdb_string(path)}, hive_partitioning={hive}{union})"


def describe_parquet_query(path: Path, *, hive_partitioning: bool = False) -> str:
    return f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=hive_partitioning)}"


def count_parquet_query(path: Path, *, hive_partitioning: bool = False) -> str:
    return f"SELECT count(*) AS row_count FROM {read_parquet(path, hive_partitioning=hive_partitioning)}"


def silver_trade_calendar_select(raw_path: Path) -> str:
    return f"""
SELECT
  exchange,
  CAST(strptime(cal_date, '%Y%m%d') AS DATE) AS trade_date,
  CASE
    WHEN is_open = 1 THEN true
    WHEN is_open = 0 THEN false
    ELSE NULL
  END AS is_open,
  CASE
    WHEN pretrade_date IS NULL OR pretrade_date = '' THEN NULL
    ELSE CAST(strptime(pretrade_date, '%Y%m%d') AS DATE)
  END AS pretrade_date
FROM {read_parquet(raw_path, hive_partitioning=False)}
"""


def silver_stock_basic_select(raw_path: Path) -> str:
    return f"""
SELECT
  ts_code,
  symbol,
  name,
  area,
  industry,
  market,
  exchange,
  list_status,
  CASE
    WHEN list_date IS NULL OR trim(list_date) = '' THEN NULL
    ELSE CAST(strptime(list_date, '%Y%m%d') AS DATE)
  END AS list_date,
  CASE
    WHEN delist_date IS NULL OR trim(delist_date) = '' THEN NULL
    ELSE CAST(strptime(delist_date, '%Y%m%d') AS DATE)
  END AS delist_date,
  is_hs
FROM {read_parquet(raw_path, hive_partitioning=False)}
WHERE list_status = 'L'
"""


def stock_daily_normalized_select(raw_path: Path) -> str:
    return f"""
SELECT
  ts_code,
  CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date,
  CAST(open AS DOUBLE) AS open,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(close AS DOUBLE) AS close,
  CAST(pre_close AS DOUBLE) AS pre_close,
  CAST(change AS DOUBLE) AS change_amount,
  CAST(pct_chg AS DOUBLE) AS pct_chg,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount
FROM {read_parquet(raw_path, hive_partitioning=False)}
"""


def silver_stock_daily_select(raw_path: Path, silver_stock_basic_path: Path) -> str:
    return f"""
WITH normalized AS (
  {stock_daily_normalized_select(raw_path)}
),
deduped AS (
  SELECT DISTINCT *
  FROM normalized
),
current_listed AS (
  SELECT DISTINCT ts_code, list_date
  FROM {read_parquet(silver_stock_basic_path, hive_partitioning=False)}
  WHERE list_status = 'L'
)
SELECT deduped.*
FROM deduped
INNER JOIN current_listed USING (ts_code)
WHERE deduped.trade_date >= DATE {duckdb_string(STOCK_DAILY_MIN_TRADE_DATE)}
  AND deduped.trade_date >= current_listed.list_date
  AND (
    NOT ends_with(deduped.ts_code, '.BJ')
    OR deduped.trade_date >= DATE {duckdb_string(BJ_MARKET_OPEN_DATE)}
  )
"""


def suspend_d_normalized_select(raw_path: Path) -> str:
    return f"""
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date,
  CASE
    WHEN suspend_timing IS NULL OR trim(CAST(suspend_timing AS VARCHAR)) = '' THEN NULL
    ELSE CAST(suspend_timing AS VARCHAR)
  END AS suspend_timing,
  CAST(suspend_type AS VARCHAR) AS suspend_type
FROM {read_parquet(raw_path, hive_partitioning=False)}
"""


def silver_stock_suspend_daily_select(raw_path: Path, partition_key: str) -> str:
    partition_date = f"DATE {duckdb_string(partition_key)}"
    return f"""
WITH normalized AS (
  {suspend_d_normalized_select(raw_path)}
),
corrections(ts_code, trade_date, corrected_suspend_timing) AS (
  {suspend_timing_corrections_values_sql()}
),
full_day_patch_ranges(ts_code, name, start_date, end_date) AS (
  {suspend_full_day_ranges_values_sql()}
),
full_day_raw_overrides(
  ts_code,
  name,
  trade_date,
  corrected_suspend_type,
  corrected_suspend_timing
) AS (
  {suspend_full_day_raw_overrides_values_sql()}
),
corrected AS (
  SELECT
    normalized.ts_code,
    normalized.trade_date,
    COALESCE(corrections.corrected_suspend_timing, normalized.suspend_timing)
      AS suspend_timing,
    normalized.suspend_type
  FROM normalized
  LEFT JOIN corrections
    ON normalized.ts_code = corrections.ts_code
   AND normalized.trade_date = corrections.trade_date
  WHERE NOT EXISTS (
    SELECT 1
    FROM full_day_raw_overrides
    WHERE full_day_raw_overrides.ts_code = normalized.ts_code
      AND full_day_raw_overrides.trade_date = normalized.trade_date
  )
),
full_day_patches AS (
  SELECT
    ts_code,
    {partition_date} AS trade_date,
    NULL::VARCHAR AS suspend_timing,
    'S'::VARCHAR AS suspend_type
  FROM full_day_patch_ranges
  WHERE {partition_date} BETWEEN start_date AND end_date
),
eligible_full_day_patches AS (
  SELECT full_day_patches.*
  FROM full_day_patches
  WHERE NOT EXISTS (
    SELECT 1
    FROM corrected
    WHERE corrected.ts_code = full_day_patches.ts_code
      AND corrected.trade_date = full_day_patches.trade_date
      AND corrected.suspend_type = 'S'
      AND corrected.suspend_timing IS NULL
  )
)
SELECT
  ts_code,
  trade_date,
  suspend_timing,
  suspend_type
FROM corrected
UNION ALL
SELECT
  ts_code,
  trade_date,
  suspend_timing,
  suspend_type
FROM eligible_full_day_patches
"""


def market_breadth_daily_select(silver_stock_daily_path: Path, partition_key: str) -> str:
    partition_date = f"DATE {duckdb_string(partition_key)}"
    up_count = "COALESCE(SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END), 0)"
    down_count = "COALESCE(SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END), 0)"
    flat_count = "COALESCE(SUM(CASE WHEN pct_chg = 0 THEN 1 ELSE 0 END), 0)"
    total_count = "COUNT(*)"
    return f"""
SELECT
  {partition_date} AS trade_date,
  CAST({up_count} AS BIGINT) AS up_count,
  CAST({down_count} AS BIGINT) AS down_count,
  CAST({flat_count} AS BIGINT) AS flat_count,
  CAST({total_count} AS BIGINT) AS total_count,
  CASE
    WHEN {total_count} = 0 THEN 0.0
    ELSE ROUND(({up_count}) * 100.0 / {total_count}, 2)
  END AS red_rate
FROM {read_parquet(silver_stock_daily_path, hive_partitioning=False)}
WHERE trade_date = {partition_date}
  AND pct_chg IS NOT NULL
"""

def copy_query_to_parquet(select_sql: str, target_path: Path) -> str:
    return f"COPY ({select_sql}) TO {duckdb_string(target_path)} (FORMAT PARQUET)"
