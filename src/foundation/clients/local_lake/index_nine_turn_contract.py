from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from src.foundation.clients.local_lake.major_index_mins_contract import (
    GOLD_BAR_COLUMN_SPECS,
)


FORMAL_LAKE_ROOT: Final = Path("/Volumes/datasource/data_lake")
SUPPORTED_INDEX_NINE_TURN_FREQS: Final = (5, 15, 30, 60, 90, 120)
EXPECTED_INDEX_BARS_PER_SESSION: Final = {
    5: 48,
    15: 16,
    30: 8,
    60: 4,
    90: 3,
    120: 2,
}
MAX_INDEX_NINE_TURN_LIMIT: Final = 10_000
MAX_INDEX_NINE_TURN_PARTITION_FILES: Final = 5_000
INDEX_TS_CODE_PATTERN: Final = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
TRADE_DATE_PARTITION_PATTERN: Final = re.compile(r"^trade_date=(\d{4}-\d{2}-\d{2})$")

BAR_COLUMN_SPECS: Final = GOLD_BAR_COLUMN_SPECS
NINE_TURN_COLUMN_SPECS: Final = (
    ("ts_code", "VARCHAR"),
    ("freq", "INTEGER"),
    ("trade_date", "DATE"),
    ("trade_time", "TIMESTAMP"),
    ("close", "DOUBLE"),
    ("up_count", "INTEGER"),
    ("down_count", "INTEGER"),
    ("nine_up_turn", "VARCHAR"),
    ("nine_down_turn", "VARCHAR"),
)


def index_minute_bar_dataset_root(lake_root: Path) -> Path:
    return _bounded_dataset_root(lake_root, Path("gold/quote/major_index_mins"))


def index_minute_nine_turn_dataset_root(lake_root: Path) -> Path:
    return _bounded_dataset_root(
        lake_root,
        Path("gold/indicator/major_index_mins_nineturn"),
    )


def _bounded_dataset_root(lake_root: Path, relative: Path) -> Path:
    root = lake_root.expanduser().resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("指数九转分钟数据集路径越界。")
    return candidate


__all__ = [
    "BAR_COLUMN_SPECS",
    "EXPECTED_INDEX_BARS_PER_SESSION",
    "FORMAL_LAKE_ROOT",
    "INDEX_TS_CODE_PATTERN",
    "MAX_INDEX_NINE_TURN_LIMIT",
    "MAX_INDEX_NINE_TURN_PARTITION_FILES",
    "NINE_TURN_COLUMN_SPECS",
    "SUPPORTED_INDEX_NINE_TURN_FREQS",
    "TRADE_DATE_PARTITION_PATTERN",
    "index_minute_bar_dataset_root",
    "index_minute_nine_turn_dataset_root",
]
