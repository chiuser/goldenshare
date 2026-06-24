from pathlib import Path

from orchestrator.defs.run_contracts.stk_mins import (
    normalize_stk_mins_freq,
    normalize_stk_mins_qfq_freq,
)

DEFAULT_LAKE_ROOT = "/Volumes/datasource/data_lake"
PATH_TEMPLATE_LAKE_ROOT = Path("data_lake")
PATH_TEMPLATE_PARTITION_KEY = "{partition_key}"
PATH_TEMPLATE_TS_CODE = "{ts_code}"
PATH_TEMPLATE_YEAR = "{year}"

RAW = "raw"
SILVER = "silver"
GOLD = "gold"
LAYERS = {RAW, SILVER, GOLD}

FORBIDDEN_NEW_LAKE_PARTS = {
    "raw_tushare",
    "manifest",
    "derived",
    "research",
    "lake_jobs",
    "duckdb_compute",
}


def lake_path(root: Path, layer: str, *parts: str) -> Path:
    if layer not in LAYERS:
        raise ValueError(f"Unsupported lake layer: {layer}")

    forbidden = FORBIDDEN_NEW_LAKE_PARTS.intersection(parts)
    if forbidden:
        names = ", ".join(sorted(forbidden))
        raise ValueError(f"New Dagster lake paths must not contain legacy path parts: {names}")

    return root / layer / Path(*parts)


def lake_path_template(path: Path) -> str:
    return path.as_posix()


def raw_trade_calendar_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "trade_calendar", "full", "part-000.parquet")


def silver_trade_calendar_path(root: Path) -> Path:
    return lake_path(root, SILVER, "calendar", "trade_calendar", "full", "part-000.parquet")


def raw_stock_basic_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "stock_basic", "full", "part-000.parquet")


def silver_stock_basic_path(root: Path) -> Path:
    return lake_path(root, SILVER, "basic", "stock_basic", "full", "part-000.parquet")


def silver_stock_lifecycle_path(root: Path) -> Path:
    return lake_path(
        root,
        SILVER,
        "basic",
        "stock_lifecycle",
        "full",
        "part-000.parquet",
    )


def raw_namechange_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "namechange", "full", "part-000.parquet")


def silver_namechange_path(root: Path) -> Path:
    return lake_path(root, SILVER, "basic", "namechange", "full", "part-000.parquet")


def silver_stock_identity_map_path(root: Path) -> Path:
    return lake_path(root, SILVER, "basic", "stock_identity_map", "part-000.parquet")


def raw_stock_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "stock_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_stk_mins_path(root: Path, freq: int | str, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "stk_mins",
        f"freq={normalize_stk_mins_freq(freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_stk_mins_path(root: Path, freq: int | str, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "stk_mins",
        f"freq={normalize_stk_mins_freq(freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def _gold_stk_mins_qfq_ts_code_part(ts_code: str) -> str:
    if not ts_code or "/" in ts_code:
        raise ValueError("gold stk_mins qfq ts_code must be non-empty and must not contain '/'")

    return f"ts_code={ts_code}"


def _gold_stk_mins_qfq_year_part(year: int | str) -> str:
    year_value = str(year)
    if year_value == PATH_TEMPLATE_YEAR:
        return f"year={year_value}"
    if len(year_value) != 4 or not year_value.isdigit():
        raise ValueError("gold stk_mins qfq year must be a four-digit year")

    return f"year={year_value}"


def gold_stk_mins_qfq_path(root: Path, freq: int | str, ts_code: str, year: int | str) -> Path:
    return lake_path(
        root,
        GOLD,
        "quote",
        "stk_mins_qfq",
        f"freq={normalize_stk_mins_qfq_freq(freq)}",
        _gold_stk_mins_qfq_ts_code_part(ts_code),
        _gold_stk_mins_qfq_year_part(year),
        "part-000.parquet",
    )


def gold_stk_mins_qfq_macd_kdj_path(
    root: Path,
    freq: int | str,
    ts_code: str,
    year: int | str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "stk_mins_qfq_macd_kdj",
        f"freq={normalize_stk_mins_qfq_freq(freq)}",
        _gold_stk_mins_qfq_ts_code_part(ts_code),
        _gold_stk_mins_qfq_year_part(year),
        "part-000.parquet",
    )


def gold_stk_mins_qfq_macd_kdj_state_path(
    root: Path,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "stk_mins_qfq_macd_kdj_state",
        f"freq={normalize_stk_mins_qfq_freq(freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_adj_factor_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "adj_factor",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_suspend_d_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "suspend_d",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_stock_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "stock_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_adj_factor_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "adj_factor",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_stock_suspend_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "stock_suspend_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_market_breadth_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "breadth",
        "market_breadth_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_stock_return_distribution_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "breadth",
        "stock_return_distribution",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_index_basic_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "index_basic", "full", "part-000.parquet")


def silver_index_basic_path(root: Path) -> Path:
    return lake_path(root, SILVER, "index_basic", "full", "part-000.parquet")


def raw_index_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "index_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_index_daily_staging_path(
    root: Path,
    run_id: str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        RAW,
        "index_daily",
        "_staging",
        f"run_id={run_id}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_index_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "index_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_market_major_indices_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "market",
        "major_indices_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )
