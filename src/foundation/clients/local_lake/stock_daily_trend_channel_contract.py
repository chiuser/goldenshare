from __future__ import annotations

import re
from pathlib import Path
from typing import Final


FORMAL_LAKE_ROOT: Final = Path("/Volumes/datasource/data_lake")
FORMULA_KEY: Final = "high-low-ema-hysteresis"
FORMULA_VERSION: Final = "stock-daily-trend-channel-v1"
SHORT_PERIOD: Final = 25
LONG_PERIOD: Final = 90
DEFAULT_TREND_CHANNEL_LIMIT: Final = 300
MAX_TREND_CHANNEL_LIMIT: Final = 2_000
STOCK_TS_CODE_PATTERN: Final = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
TRADE_DATE_PARTITION_PATTERN: Final = re.compile(
    r"^trade_date=(\d{4}-\d{2}-\d{2})$"
)

RESULT_COLUMN_SPECS: Final = (
    ("ts_code", "VARCHAR"),
    ("trade_date", "DATE"),
    ("open", "DOUBLE"),
    ("high", "DOUBLE"),
    ("low", "DOUBLE"),
    ("close", "DOUBLE"),
    ("short_upper", "DOUBLE"),
    ("short_lower", "DOUBLE"),
    ("short_position", "VARCHAR"),
    ("short_state", "VARCHAR"),
    ("long_upper", "DOUBLE"),
    ("long_lower", "DOUBLE"),
    ("long_position", "VARCHAR"),
    ("long_state", "VARCHAR"),
    ("combined_state", "VARCHAR"),
    ("formula_version", "VARCHAR"),
)


def stock_daily_trend_channel_dataset_root(lake_root: Path) -> Path:
    return _bounded_dataset_root(
        lake_root,
        Path("gold/indicator/stock_daily_trend_channel"),
    )


def stock_daily_trend_channel_state_dataset_root(lake_root: Path) -> Path:
    return _bounded_dataset_root(
        lake_root,
        Path("gold/indicator/stock_daily_trend_channel_state"),
    )


def _bounded_dataset_root(lake_root: Path, relative: Path) -> Path:
    root = lake_root.expanduser().resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("股票日线趋势通道数据集路径越界。")
    return candidate
