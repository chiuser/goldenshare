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
