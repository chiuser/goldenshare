from pathlib import Path

from orchestrator.defs.corrections.suspend_full_day import (
    suspend_full_day_raw_overrides_values_sql,
    suspend_full_day_ranges_values_sql,
)
from orchestrator.defs.corrections.suspend_timing import (
    suspend_timing_corrections_values_sql,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_MINS_SCHEMA,
    RAW_INDEX_DAILY_SCHEMA,
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
    RAW_TUSHARE_INDEX_BASIC_SCHEMA,
    RAW_TUSHARE_NAMECHANGE_SCHEMA,
    RAW_TUSHARE_STOCK_BASIC_SCHEMA,
    RAW_TUSHARE_STOCK_DAILY_SCHEMA,
    RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
    RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_INDEX_BASIC_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
    SILVER_NAMECHANGE_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
    SILVER_STOCK_DAILY_SCHEMA,
    SILVER_STOCK_LIFECYCLE_SCHEMA,
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)

STOCK_DAILY_MIN_TRADE_DATE = "2014-01-01"
BJ_MARKET_OPEN_DATE = "2021-11-15"
CNY_STOCK_CURR_TYPE = "CNY"

TRADE_CALENDAR_RAW_REQUIRED_COLUMNS = tuple(
    column.name for column in RAW_TUSHARE_TRADE_CALENDAR_SCHEMA
)

TRADE_CALENDAR_SILVER_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_TRADE_CALENDAR_SCHEMA
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

STOCK_BASIC_RAW_COLUMNS = tuple(
    column.name for column in RAW_TUSHARE_STOCK_BASIC_SCHEMA
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

STOCK_BASIC_SILVER_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_STOCK_BASIC_SCHEMA
)

STOCK_LIFECYCLE_SILVER_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_STOCK_LIFECYCLE_SCHEMA
)

NAMECHANGE_RAW_COLUMNS = tuple(
    column.name for column in RAW_TUSHARE_NAMECHANGE_SCHEMA
)

NAMECHANGE_RAW_REQUIRED_COLUMNS = NAMECHANGE_RAW_COLUMNS

NAMECHANGE_SILVER_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_NAMECHANGE_SCHEMA
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

STOCK_DAILY_RAW_REQUIRED_COLUMNS = tuple(
    column.name for column in RAW_TUSHARE_STOCK_DAILY_SCHEMA
)

STOCK_DAILY_SILVER_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_STOCK_DAILY_SCHEMA
)

STK_MINS_RAW_REQUIRED_COLUMNS = tuple(column.name for column in RAW_STK_MINS_SCHEMA)

STK_MINS_SILVER_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_STK_MINS_SCHEMA
)

SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_STOCK_IDENTITY_MAP_SCHEMA
)

ADJ_FACTOR_RAW_REQUIRED_COLUMNS = tuple(
    column.name for column in RAW_TUSHARE_ADJ_FACTOR_SCHEMA
)

ADJ_FACTOR_SILVER_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_ADJ_FACTOR_SCHEMA
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

STK_MINS_BOOTSTRAP_SELECT_TEMPLATE = """
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CAST(freq AS INTEGER) AS freq,
  CAST(trade_time AS TIMESTAMP) AS trade_time,
  CAST(open AS DOUBLE) AS open,
  CAST(close AS DOUBLE) AS close,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(vol AS BIGINT) AS vol,
  CAST(amount AS DOUBLE) AS amount,
  CAST(exchange AS VARCHAR) AS exchange,
  CAST(vwap AS DOUBLE) AS vwap
FROM read_parquet({old_path}, hive_partitioning=false, union_by_name=true)
"""

STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE = """
SELECT
  CAST(latest_ts_code AS VARCHAR) AS latest_ts_code,
  CAST(source_ts_code AS VARCHAR) AS source_ts_code,
  CAST(valid_from AS DATE) AS valid_from,
  CASE
    WHEN valid_to IS NULL OR trim(CAST(valid_to AS VARCHAR)) = '' THEN NULL
    ELSE CAST(valid_to AS DATE)
  END AS valid_to,
  CAST(effective_list_date AS DATE) AS effective_list_date,
  CASE
    WHEN effective_delist_date IS NULL
      OR trim(CAST(effective_delist_date AS VARCHAR)) = ''
    THEN NULL
    ELSE CAST(effective_delist_date AS DATE)
  END AS effective_delist_date,
  CAST(identity_source AS VARCHAR) AS identity_source,
  CAST(confidence AS VARCHAR) AS confidence,
  CAST(reason AS VARCHAR) AS reason,
  CAST(created_at AS TIMESTAMP WITH TIME ZONE) AS created_at
FROM read_parquet({old_path}, hive_partitioning=false, union_by_name=true)
"""

ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE = """
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CASE
    WHEN trade_date IS NULL OR trim(CAST(trade_date AS VARCHAR)) = '' THEN NULL
    WHEN regexp_matches(trim(CAST(trade_date AS VARCHAR)), '^\\d{{8}}$')
      THEN trim(CAST(trade_date AS VARCHAR))
    ELSE strftime(CAST(trade_date AS DATE), '%Y%m%d')
  END AS trade_date,
  CAST(adj_factor AS DOUBLE) AS adj_factor
FROM read_parquet({old_path}, hive_partitioning=false, union_by_name=true)
"""

SUSPEND_D_RAW_COLUMNS = tuple(
    column.name for column in RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA
)

SUSPEND_D_RAW_REQUIRED_COLUMNS = SUSPEND_D_RAW_COLUMNS

SUSPEND_D_SILVER_REQUIRED_COLUMNS = tuple(
    column.name for column in SILVER_STOCK_SUSPEND_DAILY_SCHEMA
)

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

INDEX_BASIC_RAW_COLUMNS = tuple(
    column.name for column in RAW_TUSHARE_INDEX_BASIC_SCHEMA
)

INDEX_BASIC_SILVER_COLUMNS = tuple(column.name for column in SILVER_INDEX_BASIC_SCHEMA)

INDEX_DAILY_RAW_COLUMNS = tuple(
    column.name for column in RAW_INDEX_DAILY_SCHEMA
)

INDEX_DAILY_SILVER_COLUMNS = tuple(column.name for column in SILVER_INDEX_DAILY_SCHEMA)


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
    WHEN list_date IS NULL OR trim(list_date) = '' THEN NULL
    ELSE CAST(strptime(list_date, '%Y%m%d') AS DATE)
  END AS list_date,
  CASE
    WHEN delist_date IS NULL OR trim(delist_date) = '' THEN NULL
    ELSE CAST(strptime(delist_date, '%Y%m%d') AS DATE)
  END AS delist_date,
  CAST(is_hs AS VARCHAR) AS is_hs,
  CAST(act_name AS VARCHAR) AS act_name,
  CAST(act_ent_type AS VARCHAR) AS act_ent_type
FROM {read_parquet(raw_path, hive_partitioning=False)}
WHERE list_status = 'L'
  AND curr_type = {duckdb_string(CNY_STOCK_CURR_TYPE)}
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


def current_cny_stock_basic_select(silver_stock_basic_path: Path) -> str:
    return f"""
SELECT DISTINCT
  ts_code,
  list_date
FROM {read_parquet(silver_stock_basic_path, hive_partitioning=False)}
WHERE list_status = 'L'
  AND curr_type = {duckdb_string(CNY_STOCK_CURR_TYPE)}
"""


def silver_stock_lifecycle_select(raw_stock_basic_path: Path) -> str:
    return f"""
SELECT DISTINCT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CAST(symbol AS VARCHAR) AS symbol,
  CAST(name AS VARCHAR) AS name,
  CAST(exchange AS VARCHAR) AS exchange,
  CAST(market AS VARCHAR) AS market,
  CAST(curr_type AS VARCHAR) AS curr_type,
  CAST(curr_type AS VARCHAR) = {duckdb_string(CNY_STOCK_CURR_TYPE)} AS is_cny_stock,
  CAST(list_status AS VARCHAR) AS list_status,
  CASE
    WHEN list_date IS NULL OR trim(CAST(list_date AS VARCHAR)) = '' THEN NULL
    ELSE CAST(try_strptime(CAST(list_date AS VARCHAR), '%Y%m%d') AS DATE)
  END AS list_date,
  CASE
    WHEN delist_date IS NULL OR trim(CAST(delist_date AS VARCHAR)) = '' THEN NULL
    ELSE CAST(try_strptime(CAST(delist_date AS VARCHAR), '%Y%m%d') AS DATE)
  END AS delist_date
FROM {read_parquet(raw_stock_basic_path, hive_partitioning=False)}
WHERE curr_type = {duckdb_string(CNY_STOCK_CURR_TYPE)}
"""


def historical_cny_stock_lifecycle_select(raw_stock_basic_path: Path) -> str:
    return f"""
SELECT DISTINCT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CASE
    WHEN list_date IS NULL OR trim(CAST(list_date AS VARCHAR)) = '' THEN NULL
    ELSE CAST(strptime(CAST(list_date AS VARCHAR), '%Y%m%d') AS DATE)
  END AS list_date,
  CASE
    WHEN delist_date IS NULL OR trim(CAST(delist_date AS VARCHAR)) = '' THEN NULL
    ELSE CAST(strptime(CAST(delist_date AS VARCHAR), '%Y%m%d') AS DATE)
  END AS delist_date
FROM {read_parquet(raw_stock_basic_path, hive_partitioning=False)}
WHERE curr_type = {duckdb_string(CNY_STOCK_CURR_TYPE)}
  AND ts_code IS NOT NULL
  AND trim(CAST(ts_code AS VARCHAR)) != ''
  AND list_date IS NOT NULL
  AND trim(CAST(list_date AS VARCHAR)) != ''
"""


def silver_cny_stock_lifecycle_select(silver_stock_lifecycle_path: Path) -> str:
    return f"""
SELECT DISTINCT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CAST(list_date AS DATE) AS list_date,
  CAST(delist_date AS DATE) AS delist_date
FROM {read_parquet(silver_stock_lifecycle_path, hive_partitioning=False)}
WHERE is_cny_stock
  AND ts_code IS NOT NULL
  AND trim(CAST(ts_code AS VARCHAR)) != ''
  AND list_date IS NOT NULL
"""


def silver_stock_daily_select(raw_path: Path, stock_lifecycle_path: Path) -> str:
    return f"""
WITH normalized AS (
  {stock_daily_normalized_select(raw_path)}
),
deduped AS (
  SELECT DISTINCT *
  FROM normalized
),
stock_lifecycle AS (
  {silver_cny_stock_lifecycle_select(stock_lifecycle_path)}
)
SELECT deduped.*
FROM deduped
INNER JOIN stock_lifecycle USING (ts_code)
WHERE deduped.trade_date >= DATE {duckdb_string(STOCK_DAILY_MIN_TRADE_DATE)}
  AND deduped.trade_date >= stock_lifecycle.list_date
  AND (
    stock_lifecycle.delist_date IS NULL
    OR deduped.trade_date < stock_lifecycle.delist_date
  )
  AND (
    NOT ends_with(deduped.ts_code, '.BJ')
    OR deduped.trade_date >= DATE {duckdb_string(BJ_MARKET_OPEN_DATE)}
  )
"""


def adj_factor_normalized_select(raw_path: Path) -> str:
    return f"""
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date,
  CAST(adj_factor AS DOUBLE) AS adj_factor
FROM {read_parquet(raw_path, hive_partitioning=False)}
"""


def silver_adj_factor_select(raw_path: Path, stock_lifecycle_path: Path) -> str:
    return f"""
WITH normalized AS (
  {adj_factor_normalized_select(raw_path)}
),
stock_lifecycle AS (
  {silver_cny_stock_lifecycle_select(stock_lifecycle_path)}
)
SELECT normalized.*
FROM normalized
INNER JOIN stock_lifecycle USING (ts_code)
WHERE normalized.trade_date >= stock_lifecycle.list_date
  AND (
    stock_lifecycle.delist_date IS NULL
    OR normalized.trade_date < stock_lifecycle.delist_date
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
"""


def stock_return_distribution_select(silver_stock_daily_path: Path, partition_key: str) -> str:
    partition_date = f"DATE {duckdb_string(partition_key)}"
    down_gt_10 = "COALESCE(SUM(CASE WHEN pct_chg < -10 THEN 1 ELSE 0 END), 0)"
    down_7_10 = "COALESCE(SUM(CASE WHEN pct_chg >= -10 AND pct_chg < -7 THEN 1 ELSE 0 END), 0)"
    down_5_7 = "COALESCE(SUM(CASE WHEN pct_chg >= -7 AND pct_chg < -5 THEN 1 ELSE 0 END), 0)"
    down_3_5 = "COALESCE(SUM(CASE WHEN pct_chg >= -5 AND pct_chg < -3 THEN 1 ELSE 0 END), 0)"
    down_0_3 = "COALESCE(SUM(CASE WHEN pct_chg >= -3 AND pct_chg < 0 THEN 1 ELSE 0 END), 0)"
    flat = "COALESCE(SUM(CASE WHEN pct_chg = 0 THEN 1 ELSE 0 END), 0)"
    up_0_3 = "COALESCE(SUM(CASE WHEN pct_chg > 0 AND pct_chg <= 3 THEN 1 ELSE 0 END), 0)"
    up_3_5 = "COALESCE(SUM(CASE WHEN pct_chg > 3 AND pct_chg <= 5 THEN 1 ELSE 0 END), 0)"
    up_5_7 = "COALESCE(SUM(CASE WHEN pct_chg > 5 AND pct_chg <= 7 THEN 1 ELSE 0 END), 0)"
    up_7_10 = "COALESCE(SUM(CASE WHEN pct_chg > 7 AND pct_chg <= 10 THEN 1 ELSE 0 END), 0)"
    up_gt_10 = "COALESCE(SUM(CASE WHEN pct_chg > 10 THEN 1 ELSE 0 END), 0)"
    total_count = "COUNT(*)"
    return f"""
SELECT
  {partition_date} AS trade_date,
  CAST({down_gt_10} AS BIGINT) AS down_gt_10_count,
  CAST({down_7_10} AS BIGINT) AS down_7_10_count,
  CAST({down_5_7} AS BIGINT) AS down_5_7_count,
  CAST({down_3_5} AS BIGINT) AS down_3_5_count,
  CAST({down_0_3} AS BIGINT) AS down_0_3_count,
  CAST({flat} AS BIGINT) AS flat_count,
  CAST({up_0_3} AS BIGINT) AS up_0_3_count,
  CAST({up_3_5} AS BIGINT) AS up_3_5_count,
  CAST({up_5_7} AS BIGINT) AS up_5_7_count,
  CAST({up_7_10} AS BIGINT) AS up_7_10_count,
  CAST({up_gt_10} AS BIGINT) AS up_gt_10_count,
  CAST({total_count} AS BIGINT) AS total_count
FROM {read_parquet(silver_stock_daily_path, hive_partitioning=False)}
WHERE trade_date = {partition_date}
"""


def _index_basic_date_expression(column_name: str) -> str:
    return f"""
CASE
  WHEN {column_name} IS NULL OR trim(CAST({column_name} AS VARCHAR)) = '' THEN NULL
  ELSE CAST(try_strptime(trim(CAST({column_name} AS VARCHAR)), '%Y%m%d') AS DATE)
END
"""


def silver_index_basic_select(raw_path: Path, ready_for_trade_date: str) -> str:
    ready_date = f"DATE {duckdb_string(ready_for_trade_date)}"
    return f"""
WITH normalized AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(name AS VARCHAR) AS name,
    CAST(fullname AS VARCHAR) AS fullname,
    CAST(market AS VARCHAR) AS market,
    CAST(publisher AS VARCHAR) AS publisher,
    CAST(index_type AS VARCHAR) AS index_type,
    CAST(category AS VARCHAR) AS category,
    {_index_basic_date_expression("base_date")} AS base_date,
    CAST(base_point AS DOUBLE) AS base_point,
    {_index_basic_date_expression("list_date")} AS list_date,
    CAST(weight_rule AS VARCHAR) AS weight_rule,
    CAST("desc" AS VARCHAR) AS "desc",
    {_index_basic_date_expression("exp_date")} AS exp_date
  FROM {read_parquet(raw_path, hive_partitioning=False)}
)
SELECT *
FROM normalized
WHERE exp_date IS NULL OR exp_date > {ready_date}
"""


def copy_query_to_parquet(select_sql: str, target_path: Path) -> str:
    return f"COPY ({select_sql}) TO {duckdb_string(target_path)} (FORMAT PARQUET)"
