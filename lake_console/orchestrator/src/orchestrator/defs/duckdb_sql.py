from pathlib import Path

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


def duckdb_string(value: str | Path) -> str:
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def read_parquet(path: Path, *, hive_partitioning: bool = False) -> str:
    hive = "true" if hive_partitioning else "false"
    return f"read_parquet({duckdb_string(path)}, hive_partitioning={hive})"


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


def silver_stock_daily_select(raw_path: Path) -> str:
    return f"""
SELECT DISTINCT *
FROM ({stock_daily_normalized_select(raw_path)}) normalized
"""


def cn_a_trade_day_partition_keys_select(silver_path: Path) -> str:
    return f"""
SELECT strftime(trade_date, '%Y-%m-%d') AS partition_key
FROM {read_parquet(silver_path, hive_partitioning=False)}
WHERE exchange = 'SSE'
  AND is_open = true
  AND trade_date BETWEEN DATE '2026-04-01' AND DATE '2026-04-30'
ORDER BY trade_date
"""


def copy_query_to_parquet(select_sql: str, target_path: Path) -> str:
    return f"COPY ({select_sql}) TO {duckdb_string(target_path)} (FORMAT PARQUET)"
