from pathlib import Path

DEFAULT_LAKE_ROOT = "/Volumes/datasource/data_lake"

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


def raw_trade_calendar_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "trade_calendar", "full", "part-000.parquet")


def silver_trade_calendar_path(root: Path) -> Path:
    return lake_path(root, SILVER, "calendar", "trade_calendar", "full", "part-000.parquet")


def raw_stock_basic_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "stock_basic", "full", "part-000.parquet")


def silver_stock_basic_path(root: Path) -> Path:
    return lake_path(root, SILVER, "basic", "stock_basic", "full", "part-000.parquet")


def raw_stock_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "stock_daily",
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


def raw_index_basic_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "index_basic", "full", "part-000.parquet")


def silver_index_basic_path(root: Path) -> Path:
    return lake_path(root, SILVER, "index_basic", "full", "part-000.parquet")


def raw_index_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "index_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_index_daily_staging_dir(root: Path, run_id: str) -> Path:
    return lake_path(root, RAW, "tushare", "index_daily", "_staging", f"run_id={run_id}")


def silver_index_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "index_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_index_daily_active_pool_path(root: Path) -> Path:
    return lake_path(root, SILVER, "index_daily_active_pool", "full", "part-000.parquet")


def gold_market_major_indices_path(root: Path) -> Path:
    return lake_path(root, GOLD, "market", "major_indices", "full", "part-000.parquet")


def gold_market_major_indices_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "market",
        "major_indices_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )
