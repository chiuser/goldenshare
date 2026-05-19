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
